#!/usr/bin/env bash
# =============================================================================
# WALL-E Audio Setup — Smart Pi Audio Configuration
# =============================================================================
# Automatically detects whether the Pi is running PipeWire or PulseAudio
# and configures the correct audio stack.
#
# Raspberry Pi OS Bookworm  → PipeWire  (default since 2023)
# Raspberry Pi OS Bullseye  → PulseAudio (older)
#
# Run ONCE on the Pi as the walle user (not root):
#   bash ~/walle/scripts/setup_audio_pi.sh
# =============================================================================

set -uo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${GREEN}[SETUP]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*"; }
info() { echo -e "${BLUE}[INFO]${NC}  $*"; }

# ── Sanity checks ─────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] && { err "Run as the walle user, NOT as root."; exit 1; }

log "=== WALL-E Smart Audio Setup ==="
info "User: $(whoami) | Home: $HOME"

# ── 1. Detect audio server (PipeWire vs PulseAudio) ──────────────────────────
log "Detecting audio server..."

USING_PIPEWIRE=false
USING_PULSEAUDIO=false

if systemctl --user is-active pipewire.service &>/dev/null 2>&1; then
    USING_PIPEWIRE=true
    log "Detected: PipeWire (Raspberry Pi OS Bookworm)"
elif systemctl --user is-active pulseaudio.service &>/dev/null 2>&1; then
    USING_PULSEAUDIO=true
    log "Detected: PulseAudio (Raspberry Pi OS Bullseye)"
elif pgrep -x pipewire &>/dev/null; then
    USING_PIPEWIRE=true
    log "Detected: PipeWire (running directly)"
elif pgrep -x pulseaudio &>/dev/null; then
    USING_PULSEAUDIO=true
    log "Detected: PulseAudio (running directly)"
elif command -v pipewire &>/dev/null; then
    USING_PIPEWIRE=true
    warn "PipeWire installed but not running — treating as PipeWire system."
else
    warn "No audio server detected — will install PulseAudio."
    USING_PULSEAUDIO=true
fi

info "PipeWire=$USING_PIPEWIRE | PulseAudio=$USING_PULSEAUDIO"

# ── 2. Install required packages ──────────────────────────────────────────────
log "Installing base audio packages..."
sudo apt-get update -qq

if [[ "$USING_PIPEWIRE" == "true" ]]; then
    # PipeWire path — install wireplumber + pipewire-pulse compat layer
    sudo apt-get install -y \
        pipewire \
        pipewire-pulse \
        wireplumber \
        alsa-utils \
        libpulse0 2>/dev/null || warn "Some packages failed — continuing."
    log "PipeWire packages installed."
else
    # PulseAudio path
    sudo apt-get install -y \
        pulseaudio \
        pulseaudio-utils \
        alsa-utils \
        libpulse0 2>/dev/null || warn "Some packages failed — continuing."
    log "PulseAudio packages installed."
fi

# Make sure user is in audio group
sudo usermod -a -G audio "$USER" 2>/dev/null || true
log "User added to audio group."

# ── 3. Detect USB microphone ─────────────────────────────────────────────────
log "Detecting USB microphone..."
USB_CARD=$(arecord -l 2>/dev/null | grep -i "usb\|pnp\|mic" | head -1 | grep -oP 'card \K\d+' || echo "")
if [[ -z "$USB_CARD" ]]; then
    warn "USB mic not detected by arecord. Using card index 2 as default."
    USB_CARD="2"
fi
log "USB microphone on ALSA card: $USB_CARD"

# ─────────────────────────────────────────────────────────────────────────────
# ── PIPEWIRE PATH ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
if [[ "$USING_PIPEWIRE" == "true" ]]; then
    log ""
    log "=== Configuring PipeWire (Bookworm) ==="
    log "PipeWire already handles resampling, device management, and AGC."
    log "No complex configuration needed — just set volume and verify."

    # Ensure PipeWire + WirePlumber are running
    systemctl --user start pipewire.service 2>/dev/null || true
    systemctl --user start pipewire-pulse.service 2>/dev/null || true
    systemctl --user start wireplumber.service 2>/dev/null || true
    sleep 2

    # Set mic volume to 100% via pactl (pipewire-pulse compat handles this)
    log "Setting mic volume to 100%..."
    pactl set-source-volume @DEFAULT_SOURCE@ 100% 2>/dev/null || warn "pactl not responding yet (retry after reboot)"
    pactl set-source-mute @DEFAULT_SOURCE@ 0 2>/dev/null || true

    # Enable linger so services start at boot without login
    sudo loginctl enable-linger "$USER" 2>/dev/null || warn "linger not available (not critical)"

    # Enable services at boot
    systemctl --user enable pipewire.service 2>/dev/null || true
    systemctl --user enable pipewire-pulse.service 2>/dev/null || true
    systemctl --user enable wireplumber.service 2>/dev/null || true

    # Verify
    log ""
    log "=== PipeWire Audio Verification ==="
    info "Audio sources visible to WALL-E:"
    pactl list sources short 2>/dev/null || warn "PipeWire-pulse not responding yet"
    info ""
    info "Default source: $(pactl get-default-source 2>/dev/null || echo 'unknown')"
    info ""

    # Update .env for PipeWire mode
    WALLE_ENV="$HOME/walle/.env"
    if [[ -f "$WALLE_ENV" ]]; then
        log "Updating .env for PipeWire mode..."
        # PipeWire handles resampling — request 16000Hz directly
        sed -i 's/WALLE_CAPTURE_RATE=.*/WALLE_CAPTURE_RATE=16000/' "$WALLE_ENV" 2>/dev/null || \
            echo "WALLE_CAPTURE_RATE=16000" >> "$WALLE_ENV"
        sed -i 's/WALLE_SAMPLE_RATE=.*/WALLE_SAMPLE_RATE=16000/' "$WALLE_ENV" 2>/dev/null || \
            echo "WALLE_SAMPLE_RATE=16000" >> "$WALLE_ENV"
        # Keep a moderate gain since PipeWire doesn't do AGC by default
        # (increase to 4.0 or 8.0 if mic is still quiet after testing)
        sed -i 's/WALLE_MIC_GAIN=.*/WALLE_MIC_GAIN=4.0/' "$WALLE_ENV" 2>/dev/null || \
            echo "WALLE_MIC_GAIN=4.0" >> "$WALLE_ENV"
        # Use default device — PipeWire manages selection
        sed -i 's/WALLE_MIC_DEVICE=.*/WALLE_MIC_DEVICE=/' "$WALLE_ENV" 2>/dev/null || \
            echo "WALLE_MIC_DEVICE=" >> "$WALLE_ENV"
        log ".env updated for PipeWire."
    fi

    # Test recording via parecord
    log "Testing microphone (2 seconds)..."
    parecord --channels=1 --rate=16000 --format=s16le /tmp/walle_test.wav & REC_PID=$!
    sleep 2
    kill $REC_PID 2>/dev/null || true
    if [[ -f /tmp/walle_test.wav ]]; then
        SIZE=$(wc -c < /tmp/walle_test.wav)
        if [[ $SIZE -gt 1000 ]]; then
            log "✅ Microphone recording: SUCCESS ($SIZE bytes)"
        else
            warn "Recording too small ($SIZE bytes). Mic may be muted or wrong device selected."
            warn "Check: pactl list sources short | grep -i usb"
        fi
    else
        warn "No recording produced. Run: parecord --channels=1 --rate=16000 /tmp/test.wav"
    fi

    log ""
    log "==================================="
    log "✅ PipeWire Audio Setup Complete!"
    log "==================================="
    log ""
    log "What PipeWire gives you automatically:"
    log "  ✓ Sample rate conversion (44100 Hz → 16000 Hz) — transparent"
    log "  ✓ Device hot-plug detection — no restart needed when mic reconnects"
    log "  ✓ Low-latency audio — optimized for Raspberry Pi"
    log "  ✓ Starts automatically at boot via systemd user services"
    log ""
    log "Note: Software gain is set to 4.0x in .env."
    log "  If WALL-E is still not hearing you: increase WALLE_MIC_GAIN to 8.0 or 16.0"
    log "  If WALL-E activates on background noise: decrease to 2.0"
    log ""
    log "Next steps:"
    log "  1. sudo systemctl restart walle-hw"
    log "  2. sudo journalctl -u walle-hw -f"
    log "  3. Say 'WALL-E' at normal speaking volume"

    exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
# ── PULSEAUDIO PATH (Bullseye / older Pi OS) ──────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
log ""
log "=== Configuring PulseAudio (Bullseye) ==="

# Kill any existing PulseAudio
pulseaudio --kill 2>/dev/null || true
sleep 1

# Write PulseAudio daemon.conf (no idle-timeout — that's PipeWire-only)
log "Writing PulseAudio daemon.conf..."
mkdir -p ~/.config/pulse
cat > ~/.config/pulse/daemon.conf << 'DAEMONEOF'
# WALL-E PulseAudio Daemon — Headless 16kHz Configuration
default-sample-rate = 16000
alternate-sample-rate = 44100
default-sample-channels = 1
default-sample-format = s16le
resample-method = speex-float-5
avoid-resampling = false
exit-idle-time = -1
default-fragments = 8
default-fragment-size-msec = 10
log-target = journal
log-level = warning
allow-module-loading = true
allow-exit = false
use-pid-file = true
system-instance = false
DAEMONEOF

# Probe WebRTC AEC availability
log "Probing WebRTC AEC..."
WEBRTC_AVAILABLE=false
pulseaudio --start --daemonize=yes --exit-idle-time=-1 2>/dev/null || true
sleep 2
if pactl load-module module-echo-cancel aec_method=webrtc 2>/dev/null; then
    WEBRTC_AVAILABLE=true
    log "WebRTC AEC available."
    pactl unload-module module-echo-cancel 2>/dev/null || true
else
    warn "WebRTC AEC not available — using speex fallback."
fi
pulseaudio --kill 2>/dev/null || true
sleep 1

# Build AEC args
if [[ "$WEBRTC_AVAILABLE" == "true" ]]; then
    AEC_ARGS='aec_method=webrtc aec_args="analog_gain_control=0 digital_gain_control=1 noise_suppression=1 high_pass_filter=1"'
else
    AEC_ARGS='aec_method=speex'
fi

# Write default.pa
log "Writing PulseAudio default.pa..."
cat > ~/.config/pulse/default.pa << PAEOF
#!/usr/bin/pulseaudio -nF
load-module module-native-protocol-unix
load-module module-always-sink
load-module module-alsa-source device=hw:${USB_CARD},0 rate=44100 channels=1 format=s16le source_name=usb_mic_raw source_properties="device.description='USB Microphone (Raw)'"
load-module module-null-sink sink_name=null_out sink_properties="device.description='WALL-E Null Sink'"
load-module module-echo-cancel source_master=usb_mic_raw sink_master=null_out source_name=walle_mic sink_name=walle_null source_properties="device.description='WALL-E Mic'" ${AEC_ARGS}
load-module module-alsa-sink device=default rate=16000 channels=1 sink_name=speaker_out
set-default-source walle_mic
set-default-sink speaker_out
.ifexists module-console-kit.so
load-module module-console-kit
.endif
PAEOF

# Create systemd user service
log "Creating PulseAudio systemd service..."
mkdir -p ~/.config/systemd/user/
cat > ~/.config/systemd/user/pulseaudio.service << 'SVCEOF'
[Unit]
Description=WALL-E Sound Server (PulseAudio)
After=dbus.socket
Wants=dbus.socket

[Service]
Type=notify
ExecStart=/usr/bin/pulseaudio --daemonize=no --log-target=journal
Restart=on-failure
RestartSec=3
SupplementaryGroups=audio

[Install]
WantedBy=default.target
SVCEOF

systemctl --user daemon-reload
systemctl --user enable pulseaudio.service 2>/dev/null || warn "Could not enable service."
sudo loginctl enable-linger "$USER" 2>/dev/null || warn "Linger not available."
systemctl --user start pulseaudio.service 2>/dev/null || true
sleep 2

pactl set-source-volume @DEFAULT_SOURCE@ 100% 2>/dev/null || warn "Could not set volume."
pactl set-source-mute @DEFAULT_SOURCE@ 0 2>/dev/null || true

# Update .env
WALLE_ENV="$HOME/walle/.env"
if [[ -f "$WALLE_ENV" ]]; then
    sed -i 's/WALLE_CAPTURE_RATE=.*/WALLE_CAPTURE_RATE=16000/' "$WALLE_ENV" 2>/dev/null || echo "WALLE_CAPTURE_RATE=16000" >> "$WALLE_ENV"
    sed -i 's/WALLE_SAMPLE_RATE=.*/WALLE_SAMPLE_RATE=16000/' "$WALLE_ENV" 2>/dev/null || echo "WALLE_SAMPLE_RATE=16000" >> "$WALLE_ENV"
    sed -i 's/WALLE_MIC_GAIN=.*/WALLE_MIC_GAIN=1.0/' "$WALLE_ENV" 2>/dev/null || echo "WALLE_MIC_GAIN=1.0" >> "$WALLE_ENV"
    sed -i 's/WALLE_MIC_DEVICE=.*/WALLE_MIC_DEVICE=/' "$WALLE_ENV" 2>/dev/null || echo "WALLE_MIC_DEVICE=" >> "$WALLE_ENV"
    log ".env updated."
fi

log ""
log "==================================="
log "✅ PulseAudio Audio Setup Complete!"
log "==================================="
log ""
log "PulseAudio features active:"
if [[ "$WEBRTC_AVAILABLE" == "true" ]]; then
log "  ✓ WebRTC AGC + Noise Suppression"
else
log "  ✓ Speex Echo Cancellation (fallback)"
fi
log "  ✓ Sample rate: 44100Hz → 16000Hz"
log "  ✓ Starts at boot automatically"
log ""
log "Next steps:"
log "  1. sudo systemctl restart walle-hw"
log "  2. sudo journalctl -u walle-hw -f"
log "  3. Say 'WALL-E' at normal speaking volume"
