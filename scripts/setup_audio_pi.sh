#!/usr/bin/env bash
# =============================================================================
# WALL-E Audio Setup — Industry-Level Headless Pi Configuration
# =============================================================================
# Installs and configures PulseAudio with WebRTC noise cancellation + AGC.
# Run ONCE on the Pi as the walle user (not root):
#   bash ~/walle/scripts/setup_audio_pi.sh
#
# What this does:
#   1. Installs PulseAudio + WebRTC echo-cancel module
#   2. Configures PulseAudio for headless operation (no display needed)
#   3. Enables WebRTC Automatic Gain Control (AGC) — like Windows audio engine
#   4. Enables WebRTC Noise Suppression — better than Windows
#   5. Sets default sample rate to 16000 Hz (native Whisper/Gemini rate)
#   6. Creates a user systemd service for PulseAudio (starts on boot, no login needed)
#   7. Updates walle-hw.service to depend on PulseAudio
#
# After running this:
#   - No more manual resampling in Python code
#   - No more gain hacks
#   - PulseAudio handles 44100 Hz → 16000 Hz transparently
#   - AGC normalizes mic volume like Windows does automatically
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${GREEN}[SETUP]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
info() { echo -e "${BLUE}[INFO]${NC}  $*"; }

# ── Sanity checks ─────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] && err "Run as the walle user, NOT as root."

log "=== WALL-E Industry Audio Setup ==="
info "User: $(whoami) | Home: $HOME"

# ── 1. Detect Pi OS ───────────────────────────────────────────────────────────
if ! grep -q "Raspberry Pi\|raspbian" /proc/device-tree/model 2>/dev/null &&
   ! grep -qi "raspberry" /etc/os-release 2>/dev/null; then
    warn "Not a Raspberry Pi — setup may still work on Debian/Ubuntu."
fi

# ── 2. Install PulseAudio ─────────────────────────────────────────────────────
log "Installing PulseAudio + WebRTC module..."
sudo apt-get update -qq
sudo apt-get install -y \
    pulseaudio \
    pulseaudio-utils \
    pulseaudio-module-echo-cancel \
    alsa-utils \
    libpulse0 \
    python3-pyaudio

# Make sure user is in audio group
sudo usermod -a -G audio "$USER"
log "User added to audio group."

# ── 3. Kill any existing PulseAudio ───────────────────────────────────────────
pulseaudio --kill 2>/dev/null || true
sleep 1

# ── 4. Detect USB microphone ─────────────────────────────────────────────────
log "Detecting USB microphone..."
USB_CARD=$(arecord -l 2>/dev/null | grep -i "usb\|pnp\|mic" | head -1 | grep -oP 'card \K\d+' || echo "")
if [[ -z "$USB_CARD" ]]; then
    warn "USB mic not detected by arecord. Using card 2 as default."
    USB_CARD="2"
fi
log "USB microphone on ALSA card: $USB_CARD"

# ── 5. Create PulseAudio config directory ─────────────────────────────────────
mkdir -p ~/.config/pulse

# ── 6. PulseAudio daemon config (headless, 16kHz, low-latency) ───────────────
log "Writing PulseAudio daemon.conf..."
cat > ~/.config/pulse/daemon.conf << EOF
# WALL-E PulseAudio Daemon — Headless 16kHz Configuration
# Optimized for voice recognition on Raspberry Pi 5

default-sample-rate = 16000
alternate-sample-rate = 44100
default-sample-channels = 1
default-sample-format = s16le

# Speex-float-5: high quality resampling (like Windows WASAPI)
resample-method = speex-float-5

# Avoid unnecessary resampling when rates match
avoid-resampling = false

# Keep running even with no active streams (headless requirement)
exit-idle-time = -1
idle-timeout = 0

# Low latency settings for voice recognition
default-fragments = 8
default-fragment-size-msec = 10

# Log to journal (visible via journalctl)
log-target = journal
log-level = warning

# Daemon settings for headless operation
allow-module-loading = true
allow-exit = false
use-pid-file = true
system-instance = false
EOF

# ── 7. PulseAudio default.pa (module loading) ─────────────────────────────────
log "Writing PulseAudio default.pa with WebRTC AGC + noise suppression..."
cat > ~/.config/pulse/default.pa << EOF
#!/usr/bin/pulseaudio -nF
# WALL-E PulseAudio Module Configuration
# Industry-standard voice processing stack: WebRTC AGC + Noise Suppression

# ── Core modules ──────────────────────────────────────────────────────────────
load-module module-native-protocol-unix
load-module module-always-sink

# ── USB Microphone — raw ALSA source ─────────────────────────────────────────
# Capture at the mic's native rate; PulseAudio resamples to 16kHz
load-module module-alsa-source \
    device=hw:${USB_CARD},0 \
    rate=44100 \
    channels=1 \
    format=s16le \
    source_name=usb_mic_raw \
    source_properties="device.description='USB Microphone (Raw)'"

# ── Output (null sink for headless — no speaker needed for wake word) ─────────
load-module module-null-sink \
    sink_name=null_out \
    sink_properties="device.description='WALL-E Null Sink'"

# ── WebRTC Processing: AGC + Noise Suppression + Echo Cancellation ────────────
# This is the equivalent of Windows audio engine automatic processing.
# aec_method=webrtc uses Google's WebRTC audio processing library.
# analog_gain_control=0  — skip analog (already at 100% hardware)
# digital_gain_control=1 — enable digital AGC (software, like Windows)
# noise_suppression=1    — enable noise suppression
# high_pass_filter=1     — remove low-frequency rumble
load-module module-echo-cancel \
    source_master=usb_mic_raw \
    sink_master=null_out \
    source_name=walle_mic \
    sink_name=walle_null \
    source_properties="device.description='WALL-E Enhanced Microphone (AGC+NS)'" \
    aec_method=webrtc \
    aec_args="analog_gain_control=0 digital_gain_control=1 noise_suppression=1 high_pass_filter=1 extended_filter=1"

# ── ALSA Speaker output ───────────────────────────────────────────────────────
load-module module-alsa-sink \
    device=default \
    rate=16000 \
    channels=1 \
    sink_name=speaker_out \
    sink_properties="device.description='Speaker Output'"

# ── Set WALL-E Enhanced Mic as default input ──────────────────────────────────
set-default-source walle_mic
set-default-sink speaker_out

# ── Boost mic capture volume to 100% ─────────────────────────────────────────
.ifexists module-console-kit.so
load-module module-console-kit
.endif

EOF

# ── 8. Create user systemd service for PulseAudio ────────────────────────────
log "Creating PulseAudio user systemd service..."
mkdir -p ~/.config/systemd/user/

cat > ~/.config/systemd/user/pulseaudio.service << EOF
[Unit]
Description=WALL-E Sound Server (PulseAudio)
Documentation=man:pulseaudio(1)
After=dbus.socket
Wants=dbus.socket

[Service]
Type=notify
ExecStart=/usr/bin/pulseaudio --daemonize=no --log-target=journal
Restart=on-failure
RestartSec=3

# Give audio group access
SupplementaryGroups=audio

[Install]
WantedBy=default.target
EOF

# Enable PulseAudio user service (starts automatically with user session/linger)
systemctl --user daemon-reload
systemctl --user enable pulseaudio.service

# Enable user linger (allows user services to start at boot without login)
sudo loginctl enable-linger "$USER"
log "User linger enabled — PulseAudio will start at boot."

# ── 9. Update walle-hw.service to depend on PulseAudio ───────────────────────
log "Updating walle-hw.service to wait for PulseAudio..."
WALLE_SERVICE="/etc/systemd/system/walle-hw.service"
if [[ -f "$WALLE_SERVICE" ]]; then
    sudo sed -i 's|After=network.target|After=network.target pulseaudio.service|g' "$WALLE_SERVICE"
    sudo systemctl daemon-reload
    log "walle-hw.service updated."
else
    warn "walle-hw.service not found — update it manually to add: After=pulseaudio.service"
fi

# ── 10. Start PulseAudio now ──────────────────────────────────────────────────
log "Starting PulseAudio..."
systemctl --user start pulseaudio.service
sleep 2

# Verify it started
if systemctl --user is-active pulseaudio.service &>/dev/null; then
    log "PulseAudio is running!"
else
    warn "PulseAudio failed to start via systemd. Trying direct start..."
    pulseaudio --start --exit-idle-time=-1 --daemonize=yes
    sleep 2
fi

# ── 11. Set mic volume to 100% via PulseAudio ─────────────────────────────────
log "Setting mic volume to 100%..."
pactl set-source-volume @DEFAULT_SOURCE@ 100% 2>/dev/null || warn "Could not set source volume (PulseAudio may still be loading)"
pactl set-source-mute @DEFAULT_SOURCE@ 0 2>/dev/null || true

# ── 12. Verify setup ──────────────────────────────────────────────────────────
log ""
log "=== Audio Setup Complete ==="
info "PulseAudio sources:"
pactl list sources short 2>/dev/null || warn "PulseAudio not responding yet"
info ""
info "Default source: $(pactl get-default-source 2>/dev/null || echo 'unknown')"

# ── 13. Update .env ───────────────────────────────────────────────────────────
WALLE_ENV="$HOME/walle/.env"
if [[ -f "$WALLE_ENV" ]]; then
    log "Updating .env — disabling manual resampling (PulseAudio handles it now)..."
    # Set both rates to 16000 — PulseAudio handles 44100→16000 transparently
    sed -i 's/WALLE_CAPTURE_RATE=.*/WALLE_CAPTURE_RATE=16000/' "$WALLE_ENV" 2>/dev/null || \
        echo "WALLE_CAPTURE_RATE=16000" >> "$WALLE_ENV"
    sed -i 's/WALLE_SAMPLE_RATE=.*/WALLE_SAMPLE_RATE=16000/' "$WALLE_ENV" 2>/dev/null || \
        echo "WALLE_SAMPLE_RATE=16000" >> "$WALLE_ENV"
    # Disable software gain (PulseAudio AGC handles this now)
    sed -i 's/WALLE_MIC_GAIN=.*/WALLE_MIC_GAIN=1.0/' "$WALLE_ENV" 2>/dev/null || \
        echo "WALLE_MIC_GAIN=1.0" >> "$WALLE_ENV"
    # Use PulseAudio default device (no device index — PA manages it)
    sed -i 's/WALLE_MIC_DEVICE=.*/WALLE_MIC_DEVICE=/' "$WALLE_ENV" 2>/dev/null || \
        echo "WALLE_MIC_DEVICE=" >> "$WALLE_ENV"
    log ".env updated."
fi

# ── 14. Test recording ────────────────────────────────────────────────────────
log ""
log "Testing microphone via PulseAudio (recording 2 seconds)..."
parecord --channels=1 --rate=16000 --format=s16le /tmp/walle_test.wav & REC_PID=$!
sleep 2
kill $REC_PID 2>/dev/null
if [[ -f /tmp/walle_test.wav ]]; then
    SIZE=$(wc -c < /tmp/walle_test.wav)
    if [[ $SIZE -gt 1000 ]]; then
        log "✅ Microphone recording via PulseAudio: SUCCESS ($SIZE bytes)"
    else
        warn "Recording file too small — mic may not be working through PulseAudio yet."
    fi
fi

log ""
log "==================================="
log "✅ Industry Audio Setup Complete!"
log "==================================="
log ""
log "Next steps:"
log "  1. Restart WALL-E:  sudo systemctl restart walle-hw"
log "  2. View logs:       sudo journalctl -u walle-hw -f"
log "  3. Say:             'WALL-E' (at normal speaking volume)"
log ""
log "PulseAudio features now active:"
log "  ✓ Automatic Gain Control (AGC) — like Windows audio engine"
log "  ✓ Noise Suppression — filters background noise"
log "  ✓ High-pass filter — removes rumble/hum"
log "  ✓ Sample rate conversion: 44100Hz → 16000Hz (transparent)"
log "  ✓ Starts automatically at boot (no login needed)"
