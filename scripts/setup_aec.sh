#!/bin/bash
# setup_aec.sh - Configures WebRTC Acoustic Echo Cancellation on Raspberry Pi OS

echo "====================================================="
echo "WALL-E: Full-Duplex WebRTC Echo Cancellation Setup"
echo "====================================================="
echo ""

# Check if using PipeWire or PulseAudio
if systemctl --user is-active --quiet pipewire; then
    echo "Detected PipeWire (Raspberry Pi OS Bookworm or newer)."
    echo "Setting up libpipewire-module-echo-cancel..."
    
    mkdir -p ~/.config/pipewire/pipewire.conf.d/
    cat << 'EOF' > ~/.config/pipewire/pipewire.conf.d/echo-cancel.conf
context.modules = [
    { name = libpipewire-module-echo-cancel
      args = {
          # library.name  = aec/libspa-aec-webrtc
          # node.latency = 1024/48000
          source.props = {
             node.name = "Echo Cancel Source"
          }
          sink.props = {
             node.name = "Echo Cancel Sink"
          }
      }
    }
]
EOF

    echo "Restarting PipeWire..."
    systemctl --user restart pipewire pipewire-pulse
    
    # Wait for restart
    sleep 2
    
    # Set default to the new echo-canceled virtual nodes
    pw-metadata -n settings 0 default.audio.source "Echo Cancel Source"
    pw-metadata -n settings 0 default.audio.sink "Echo Cancel Sink"
    
    echo "PipeWire Echo Cancellation successfully enabled!"

elif systemctl --user is-active --quiet pulseaudio; then
    echo "Detected PulseAudio (Raspberry Pi OS Bullseye or older)."
    echo "Setting up module-echo-cancel..."
    
    # Check if already in config
    if grep -q "module-echo-cancel" /etc/pulse/default.pa; then
        echo "module-echo-cancel is already configured in /etc/pulse/default.pa"
    else
        echo "Appending to /etc/pulse/default.pa (requires sudo)..."
        sudo bash -c 'cat << EOF >> /etc/pulse/default.pa

### Enable WebRTC Acoustic Echo Cancellation for WALL-E
load-module module-echo-cancel aec_method=webrtc source_name=echocancel_mic sink_name=echocancel_speaker
set-default-source echocancel_mic
set-default-sink echocancel_speaker
EOF'
    fi
    
    echo "Restarting PulseAudio..."
    pulseaudio -k
    pulseaudio --start
    
    echo "PulseAudio Echo Cancellation successfully enabled!"
else
    echo "ERROR: Neither PipeWire nor PulseAudio appear to be active."
    echo "Make sure you are running a desktop version of Raspberry Pi OS, or manually start the audio server."
    exit 1
fi

echo ""
echo "Done! You can now interrupt WALL-E while he is speaking without him hearing himself!"
echo "Please restart WALL-E to apply changes: sudo systemctl restart walle-hw"
