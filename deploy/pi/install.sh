#!/bin/bash
# =============================================================================
#  deploy/pi/install.sh — WALL-E AI Full Installer for Raspberry Pi 5
#  Created by K.Astra and its members.
#
#  Run this ONCE on a fresh Raspberry Pi OS Bookworm (64-bit) install:
#    chmod +x deploy/pi/install.sh
#    ./deploy/pi/install.sh
#
#  What this script does:
#    1. Updates the system
#    2. Installs all system (apt) dependencies
#    3. Creates a Python virtual environment
#    4. Installs Python packages (Pi-optimised)
#    5. Creates the .env file from .env.example
#    6. Installs the systemd service
#    7. Sets up audio (ALSA / PulseAudio)
# =============================================================================

set -e  # Exit immediately on any error

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*"; exit 1; }
section() { echo -e "\n${BOLD}${CYAN}══ $* ══${RESET}"; }

# ── Detect script location ────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

info "Project directory: $PROJECT_DIR"
info "Script directory:  $SCRIPT_DIR"

# ── Verify we are on a Pi ─────────────────────────────────────────────────────
if ! grep -qi "raspberry pi" /proc/device-tree/model 2>/dev/null; then
    warn "This script is designed for Raspberry Pi. Continuing anyway..."
fi

# =============================================================================
section "1/7 — System update"
# =============================================================================
info "Updating package lists..."
sudo apt-get update -qq

# =============================================================================
section "2/7 — System packages"
# =============================================================================
info "Installing system dependencies..."
sudo apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv python3-dev \
    build-essential cmake git pkg-config \
    \
    portaudio19-dev \
    alsa-utils pulseaudio pulseaudio-utils \
    espeak-ng \
    \
    libopenblas-dev \
    libhdf5-dev \
    libjpeg-dev libpng-dev libtiff-dev \
    libavcodec-dev libavformat-dev libswscale-dev \
    libv4l-dev v4l-utils \
    libxvidcore-dev libx264-dev \
    libfontconfig1-dev libcairo2-dev \
    libgdk-pixbuf-2.0-dev libpango1.0-dev \
    libgtk2.0-dev libgtk-3-dev \
    \
    libboost-python-dev libboost-thread-dev \
    libssl-dev libffi-dev \
    libblas-dev liblapack-dev gfortran \
    \
    libopencv-dev \
    libdlib-dev \
    \
    sqlite3 \
    curl wget unzip

success "System packages installed."

# =============================================================================
section "3/7 — Python virtual environment"
# =============================================================================
VENV_DIR="$PROJECT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    info "Creating virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

# Activate venv for the rest of the script
source "$VENV_DIR/bin/activate"
info "Virtual environment active."

# Upgrade pip, setuptools, wheel
pip install --upgrade pip setuptools wheel
success "pip upgraded."

# =============================================================================
section "4/7 — Python packages"
# =============================================================================

# PyTorch ARM64 (Pi 5 uses aarch64 — use the official ARM wheel)
info "Installing PyTorch for ARM64 (this may take a few minutes)..."
pip install torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cpu \
    || warn "PyTorch install from PyPI may be slow on Pi — trying anyway."

# dlib and face_recognition are skipped to prevent thermal/power crashes during installation
# (Face recognition is disabled in main.py to save CPU anyway)

# All other WALL-E dependencies using the Pi-specific requirements file
info "Installing WALL-E AI Python packages..."
pip install -r "$PROJECT_DIR/requirements-pi.txt"

success "All Python packages installed."

# =============================================================================
section "5/7 — Environment file"
# =============================================================================
ENV_FILE="$PROJECT_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
    cp "$PROJECT_DIR/.env.example" "$ENV_FILE"
    warn ".env file created from .env.example — EDIT IT NOW to add your GEMINI_API_KEY!"
    echo ""
    echo -e "  ${BOLD}nano $ENV_FILE${RESET}"
    echo ""
else
    info ".env file already exists — skipping."
fi

# Add Pi-specific env defaults if not already present
add_env_if_missing() {
    local key="$1"
    local val="$2"
    if ! grep -q "^${key}=" "$ENV_FILE"; then
        echo "${key}=${val}" >> "$ENV_FILE"
        info "Added to .env: ${key}=${val}"
    fi
}

add_env_if_missing "WALLE_PI_MODE"           "1"
add_env_if_missing "WALLE_AUDIO_BLOCKSIZE"   "4096"
add_env_if_missing "WALLE_WHISPER_COMPUTE"   "int8"
add_env_if_missing "WALLE_TORCH_THREADS"     "2"
add_env_if_missing "WALLE_FACE_INTERVAL"     "3.0"
add_env_if_missing "WALLE_CAM_W"             "320"
add_env_if_missing "WALLE_CAM_H"             "240"
add_env_if_missing "ENVIRONMENT"             "production"

success ".env configured."

# =============================================================================
section "6/7 — Audio setup"
# =============================================================================
info "Configuring ALSA audio..."

# Create ALSA config to reduce underruns on Pi
ALSA_CONF="$HOME/.asoundrc"
if [ ! -f "$ALSA_CONF" ]; then
cat > "$ALSA_CONF" << 'EOF'
# WALL-E AI — ALSA configuration for Raspberry Pi 5
# Increases buffer size to prevent underruns during AI model inference

defaults.pcm.rate_converter "speexrate_best"

pcm.!default {
    type asym
    playback.pcm "plughw:0,0"
    capture.pcm  "plughw:1,0"
}

ctl.!default {
    type hw
    card 0
}
EOF
    info "ALSA config written to $ALSA_CONF"
    warn "You may need to adjust card numbers — run: aplay -l  and  arecord -l"
fi

# List audio devices for the user
info "Available playback devices:"
aplay -l 2>/dev/null || true
echo ""
info "Available capture (microphone) devices:"
arecord -l 2>/dev/null || true
echo ""
warn "Set WALLE_MIC_DEVICE in your .env to select your USB microphone."
warn "Example: WALLE_MIC_DEVICE=USB  (matches any device containing 'USB' in its name)"

success "Audio configured."

# =============================================================================
section "7/7 — systemd service (User level)"
# =============================================================================
SERVICE_SRC="$SCRIPT_DIR/walle.service"
USER_SYSTEMD_DIR="$HOME/.config/systemd/user"
SERVICE_DST="$USER_SYSTEMD_DIR/walle.service"

if [ -f "$SERVICE_SRC" ]; then
    mkdir -p "$USER_SYSTEMD_DIR"
    # Substitute paths into the service template
    sed \
        -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
        -e "s|__VENV_DIR__|$VENV_DIR|g" \
        "$SERVICE_SRC" > "$SERVICE_DST"

    systemctl --user daemon-reload
    systemctl --user enable walle.service
    success "systemd service installed and enabled as USER service (starts on boot/login)."
    
    # Enable lingering so user-level systemd services run without active SSH sessions
    sudo loginctl enable-linger "$(whoami)" || true
    
    info "  Start now:    systemctl --user start walle"
    info "  View logs:    journalctl --user -u walle -f"
    info "  Stop:         systemctl --user stop walle"
else
    warn "walle.service template not found — skipping systemd setup."
fi

# =============================================================================
echo ""
echo -e "${GREEN}${BOLD}============================================${RESET}"
echo -e "${GREEN}${BOLD}  WALL-E AI Installation Complete!${RESET}"
echo -e "${GREEN}${BOLD}============================================${RESET}"
echo ""
echo -e "  ${BOLD}Next steps:${RESET}"
echo -e "  1. Edit your API key:   ${CYAN}nano $ENV_FILE${RESET}"
echo -e "  2. Set mic device:      ${CYAN}python3 -c \"import sounddevice as sd; print(sd.query_devices())\"${RESET}"
echo -e "     Then add to .env:    ${CYAN}WALLE_MIC_DEVICE=<index or name substring>${RESET}"
echo -e "  3. Start WALL-E:        ${CYAN}systemctl --user start walle${RESET}"
echo -e "     Or run directly:     ${CYAN}cd $PROJECT_DIR && .venv/bin/python main.py${RESET}"
echo ""
echo -e "  ${BOLD}Watch logs at:${RESET}      ${CYAN}journalctl --user -u walle -f${RESET}"
echo ""
echo -e "  ${BOLD}Access the web UI at:${RESET}  ${CYAN}http://$(hostname -I | awk '{print $1}'):8000${RESET}"
echo ""
