/**
 * audio-processor.js — WALL-E AI AudioWorklet Processor
 * Production-grade continuous audio streaming pipeline with Fast-Turn VAD.
 *
 * FIXED vs previous version:
 *   - Audio is sent CONTINUOUSLY while listening (not gated by VAD).
 *     Gemini Live has its own server-side VAD — we don't need to gate on client.
 *   - VAD is used ONLY to detect speech_stop for the fast-turn trigger.
 *   - VAD_THRESHOLD lowered to 0.0008 (was 0.0018) to work with quieter mics.
 *   - Noise suppression still silences audio while WALL-E is speaking (half-duplex).
 *
 * Created by K.Astra and its members.
 */

class WalleAudioProcessor extends AudioWorkletProcessor {
    constructor() {
        super();

        // ── Capture Buffer ────────────────────────────────────────────────────
        this.bufferSize  = 2048; // 42ms at 48kHz
        this.buffer      = new Float32Array(this.bufferSize);
        this.bufferIndex = 0;
        this.isRecording = false;
        this.isMuted     = false;

        // ── Fast-Turn VAD (for speech_stop detection only) ────────────────────
        // Lowered threshold — works with quieter/distant microphones.
        // Audio is sent continuously regardless; VAD only fires speech_stop.
        this.VAD_THRESHOLD = 0.0008;
        this.HOLD_FRAMES   = 4;  // ~170ms hold — prevents mid-word cutoffs
        this.holdCounter   = 0;
        this.isSpeaking    = false;

        // ── Volume smoothing (for orb animation only) ─────────────────────────
        this.smoothedEnergy          = 0;
        this.framesSinceVolumeReport = 0;

        // ── Message handler ───────────────────────────────────────────────────
        this.port.onmessage = (e) => {
            if (e.data.type === 'start') {
                this.isRecording = true;
                this.isSpeaking  = false;
                this.holdCounter = 0;
            } else if (e.data.type === 'stop') {
                this.isRecording    = false;
                this.isSpeaking     = false;
                this.holdCounter    = 0;
                this.bufferIndex    = 0;
                this.smoothedEnergy = 0;
            } else if (e.data.type === 'mute') {
                this.isMuted = true;
            } else if (e.data.type === 'unmute') {
                this.isMuted = false;
            }
        };
    }

    rms(buf) {
        let sum = 0;
        for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
        return Math.sqrt(sum / buf.length);
    }

    downsample(buf) {
        const ratio  = sampleRate / 16000;
        if (ratio <= 1) return buf;
        const outLen = Math.floor(buf.length / ratio);
        const out    = new Float32Array(outLen);
        for (let i = 0; i < outLen; i++) {
            const pos  = i * ratio;
            const lo   = Math.floor(pos);
            const hi   = Math.min(lo + 1, buf.length - 1);
            const frac = pos - lo;
            out[i] = buf[lo] * (1 - frac) + buf[hi] * frac;
        }
        return out;
    }

    toInt16(f32) {
        const i16 = new Int16Array(f32.length);
        for (let i = 0; i < f32.length; i++) {
            const s = Math.max(-1, Math.min(1, f32[i]));
            i16[i]  = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        return i16;
    }

    process(inputs) {
        if (!this.isRecording) return true;

        const ch = inputs[0]?.[0];
        if (!ch || ch.length === 0) return true;

        for (let i = 0; i < ch.length; i++) {
            this.buffer[this.bufferIndex++] = ch[i];

            if (this.bufferIndex >= this.bufferSize) {
                const energy = this.rms(this.buffer);

                // ── Volume report (throttled) for orb animation ───────────────
                this.smoothedEnergy = 0.85 * this.smoothedEnergy + 0.15 * energy;
                this.framesSinceVolumeReport++;
                if (this.framesSinceVolumeReport >= 4) {
                    this.port.postMessage({ type: 'volume', value: this.smoothedEnergy });
                    this.framesSinceVolumeReport = 0;
                }

                // ── Fast-Turn VAD (for speech_stop signal only) ───────────────
                // IMPORTANT: while muted (WALL-E is speaking), mic input is silent.
                // Don't run VAD during mute — the silence would falsely trigger
                // speech_stop which reaches the server and cuts WALL-E's voice.
                if (!this.isMuted) {
                    if (energy > this.VAD_THRESHOLD) {
                        if (!this.isSpeaking) {
                            this.isSpeaking = true;
                            this.port.postMessage({ type: 'speech_start' });
                        }
                        this.holdCounter = this.HOLD_FRAMES;
                    } else if (this.holdCounter > 0) {
                        this.holdCounter--;
                        if (this.holdCounter === 0 && this.isSpeaking) {
                            this.isSpeaking = false;
                            this.port.postMessage({ type: 'speech_stop' });
                        }
                    }
                } else {
                    // Reset VAD state so it starts fresh when unmuted
                    this.isSpeaking  = false;
                    this.holdCounter = 0;
                }

                // ── Send audio ────────────────────────────────────────────────
                // HALF-DUPLEX: drop frame while WALL-E is speaking (prevents echo).
                // Otherwise, send CONTINUOUSLY — Gemini Live has its own VAD server-side.
                if (!this.isMuted) {
                    const downsampled = this.downsample(this.buffer);
                    const pcm16       = this.toInt16(downsampled);
                    this.port.postMessage({ type: 'audio', data: pcm16.buffer }, [pcm16.buffer]);
                }

                this.bufferIndex = 0;
            }
        }
        return true;
    }
}

registerProcessor('walle-audio-processor', WalleAudioProcessor);
