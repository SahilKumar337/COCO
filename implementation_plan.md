# Implement Zero-Cost Production Stack (Pro-Audio Pattern)

You are completely right. Since the Gemini Live API natively uses WebSockets, adding a WebRTC bridge (like LiveKit) introduces an unnecessary middleman "hop" that fundamentally increases latency. 

To achieve production-grade, glitch-free audio while maintaining the lowest possible latency, we will stay on WebSockets and implement your proposed **Pro-Audio Pattern** entirely on the client side.

## Proposed Changes

### Component A: The AudioWorklet (No-Lag Threading)
**Status:** Already Implemented
We will maintain the `audio-processor.js` implementation. By running audio capture in the AudioWorklet thread (a dedicated, high-priority background thread), we guarantee that UI renders or main-thread blocking will not cause the microphone capture to stutter or "crackle". 

### Component B: Adaptive Jitter Buffer (Smooth Playback)
**Status:** To Be Implemented
**Action:** 
- **[MODIFY] `app.js`**: We will replace the current simplistic static-offset scheduling (`Audio.scheduledEndTime = now + JITTER`) with a robust **Adaptive Jitter Buffer / Ring Buffer**.
- Instead of playing chunks immediately, we will queue the incoming raw PCM chunks from Gemini into a buffer and maintain a dynamic lookahead (50–100ms).
- We will dynamically adjust the playback speed or insert micro-silences if network speed fluctuates, ensuring silky smooth, human-like speech playback even on unstable Wi-Fi.

### Component C: Binary-Only Transport
**Status:** Already Implemented
We will maintain the strict binary payload protocol. Both `app.js` and `sifra_session.py` will exclusively transmit and receive raw `ArrayBuffer` / `bytes` (16kHz PCM for mic, 24kHz PCM for speaker). No Base64 encoding will be used, saving 33% bandwidth and significantly reducing CPU overhead.

## Verification Plan
1. Start the server and connect the frontend.
2. Initiate a conversation with SIFRA.
3. Verify that the new Adaptive Jitter Buffer in `app.js` successfully queues incoming audio and smooths out network fluctuations without stuttering or popping.
