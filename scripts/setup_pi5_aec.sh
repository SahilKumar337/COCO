#!/bin/bash
# setup_pi5_aec.sh - Configures Explicit PipeWire WebRTC Echo Cancellation for Pi 5

echo "====================================================="
echo "WALL-E: Pi 5 Full-Duplex WebRTC Echo Cancellation Setup"
echo "====================================================="
echo ""

echo "1. Installing required WebRTC library..."
sudo apt-get update
sudo apt-get install -y libspa-0.2-webrtc

echo "2. Writing custom PipeWire configuration..."
mkdir -p ~/.config/pipewire/pipewire.conf.d/
cat << 'EOF' > ~/.config/pipewire/pipewire.conf.d/echo-cancel.conf
context.modules = [
    { name = libpipewire-module-echo-cancel
      args = {
          # Explicitly force Google's WebRTC algorithm (requires libspa-0.2-webrtc)
          library.name  = aec/libspa-aec-webrtc
          # Optional tuning parameters:
          # webrtc.extended_filter = true
          source.props = {
             node.name = "WALL-E-AEC-Mic"
             node.description = "WALL-E AEC Microphone"
          }
          sink.props = {
             node.name = "WALL-E-AEC-Speaker"
             node.description = "WALL-E AEC Speaker"
          }
      }
    }
]
EOF

echo "3. Restarting PipeWire audio server..."
systemctl --user restart pipewire pipewire-pulse
sleep 3

echo "4. Setting the AEC nodes as the system default..."
pw-metadata -n settings 0 default.audio.source "WALL-E-AEC-Mic"
pw-metadata -n settings 0 default.audio.sink "WALL-E-AEC-Speaker"

echo ""
echo "Done! PipeWire is now running hardware-grade Echo Cancellation."
echo "Please completely restart the Pi to ensure all audio nodes link properly:"
echo "    sudo reboot"
