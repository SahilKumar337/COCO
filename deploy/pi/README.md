# WALL-E AI — Raspberry Pi 5 Setup Guide
**Created by K.Astra and its members**

---

## What You Need

| Item | Recommendation |
|---|---|
| **Hardware** | Raspberry Pi 5 — 8GB RAM |
| **OS** | Raspberry Pi OS Bookworm **64-bit** (Lite or Desktop) |
| **Storage** | 32GB+ microSD (Class 10 / A1) or USB SSD (faster) |
| **Microphone** | USB microphone or USB audio adapter + 3.5mm mic |
| **Speaker** | USB speaker, 3.5mm speaker, or HDMI display with audio |
| **Camera** | USB webcam or Pi Camera Module 3 (optional, for face recognition) |
| **Internet** | Required (Gemini Live API) |

> [!IMPORTANT]
> Use **64-bit** Raspberry Pi OS. The 32-bit version cannot run PyTorch ARM64 wheels.

---

## Step 1: Flash Raspberry Pi OS

1. Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Choose **Raspberry Pi OS (64-bit) — Bookworm**
3. In Advanced settings: set hostname, username, password, Wi-Fi
4. Flash to your SD card / USB SSD
5. Boot your Pi 5

---

## Step 2: Copy the Project to Your Pi

**Option A — Git clone (if repo is on GitHub):**
```bash
git clone https://github.com/your-repo/COCO.git ~/walle
cd ~/walle
```

**Option B — Copy from Windows over network:**
```bash
# On Windows, from D:\KisanSetu\COCO:
scp -r . pi@<PI_IP>:~/walle
```

**Option C — USB drive:**
Copy the `COCO/` folder to a USB drive, plug into Pi, then:
```bash
cp -r /media/pi/USB_DRIVE/COCO ~/walle
cd ~/walle
```

---

## Step 3: Run the Installer

```bash
cd ~/walle
chmod +x deploy/pi/install.sh
./deploy/pi/install.sh
```

The installer does everything automatically:
- Installs system packages (`portaudio`, `dlib`, `cmake`, etc.)
- Creates `.venv` Python virtual environment
- Installs PyTorch ARM64
- Installs all WALL-E Python dependencies
- Creates `.env` from template
- Configures ALSA audio
- Installs and enables the systemd service

> [!NOTE]
> First install takes **15–30 minutes** on Pi 5 (dlib may need to compile from source).

---

## Step 4: Configure Your API Key

```bash
nano ~/walle/.env
```

Set:
```env
GEMINI_API_KEY=your_api_key_here
```

Get a free key at [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)

---

## Step 5: Configure Audio

### Find your microphone

```bash
# List all microphones (capture devices)
arecord -l

# List all speakers (playback devices)
aplay -l

# Or use sounddevice to list with indices
source ~/walle/.venv/bin/activate
python3 -c "import sounddevice as sd; print(sd.query_devices())"
```

Example output:
```
  0 bcm2835 HDMI: - (hw:0,0), ALSA (0 in, 8 out)
  1 USB Audio Device: - (hw:1,0), ALSA (1 in, 0 out)   ← your USB mic
  2 USB Speaker: - (hw:2,0), ALSA (0 in, 2 out)         ← your USB speaker
```

### Set in `.env`

```env
# Use the device name substring (partial match works)
WALLE_MIC_DEVICE=USB Audio
WALLE_SPEAKER_DEVICE=USB Speaker

# Or use the index number directly
# WALLE_MIC_DEVICE=1
# WALLE_SPEAKER_DEVICE=2
```

---

## Step 6: Start WALL-E

### As a system service (recommended — auto-starts on boot):
```bash
sudo systemctl start walle
sudo journalctl -u walle -f   # watch live logs
```

### Manually (for testing):
```bash
cd ~/walle
source .venv/bin/activate
python server.py
```

### Access the web UI:
Open a browser on any device on the same network:
```
http://<PI_IP_ADDRESS>:8000
```

Find your Pi's IP:
```bash
hostname -I
```

---

## Environment Variables Reference

All Pi-specific settings in your `.env`:

```env
# ─── Required ───────────────────────────────────────────────
GEMINI_API_KEY=your_key_here

# ─── Pi Detection ───────────────────────────────────────────
WALLE_PI_MODE=1               # Force Pi mode (auto-detected normally)

# ─── Audio ──────────────────────────────────────────────────
WALLE_MIC_DEVICE=USB Audio    # Mic device name or index
WALLE_SPEAKER_DEVICE=         # Speaker device (leave blank = ALSA default)
WALLE_AUDIO_BLOCKSIZE=4096    # Larger = fewer ALSA underruns on Pi

# ─── AI Performance ─────────────────────────────────────────
WALLE_WHISPER_MODEL=tiny      # tiny|base|small (tiny recommended for Pi)
WALLE_WHISPER_COMPUTE=int8    # int8 = fastest on ARM, less RAM
WALLE_TORCH_THREADS=2         # PyTorch CPU threads (Pi 5 has 4 cores)

# ─── Face Detection ─────────────────────────────────────────
WALLE_FACE_INTERVAL=3.0       # Seconds between face detection (higher = less CPU)
WALLE_CAM_W=320               # Camera width (lower = faster on Pi)
WALLE_CAM_H=240               # Camera height

# ─── Server ─────────────────────────────────────────────────
PORT=8000
ENVIRONMENT=production
WALLE_USER_NAME=K.Astra
WALLE_VOICE=Aoede
WALLE_OWNER_NAME=Sahil
WALLE_OWNER_REF_FILE=sahil_reference.wav
```

---

## Useful Commands

```bash
# Start / stop / restart the service
sudo systemctl start walle
sudo systemctl stop walle
sudo systemctl restart walle

# View live logs
sudo journalctl -u walle -f

# Check service status
sudo systemctl status walle

# Check CPU and memory usage
htop

# Test microphone
arecord -d 3 test.wav && aplay test.wav

# List audio devices
python3 -c "import sounddevice as sd; print(sd.query_devices())"

# Update WALL-E
cd ~/walle
git pull
source .venv/bin/activate
pip install -r requirements-pi.txt
sudo systemctl restart walle
```

---

## Troubleshooting

### "No audio devices found" / ALSA errors
```bash
# Check if your USB mic is detected
lsusb
arecord -l

# Try fixing ALSA config
sudo alsa force-reload

# Add your user to the audio group
sudo usermod -aG audio $USER
# Log out and back in
```

### "Failed to load wake word model"
```bash
# Manually install faster-whisper
source ~/walle/.venv/bin/activate
pip install faster-whisper --upgrade
```

### "ImportError: libgomp.so.1"
```bash
sudo apt-get install -y libgomp1
```

### Out of memory / crashes
```bash
# Check available memory
free -h

# Reduce torch threads
echo "WALLE_TORCH_THREADS=1" >> ~/walle/.env
# Switch to smaller whisper model
echo "WALLE_WHISPER_MODEL=tiny" >> ~/walle/.env
sudo systemctl restart walle
```

### Service won't start
```bash
# View detailed error
sudo journalctl -u walle -n 50 --no-pager

# Check your .env
cat ~/walle/.env | grep GEMINI_API_KEY
```

### Can't access http://<IP>:8000 from another device
```bash
# Check if the port is open
sudo ufw allow 8000  # if ufw is active
# Verify it's listening
ss -tlnp | grep 8000
```

---

## Performance Notes (Pi 5, 8GB RAM)

| Component | CPU Usage | Memory |
|---|---|---|
| FastAPI + uvicorn | ~2% | ~80MB |
| Gemini Live session | ~5% | ~150MB |
| faster-whisper (tiny, int8) | ~30% (during wakeword) | ~200MB |
| SpeechBrain ECAPA-TDNN | ~40% (during ID check) | ~600MB |
| face_recognition (320×240) | ~15% | ~100MB |
| **Total** | **~30% idle** | **~1.2GB** |

> [!TIP]
> With 8GB RAM you have plenty of headroom. If you don't need face recognition, set `WALLE_FACE_INTERVAL=999` to effectively disable it.
