"""
enroll_sahil.py — SIFRA AI Owner Voice Enrollment
===================================================
Records Sahil's voice and saves it as 'sahil_reference.wav'.
This reference file is used by the industry-grade ECAPA-TDNN
(SpeechBrain) model for anti-impersonation verification.

HOW TO USE:
  python enroll_sahil.py

TIPS FOR BEST RESULTS:
  - Speak naturally in your normal tone (no need to shout)
  - Use phrases you'd actually say to SIFRA (e.g., "Hey SIFRA, what's the weather?")
  - Run this in a quiet environment
  - Re-run if you want to update the voiceprint
"""

import sys
import time
import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wav

SAMPLE_RATE     = 16000
DURATION_SEC    = 10
OUTPUT_FILE     = "sahil_reference.wav"

print("=" * 55)
print("  SIFRA AI — Owner Voice Enrollment")
print("  Recording voiceprint for: Sahil")
print("=" * 55)
print()
print("This records a 10-second voice sample for anti-impersonation.")
print("Speak naturally — say a few sentences as you would to SIFRA.")
print()
print("Example phrases to say during recording:")
print('  "Hey SIFRA, what is on my schedule today?"')
print('  "SIFRA, remind me about the meeting at 5 PM."')
print('  "What is the latest news? Give me a brief summary."')
print()

input("Press ENTER when you are ready to record...")
print()

for i in range(3, 0, -1):
    print(f"  Starting in {i}...")
    time.sleep(1)

print()
print("  ● RECORDING — Speak now...")
print(f"  (Recording for {DURATION_SEC} seconds)")
print()

audio = sd.rec(
    int(DURATION_SEC * SAMPLE_RATE),
    samplerate=SAMPLE_RATE,
    channels=1,
    dtype="int16",
    blocking=True,
)

print("  ■ Recording complete.")
print()

# Check audio level (detect silence)
rms = np.sqrt(np.mean(audio.astype(np.float32) ** 2))
print(f"  Audio level (RMS): {rms:.1f}", end="")
if rms < 200:
    print("  ⚠ WARNING: Very low audio — check your microphone!")
elif rms < 800:
    print("  (acceptable — try speaking louder next time)")
else:
    print("  ✓ Good signal level")

print()

wav.write(OUTPUT_FILE, SAMPLE_RATE, audio)
print(f"  ✅ Voiceprint saved → '{OUTPUT_FILE}'")
print()
print("  SIFRA AI will now use this reference to verify your identity.")
print("  Anti-impersonation threshold: 0.45 (strict ECAPA-TDNN match)")
print()
print("  To re-enroll at any time, simply run this script again.")
print("=" * 55)
