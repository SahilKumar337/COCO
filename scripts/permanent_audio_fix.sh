#!/usr/bin/env bash
# =============================================================================
# scripts/permanent_audio_fix.sh — Resolve Duplicate Voice & Audio Clashes
# =============================================================================
# Run on the Pi as the walle user:
#   bash scripts/permanent_audio_fix.sh
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${GREEN}[FIX]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
info() { echo -e "${BLUE}[INFO]${NC} $*"; }

# ── Safety Checks ────────────────────────────────────────────────────────────
if [[ $EUID -eq 0 ]]; then
    err "Do NOT run this script as root/sudo directly. Run as your regular user (e.g. niketkumar)."
fi

# Detect project path
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME=$(whoami)
USER_ID=$(id -u)

log "Starting Permanent Audio & Service Fix..."
info "Project Directory: $PROJECT_DIR"
info "User:              $USER_NAME (UID: $USER_ID)"

# ── 1. Stop and Clean System-Wide Services ───────────────────────────────────
log "Cleaning up any old system-wide services (that run in root context)..."

# Stop and disable walle-hw (system-wide)
if systemctl is-active walle-hw &>/dev/null; then
    info "Stopping system-wide walle-hw.service..."
    sudo systemctl stop walle-hw || true
fi
if systemctl is-enabled walle-hw &>/dev/null; then
    info "Disabling system-wide walle-hw.service..."
    sudo systemctl disable walle-hw || true
fi
sudo rm -f /etc/systemd/system/walle-hw.service

# Stop and disable walle (system-wide)
if systemctl is-active walle &>/dev/null; then
    info "Stopping system-wide walle.service..."
    sudo systemctl stop walle || true
fi
if systemctl is-enabled walle &>/dev/null; then
    info "Disabling system-wide walle.service..."
    sudo systemctl disable walle || true
fi
sudo rm -f /etc/systemd/system/walle.service

# Reload system daemon to register file deletions
sudo systemctl daemon-reload

# ── 2. Kill Zombie Python Processes ──────────────────────────────────────────
log "Killing any orphaned python processes running main.py or server.py..."
pkill -f "python.*(main.py|server.py)" || true
sleep 1

# ── 3. Configure the User-Level Service ──────────────────────────────────────
log "Creating the single, clean user-level systemd service..."

USER_SERVICE_DIR="$HOME/.config/systemd/user"
mkdir -p "$USER_SERVICE_DIR"
USER_SERVICE_PATH="$USER_SERVICE_DIR/walle.service"

cat > "$USER_SERVICE_PATH" << EOF
[Unit]
Description=WALL-E AI Voice Assistant (User Session)
Documentation=https://github.com/SahilKumar337/COCO
After=default.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PROJECT_DIR}/.venv/bin/python main.py
Restart=on-failure
RestartSec=5s

# Pi 5 logs real-time formatting
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1

# Audio server context permissions
Environment=XDG_RUNTIME_DIR=/run/user/${USER_ID}
Environment=PULSE_RUNTIME_PATH=/run/user/${USER_ID}/pulse

# Resource constraints
MemoryMax=6G
CPUShares=512

[Install]
WantedBy=default.target
EOF

log "User-level service file written to $USER_SERVICE_PATH"

# ── 4. Enable Linger for Boot Startup ────────────────────────────────────────
log "Enabling linger for user '$USER_NAME' so user services start at boot..."
sudo loginctl enable-linger "$USER_NAME" || warn "Could not enable linger automatically. You might need to run: sudo loginctl enable-linger $USER_NAME"

# ── 5. Clean up Environment Configuration ────────────────────────────────────
ENV_FILE="${PROJECT_DIR}/.env"
if [[ -f "$ENV_FILE" ]]; then
    log "Configuring environment settings in .env..."
    cp "$ENV_FILE" "${ENV_FILE}.bak"
    
    # 1. Clear hardcoded microphone device index to fall back to virtual PipeWire default source
    if grep -q "^WALLE_MIC_DEVICE=" "$ENV_FILE"; then
        sed -i 's/^WALLE_MIC_DEVICE=.*/WALLE_MIC_DEVICE=/' "$ENV_FILE"
        info "Cleared WALLE_MIC_DEVICE (now using virtual PipeWire default)"
    else
        echo "WALLE_MIC_DEVICE=" >> "$ENV_FILE"
        info "Added WALLE_MIC_DEVICE= (virtual PipeWire default)"
    fi

    # 2. Force WALLE_MIC_AGC=1 for Automatic Gain Control
    if grep -q "^WALLE_MIC_AGC=" "$ENV_FILE"; then
        sed -i 's/^WALLE_MIC_AGC=.*/WALLE_MIC_AGC=1/' "$ENV_FILE"
        info "Set WALLE_MIC_AGC=1 (Automatic Gain Control enabled)"
    else
        echo "WALLE_MIC_AGC=1" >> "$ENV_FILE"
        info "Added WALLE_MIC_AGC=1 (Automatic Gain Control enabled)"
    fi
else
    warn ".env file not found in $PROJECT_DIR. Please copy .env.example to .env."
fi

# ── 6. Start the User Service ────────────────────────────────────────────────
log "Activating user-level service..."
systemctl --user daemon-reload
systemctl --user enable walle.service
systemctl --user restart walle.service

log ""
log "==============================================================="
log "✅ Permanent Fix Applied Successfully!"
log "==============================================================="
log "The system-wide duplicate services have been deleted."
log "Exactly ONE instance of WALL-E is now running in your user session."
log ""
info "Status command:  systemctl --user status walle"
info "Logs command:    journalctl --user -u walle -f"
log "==============================================================="
log ""
EOF
