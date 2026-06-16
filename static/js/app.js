/**
 * app.js — SIFRA AI Client
 * Industry-grade voice-only interface
 *
 * State machine:
 *   idle → [tap] → listening → [SIFRA responds] → speaking → [audio ends] → listening
 *                            → [tap again]      → idle
 *
 * Orb state flow:
 *   Server sends:
 *     "speaking"     — first audio chunk arrived, show speaking animation
 *     "turn_complete"— Gemini finished turn, schedule listening transition after audio plays
 *     "idle"         — session ended or error, reset to idle
 *   Client controls:
 *     listening      — when user taps orb
 *     idle           — when user taps again to stop
 */

'use strict';

// ── State ──────────────────────────────────────────────────────────────────
const State = {
    ws:                   null,
    audioContext:         null,      // AudioContext for mic input
    workletNode:          null,
    mediaStream:          null,
    isConnected:          false,
    isListening:          false,     // user has tapped and is in "listening mode"
    orbState:             'idle',
    reconnectAttempts:    0,
    maxReconnectAttempts: 12,
    reconnectTimer:       null,
    intentionalClose:     false,     // prevents reconnect on deliberate close
    volume:               0,
};

// ── Audio Playback State ─────────────────────────────────────────────────────
const Audio = {
    context:          null,          // AudioContext for AI voice playback
    scheduledEndTime: 0,
    isAISpeaking:     false,
    endTimer:         null,
    pendingListening: false,

    // Adaptive Jitter Buffer
    jitterBuffer:     [],
    isBuffering:      true,
    MIN_BUFFER_MS:    35,   // 35ms pre-roll — minimal buffering for fast first word
    _lastChunkTime:   0,
    _avgIntervalMs:   0,
    activeSources:    [],

    // Robotic FX chain (created once per AudioContext, reused per chunk)
    _fxChain:         null,
};

// ── Robotic Effect Chain ──────────────────────────────────────────────────
/**
 * buildRobotFX(ctx) — Formant-bank robot voice processor.
 *
 * Signal path (parallel formant synthesis):
 *
 *   source ──┬── BandPass(400Hz,Q=8)  ──┐
 *            ├── BandPass(900Hz,Q=6)  ──┤
 *            ├── BandPass(1800Hz,Q=5) ──┼── merge → WaveShaper → Compressor → dest
 *            └── BandPass(3200Hz,Q=4) ──┘
 *
 * Why formants instead of ring modulator:
 *   Ring mod at 60Hz creates a "Dalek" buzz that drowns out consonants.
 *   Parallel bandpass peaks keep the voice CLEAR and INTELLIGIBLE while
 *   giving the unmistakable mechanical, hollow robot character.
 *   The Q values create sharp resonant peaks — classic synthesiser robot.
 */
function buildRobotFX(ctx) {
    if (Audio._fxChain) return Audio._fxChain;

    // Input gain — slight cut before processing to avoid clip
    const inputGain = ctx.createGain();
    inputGain.gain.value = 0.9;

    // Merge node collects all parallel formant channels
    const merger = ctx.createGain();
    merger.gain.value = 0.25; // divide by ~4 channels to prevent clip

    // Formant frequencies: robot "throat" resonances
    const FORMANTS = [
        { freq: 400,  Q: 9  },   // chest cavity (deep hollow)
        { freq: 900,  Q: 7  },   // first vocal formant
        { freq: 1800, Q: 6  },   // second vocal formant (speech clarity)
        { freq: 3200, Q: 5  },   // high harmonic presence (metallic ring)
    ];

    FORMANTS.forEach(({ freq, Q }) => {
        const bp = ctx.createBiquadFilter();
        bp.type            = 'bandpass';
        bp.frequency.value = freq;
        bp.Q.value         = Q;
        inputGain.connect(bp);
        bp.connect(merger);
    });

    // Light waveshaper — adds harmonic overtones (metallic texture)
    const shaper = ctx.createWaveShaper();
    const N = 256;
    const curve = new Float32Array(N);
    for (let i = 0; i < N; i++) {
        const x = (i * 2) / N - 1;
        // Asymmetric soft-clip: adds odd harmonics (machine-like)
        curve[i] = x < 0
            ? -Math.pow(Math.abs(x), 0.7)
            :  Math.pow(x, 0.7);
    }
    shaper.curve = curve;
    shaper.oversample = '2x';

    // Dynamics compressor — keeps volume even, tightens attack
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -20;
    comp.knee.value      = 6;
    comp.ratio.value     = 8;
    comp.attack.value    = 0.003;
    comp.release.value   = 0.12;

    // Output gain — restore perceived loudness after compression
    const outGain = ctx.createGain();
    outGain.gain.value = 2.2;

    // Wire: merger → shaper → comp → outGain → destination
    merger.connect(shaper);
    shaper.connect(comp);
    comp.connect(outGain);
    outGain.connect(ctx.destination);

    Audio._fxChain = { input: inputGain, output: outGain };
    return Audio._fxChain;
}

// ── DOM ────────────────────────────────────────────────────────────────────
const DOM = {};
document.addEventListener('DOMContentLoaded', async () => {
    DOM.orb            = document.getElementById('voice-orb');
    DOM.orbCore        = document.getElementById('orb-core');
    DOM.orbStatus      = document.getElementById('orb-status');
    DOM.modeText       = document.getElementById('mode-text');
    DOM.connectionDot  = document.getElementById('connection-dot');
    DOM.connectionText = document.getElementById('connection-text');
    DOM.settingsBtn    = document.getElementById('settings-btn');
    DOM.themeToggleBtn = document.getElementById('theme-toggle-btn');
    DOM.greetingArea   = document.getElementById('greeting-area');
    DOM.greetingText   = document.getElementById('greeting-text');
    DOM.greetingSub    = document.getElementById('greeting-sub');

    // ── No login required — always K.Astra ──
    State.user = {
        id: 1,
        name: 'K.Astra',
        email: 'kastra@walle.ai',
        ai_voice: 'Aoede',
        ai_persona: 'Professional Executive Assistant'
    };

    DOM.greetingText.innerText = 'Hello K.Astra.';

    // Setup settings UI
    const creatorEl = document.getElementById('settings-creator');
    if (creatorEl) creatorEl.textContent = 'K.Astra';

    const voiceSelect = document.getElementById('settings-voice');
    if (voiceSelect) voiceSelect.value = State.user.ai_voice;

    const personaInput = document.getElementById('settings-persona');
    if (personaInput) personaInput.value = State.user.ai_persona;

    initWebSocket();
    initGeolocation();
    initOrbInteraction();
    initKeyboardShortcuts();
    initSettingsPanel();
    initThemeToggle();
    animateParticles();

    // Initialize premium orb renderer
    const orbCanvas = document.getElementById('orb-canvas');
    if (orbCanvas && typeof OrbRenderer !== 'undefined') {
        OrbRenderer.init(orbCanvas);
        OrbRenderer.setState('idle');
    }
});

// ── Geolocation ────────────────────────────────────────────────────────────────
/**
 * Requests browser GPS location, reverse-geocodes with OpenStreetMap Nominatim
 * (free, no API key), and sends city/country/coords to the server.
 * WALL-E can then answer "where am I?" or "weather here?" questions accurately.
 *
 * FIX: Geolocation resolves in ~1-2s but the WebSocket may not be open yet.
 * We store the pending location and flush it as soon as WS connects.
 */

// Holds the resolved location if WS wasn't ready when geolocation completed
State._pendingLocation = null;

function _sendLocationWhenReady(location) {
    if (State.ws?.readyState === WebSocket.OPEN) {
        sendCommand({ type: 'location_update', location });
        console.log(`[WALL-E] Location sent: ${location.city}, ${location.state}, ${location.country}`);
        State._pendingLocation = null;
    } else {
        // WS not open yet — queue it; flushPendingLocation() will send it on connect
        State._pendingLocation = location;
        console.log(`[WALL-E] Location queued (WS not ready): ${location.city}, ${location.state}, ${location.country}`);
    }
}

function flushPendingLocation() {
    if (State._pendingLocation && State.ws?.readyState === WebSocket.OPEN) {
        sendCommand({ type: 'location_update', location: State._pendingLocation });
        console.log(`[WALL-E] Flushed queued location: ${State._pendingLocation.city}`);
        State._pendingLocation = null;
    }
}

function initGeolocation() {
    if (!navigator.geolocation) {
        console.warn('[WALL-E] Geolocation not supported by this browser.');
        return;
    }

    const opts = { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 };

    navigator.geolocation.getCurrentPosition(
        async (pos) => {
            const { latitude: lat, longitude: lon, accuracy } = pos.coords;
            console.log(`[WALL-E] GPS acquired: ${lat.toFixed(4)}, ${lon.toFixed(4)} ±${Math.round(accuracy)}m`);

            // Reverse geocode via OpenStreetMap Nominatim (free, no key needed)
            let city = '', state = '', country = '', timezone = '';
            try {
                const url = `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json`;
                const resp = await fetch(url, {
                    headers: { 'Accept-Language': 'en', 'User-Agent': 'WALL-E-AI/2.0' }
                });
                if (resp.ok) {
                    const geo = await resp.json();
                    const addr = geo.address || {};
                    city    = addr.city || addr.town || addr.village || addr.county || '';
                    state   = addr.state || addr.region || '';
                    country = addr.country || '';
                }
            } catch (err) {
                console.warn('[WALL-E] Reverse geocode failed:', err.message);
            }

            // Get timezone from browser
            try { timezone = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch (_) {}

            const location = {
                lat:        lat.toFixed(6),
                lon:        lon.toFixed(6),
                accuracy_m: Math.round(accuracy),
                city, state, country, timezone,
            };

            // Send to server — will be stored for WALL-E's get_user_location tool
            sendCommand({ type: 'location_update', location });
            console.log(`[WALL-E] Location sent: ${city}, ${state}, ${country}`);
        },
        (err) => {
            // Non-fatal — WALL-E still works, just can't answer location questions
            console.warn(`[WALL-E] Location permission denied or unavailable: ${err.message}`);
        },
        opts
    );
}


// ── WebSocket ──────────────────────────────────────────────────────────────
function initWebSocket() {
    // Clear any pending reconnect
    if (State.reconnectTimer) {
        clearTimeout(State.reconnectTimer);
        State.reconnectTimer = null;
    }

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl    = `${protocol}//${location.host}/ws`;

    State.ws = new WebSocket(wsUrl);
    State.ws.binaryType = 'arraybuffer';

    State.ws.onopen = () => {
        console.log('[SIFRA] WebSocket connected');
        State.isConnected       = true;
        State.reconnectAttempts = 0;   // reset on successful connect
        State.intentionalClose  = false;
        updateConnectionStatus('connected');
        setOrbState('idle');
        // Flush any location that resolved before WS was open
        flushPendingLocation();
    };

    State.ws.onclose = (e) => {
        console.warn('[SIFRA] WebSocket closed:', e.code, e.reason);
        State.isConnected = false;

        // If we closed intentionally (e.g., page navigating away), don't reconnect
        if (State.intentionalClose) {
            updateConnectionStatus('disconnected');
            return;
        }

        updateConnectionStatus('disconnected');

        // If user was listening, show them the error state
        if (State.isListening) {
            setOrbState('error');
        } else {
            // Force eyes to sad even if not actively listening
            if (typeof setEyeState !== 'undefined') setEyeState('sad');
        }

        scheduleReconnect();
    };

    State.ws.onerror = (e) => {
        console.error('[SIFRA] WebSocket error:', e);
        updateConnectionStatus('error');
    };

    State.ws.onmessage = (event) => {
        if (event.data instanceof ArrayBuffer) {
            handleAudioChunk(event.data);
        } else {
            try {
                handleServerEvent(JSON.parse(event.data));
            } catch (e) {
                console.warn('[SIFRA] Bad JSON from server:', e);
            }
        }
    };
}

function scheduleReconnect() {
    if (State.reconnectAttempts >= State.maxReconnectAttempts) {
        updateConnectionStatus('failed');
        showToast('Connection failed. Please refresh the page.', 'error');
        return;
    }
    State.reconnectAttempts++;
    // Exponential backoff: 1s, 1.5s, 2.25s... capped at 20s
    const delay = Math.min(1000 * Math.pow(1.5, State.reconnectAttempts - 1), 20000);
    console.log(`[SIFRA] Reconnecting in ${(delay/1000).toFixed(1)}s (attempt ${State.reconnectAttempts}/${State.maxReconnectAttempts})`);
    updateConnectionStatus('reconnecting');
    State.reconnectTimer = setTimeout(() => {
        // Only reconnect if still not connected
        if (!State.isConnected && !State.intentionalClose) {
            initWebSocket();
        }
    }, delay);
}

function sendCommand(cmd) {
    if (State.ws?.readyState === WebSocket.OPEN) {
        State.ws.send(JSON.stringify(cmd));
    }
}

// ── Server Events ───────────────────────────────────────────────────────────
function handleServerEvent(data) {
    switch (data.type) {

        case 'state':
            handleOrbStateFromServer(data.orb);
            break;

        case 'status':
            if (data.state === 'connected') {
                updateConnectionStatus('connected');
            } else if (data.state === 'reconnecting') {
                updateConnectionStatus('reconnecting');
            } else if (data.state === 'error' && data.message) {
                showToast(data.message, 'error');
            }
            break;

        case 'identity':
            if (data.name && DOM.greetingText) {
                DOM.greetingText.textContent = `Hello ${data.name}.`;
            }
            break;

        case 'ping':
            // Server heartbeat — respond with pong
            sendCommand({ type: 'pong', time: data.time });
            break;

        case 'pong':
            // Response to our ping — connection alive
            break;
    }
}

/**
 * Handle orb state signals from the server.
 *
 * Server sends these values:
 *   "speaking"      — SIFRA's first audio chunk arrived
 *   "turn_complete" — SIFRA finished speaking; client should go listening after audio ends
 *   "idle"          — session ended or fatal error
 */
function handleOrbStateFromServer(orbValue) {
    if (!orbValue) return;

    switch (orbValue) {
        case 'speaking':
            // SIFRA is now talking — show speaking state
            Audio.isAISpeaking = true;
            Audio.pendingListening = false; // cancel any pending transition
            setOrbState('speaking');
            // Proactively mute local mic processing while SIFRA talks
            if (State.workletNode) {
                State.workletNode.port.postMessage({ type: 'mute' });
            }
            break;

        case 'tool_working':
            // SIFRA is executing a tool call (opening app, playing music, etc.).
            // We used to flush the audio here, but that caused her voice to cut off
            // abruptly if she started a sentence before the tool call.
            // Now we just change the visual state and let any queued audio play naturally.
            console.log("[SIFRA] Tool executing.");
            setOrbState('thinking');
            break;

        case 'turn_complete':
            // The server notified us that Gemini finished generating the response.
            // We ignore this event for UI transitions! 
            // The UI will naturally snap back to 'listening' the exact millisecond 
            // the audio buffer physically finishes playing in checkAndTransitionEndSpeech().
            console.log("[SIFRA] Server turn complete. UI will transition when audio drains.");
            break;

        case 'idle':
            // Server says session ended / error
            clearAISpeakingState();
            if (!State.isListening) {
                setOrbState('idle');
            }
            break;

        default:
            // Unknown state from server — ignore
            break;
    }
}

// ── Microphone ─────────────────────────────────────────────────────────────
async function startMicrophone() {
    if (State.isMicActive) return true;

    try {
        State.mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                channelCount:     1,
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl:  true,
            }
        });
        console.log('[WALL-E] Microphone access granted');

        // Use 48kHz for mic input (most devices support this natively)
        State.audioContext = new (window.AudioContext || window.webkitAudioContext)({
            sampleRate: 48000
        });

        // Initialize output Audio.context here during the user gesture to unlock playback
        if (!Audio.context) {
            Audio.context = new (window.AudioContext || window.webkitAudioContext)({
                sampleRate: 24000
            });
        }
        if (Audio.context.state === 'suspended') {
            Audio.context.resume().catch(() => {});
        }

        // Cache buster ensures fresh worklet on every deploy
        try {
            await State.audioContext.audioWorklet.addModule('/static/js/audio-processor.js?v=55');
        } catch (workletErr) {
            console.error('[WALL-E] AudioWorklet failed to load:', workletErr);
            showToast('Audio engine error: ' + workletErr.message, 'error');
            throw workletErr;
        }

        const source      = State.audioContext.createMediaStreamSource(State.mediaStream);
        State.workletNode = new AudioWorkletNode(State.audioContext, 'walle-audio-processor');

        State.workletNode.port.onmessage = (event) => {
            const { type, data, value } = event.data;

            if (type === 'audio') {
                // HALF-DUPLEX: mute mic while WALL-E is speaking so she doesn't hear herself
                if (State.isConnected && State.isListening && !Audio.isAISpeaking) {
                    if (State.ws?.readyState === WebSocket.OPEN) {
                        State.ws.send(data);
                        // DEBUG: log every 100th chunk so we know audio is flowing
                        State._audioChunkCount = (State._audioChunkCount || 0) + 1;
                        if (State._audioChunkCount % 100 === 1) {
                            console.log(`[WALL-E] Mic audio flowing: chunk #${State._audioChunkCount}, bytes=${data.byteLength}`);
                        }
                    }
                }
            } else if (type === 'volume') {
                State.volume = value;
                updateOrbVolume();
                // Show mic level in status text so user can confirm mic works
                if (State.isListening && DOM.orbStatus) {
                    const bars = value > 0.02 ? '████' : value > 0.008 ? '██░░' : value > 0.002 ? '█░░░' : '░░░░';
                    DOM.orbStatus.textContent = `Listening  ${bars}`;
                }
            } else if (type === 'speech_start') {
                console.log('[WALL-E] VAD: speech detected');
            } else if (type === 'speech_stop') {
                // ── FAST-TURN TRIGGER ──
                // Explicitly tell the server that the user finished speaking.
                // This bypasses Gemini\'s slow 3-4s native silence detection.
                console.log('[WALL-E] VAD: speech ended → sending speech_stop');
                sendCommand({ type: 'speech_stop' });
            }
        };

        source.connect(State.workletNode);
        // Connect to destination to keep worklet alive (some browsers need this)
        State.workletNode.connect(State.audioContext.destination);
        State.workletNode.port.postMessage({ type: 'start' });
        State.isMicActive = true;
        return true;

    } catch (err) {
        console.error('[SIFRA] Mic error:', err);
        const msg = err.name === 'NotAllowedError'
            ? 'Microphone permission denied. Please allow mic access.'
            : 'Mic error: ' + err.message;
        showToast(msg, 'error');
        // Clean up on failure
        if (State.mediaStream) {
            State.mediaStream.getTracks().forEach(t => t.stop());
            State.mediaStream = null;
        }
        if (State.audioContext) {
            try { State.audioContext.close(); } catch (_) {}
            State.audioContext = null;
        }
        return false;
    }
}

function stopMicrophone() {
    if (State.workletNode) {
        try { State.workletNode.port.postMessage({ type: 'stop' }); } catch (_) {}
        try { State.workletNode.disconnect(); } catch (_) {}
        State.workletNode = null;
    }
    if (State.mediaStream) {
        State.mediaStream.getTracks().forEach(t => t.stop());
        State.mediaStream = null;
    }
    if (State.audioContext) {
        try { State.audioContext.close(); } catch (_) {}
        State.audioContext = null;
    }
    State.isMicActive = false;
    State.isListening = false;
}

// ── Orb Volume Animation ───────────────────────────────────────────────────
function updateOrbVolume() {
    if (State.orbState !== 'listening' && State.orbState !== 'speaking') return;
    const vol = State.volume;

    // Feed volume to canvas renderer for fluid reactivity
    if (typeof OrbRenderer !== 'undefined') {
        OrbRenderer.setVolume(vol);
    }

    if (State.orbState === 'listening' && vol > 0.008) {
        const scale = 1 + Math.min(vol * 3.5, 0.22);
        const glow  = Math.min(vol * 500, 70);
        DOM.orb.style.transform = `scale(${scale.toFixed(3)})`;
        DOM.orb.style.boxShadow = `0 0 ${glow}px rgba(255,255,255,${Math.min(0.3 + vol * 3, 0.9)})`;
    } else if (State.orbState === 'listening') {
        DOM.orb.style.transform = '';
        DOM.orb.style.boxShadow = '';
    }
}

// ── Audio Playback ─────────────────────────────────────────────────────
/**
 * Production-grade audio playback with Adaptive Jitter Buffer.
 *
 * How it works (like Grok/GPT Voice):
 *  1. Measure how fast chunks are arriving from the server.
 *  2. Dynamically set the buffer target: fast network = 60ms, slow = 150ms.
 *  3. Schedule every chunk precisely on the Web Audio timeline.
 *  4. Use dual end-detection (onended + setTimeout) for a frame-perfect
 *     transition back to listening mode.
 */
function handleAudioChunk(arrayBuffer) {
    if (!Audio.context) {
        Audio.context = new (window.AudioContext || window.webkitAudioContext)({
            sampleRate: 24000
        });
    }
    if (Audio.context.state === 'suspended') {
        Audio.context.resume().catch(() => {});
    }

    Audio.isAISpeaking = true;

    // ── ADAPTIVE BUFFER: measure chunk arrival interval ─────────────────────
    const now = performance.now();
    if (Audio._lastChunkTime > 0) {
        const interval = now - Audio._lastChunkTime;
        Audio._avgIntervalMs = Audio._avgIntervalMs === 0
            ? interval
            : 0.85 * Audio._avgIntervalMs + 0.15 * interval;
        Audio.MIN_BUFFER_MS = Math.max(60, Math.min(150, Audio._avgIntervalMs * 2));
    }
    Audio._lastChunkTime = now;

    // ── BYTE ALIGNMENT FIX (Industry Level) ─────────────────────────────────
    // Gemini can send chunks with odd byte lengths. If we blindly cast to Int16Array,
    // it throws an error (dropping chunks = cracking) or misaligns the byte order 
    // (MSB/LSB swap = robot/static voice).
    if (!Audio.rawByteQueue) Audio.rawByteQueue = new Uint8Array(0);

    const incoming = new Uint8Array(arrayBuffer);
    const combined = new Uint8Array(Audio.rawByteQueue.length + incoming.length);
    combined.set(Audio.rawByteQueue, 0);
    combined.set(incoming, Audio.rawByteQueue.length);

    // Calculate how many complete 16-bit samples we have
    const sampleCount = Math.floor(combined.length / 2);
    const float32 = new Float32Array(sampleCount);
    
    // Parse safely as Little-Endian
    const dataView = new DataView(combined.buffer);
    for (let i = 0; i < sampleCount; i++) {
        // true = little endian (standard for PCM)
        const int16 = dataView.getInt16(i * 2, true);
        float32[i] = int16 / 32768.0;
    }

    // Save any leftover odd byte for the next chunk
    const leftoverBytes = combined.length % 2;
    Audio.rawByteQueue = new Uint8Array(combined.buffer, combined.length - leftoverBytes, leftoverBytes);

    if (float32.length > 0) {
        Audio.jitterBuffer.push(float32);
        processJitterBuffer();
    }
}

function processJitterBuffer(force = false) {
    const now = Audio.context?.currentTime || 0;

    if (Audio.endTimer) {
        clearTimeout(Audio.endTimer);
        Audio.endTimer = null;
    }

    if (Audio.jitterBuffer.length === 0) {
        if (Audio.isAISpeaking) scheduleEndTimer();
        return;
    }

    // Re-enter buffering mode if the playhead fell behind (network stall recovery)
    if (Audio.scheduledEndTime < now) {
        Audio.isBuffering = true;
    }

    // Calculate total milliseconds queued
    const samplesQueued = Audio.jitterBuffer.reduce((acc, b) => acc + b.length, 0);
    const msQueued      = (samplesQueued / 24000) * 1000;

    // Block until we have enough lookahead, unless force-flushing at turn_complete
    if (!force && Audio.isBuffering && msQueued < Audio.MIN_BUFFER_MS) {
        scheduleEndTimer(); // keep the end timer alive while buffering
        return;
    }

    if (Audio.isBuffering) {
        Audio.isBuffering = false;
        // 30ms pre-roll: gives the scheduler a small head start
        Audio.scheduledEndTime = now + 0.03;
    }

    // Drain and schedule every chunk gaplessly onto the Web Audio timeline
    while (Audio.jitterBuffer.length > 0) {
        const float32 = Audio.jitterBuffer.shift();

        const audioBuf = Audio.context.createBuffer(1, float32.length, 24000);
        audioBuf.getChannelData(0).set(float32);

        const source = Audio.context.createBufferSource();
        source.buffer = audioBuf;

        // ── Route through Robotic FX chain ──
        const fx = buildRobotFX(Audio.context);
        source.connect(fx.input);

        Audio.activeSources.push(source);

        // Guard against drift if the main thread was blocked
        if (Audio.scheduledEndTime < Audio.context.currentTime) {
            Audio.scheduledEndTime = Audio.context.currentTime + 0.01;
        }

        source.start(Audio.scheduledEndTime);

        source.onended = () => {
            const idx = Audio.activeSources.indexOf(source);
            if (idx > -1) Audio.activeSources.splice(idx, 1);

            // Only transition when every source has finished.
            // Then wait 200ms for the DynamicsCompressor release tail to fully drain
            // through the FX chain before we declare speech ended.
            // Without this delay the last ~150ms of the voice gets clipped.
            if (Audio.activeSources.length === 0) {
                setTimeout(() => checkAndTransitionEndSpeech(), 200);
            }
        };

        Audio.scheduledEndTime += audioBuf.duration;
    }

    scheduleEndTimer();
}

/**
 * Precision setTimeout that fires exactly when audio ends.
 */
function scheduleEndTimer() {
    if (Audio.endTimer) clearTimeout(Audio.endTimer);
    const now        = Audio.context?.currentTime || 0;
    const msUntilEnd = Math.max((Audio.scheduledEndTime - now) * 1000, 0);

    if (msUntilEnd <= 0 && Audio.isAISpeaking) {
        checkAndTransitionEndSpeech();
        return;
    }

    Audio.endTimer = setTimeout(() => {
        checkAndTransitionEndSpeech();
    }, msUntilEnd + 220); // 220ms = 15ms jitter + 205ms FX compressor release tail
}

/**
 * Checks if audio has truly finished and transitions state if needed.
 */
function checkAndTransitionEndSpeech() {
    const now = Audio.context?.currentTime || 0;
    
    // If there's still more scheduled audio (e.g. new chunks arrived), just reschedule
    if (now < Audio.scheduledEndTime - 0.02) {
        scheduleEndTimer();
        return;
    }

    // Speech is definitely done
    console.log("[SIFRA] Speech finished.");
    Audio.isAISpeaking = false;
    Audio.endTimer     = null;
    Audio.isBuffering  = true;

    // ── ROBUST TRANSITION ──
    // If the audio buffer is completely empty and playback has stopped, 
    // we are physically no longer speaking. Always snap back to listening 
    // mode immediately, even if the server's turn_complete signal was delayed/lost.
    if (State.isListening) {
        setOrbState('listening');
    }
    // Restore mic processing after SIFRA finishes talking
    if (State.workletNode) {
        State.workletNode.port.postMessage({ type: 'unmute' });
    }
}

/**
 * Emergency cleanup for SIFRA speaking state
 */
function clearAISpeakingState(unmuteMic = true) {
    Audio.isAISpeaking     = false;
    Audio.pendingListening = false;
    Audio.isBuffering      = true;
    if (Audio.endTimer) clearTimeout(Audio.endTimer);
    Audio.endTimer = null;
    Audio.jitterBuffer = [];
    Audio.rawByteQueue = new Uint8Array(0);

    // CRITICAL: disconnect the FX chain output from ctx.destination BEFORE
    // nulling the reference. Without this, each new session builds a NEW chain
    // and connects it to destination, while old chains remain connected and
    // keep running — causing compressor accumulation, gain overflow, cutoffs,
    // and the 'stuck at speaking' state.
    if (Audio._fxChain) {
        try { Audio._fxChain.output.disconnect(); } catch (e) {}
        Audio._fxChain = null;
    }

    // Stop all active sources immediately
    Audio.activeSources.forEach(source => {
        try { source.stop(); } catch (e) {}
    });
    Audio.activeSources = [];
    Audio.scheduledEndTime = 0;

    if (State.workletNode && unmuteMic) {
        State.workletNode.port.postMessage({ type: 'unmute' });
    }
}

// ── Orb Tap — Toggle Listening ────────────────────────────────────────────
function initOrbInteraction() {
    DOM.orb.addEventListener('click', handleOrbTap);
    DOM.orb.addEventListener('touchend', (e) => {
        e.preventDefault();
        handleOrbTap();
    }, { passive: false });
}

async function handleOrbTap() {
    if (!State.isConnected) {
        showToast('Not connected yet...', 'error');
        return;
    }

    // ── INTERRUPT: tap while SIFRA is speaking → stop her, go to listening ──
    if (State.orbState === 'speaking') {
        // 1. Kill audio playback immediately
        clearAISpeakingState();
        // 2. Tell the server to cancel Gemini's current turn
        sendCommand({ type: 'interrupt' });
        // 3. Start mic if not already active, then go to listening
        if (!State.isMicActive) {
            const ok = await startMicrophone();
            if (!ok) return;
        }
        State.isListening = true;
        setOrbState('listening');
        showToast("Go ahead, I'm listening 👂", 'success');
        return;
    }

    if (State.isListening) {
        // Already listening → stop everything
        State.isListening      = false;
        Audio.pendingListening = false;
        stopMicrophone();
        setOrbState('idle');
        showToast('Mic off 🔇');
    } else {
        // Not listening → start
        const ok = await startMicrophone();
        if (ok) {
            State.isListening = true;
            setOrbState('listening');
            showToast("I'm listening! 👂", 'success');
        }
    }
}

// ── Keyboard Shortcuts ─────────────────────────────────────────────────────
function initKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        if (e.code === 'Space' && !e.repeat) {
            e.preventDefault();
            handleOrbTap();
        }
        if (e.code === 'Escape') {
            if (State.isListening) {
                State.isListening = false;
                stopMicrophone();
                setOrbState('idle');
            }
        }
    });
}

// ── Orb State Machine ──────────────────────────────────────────────────────
function setOrbState(state) {
    State.orbState = state;

    // Reset inline transform/shadow (volume animation may have set them)
    DOM.orb.style.transform = '';
    DOM.orb.style.boxShadow = '';
    DOM.orb.className = 'voice-orb ' + state;

    // Update canvas orb renderer
    if (typeof OrbRenderer !== 'undefined') {
        OrbRenderer.setState(state);
    }

    // ── Sync eye emotion to orb state ──
    setEyeState(state);

    const statusMap = {
        idle:      'Ready',
        listening: 'Listening',
        thinking:  'Thinking...',
        speaking:  'Speaking',
        error:     'Offline',
    };

    // Watchdog: If we enter speaking, set a safety timeout to prevent getting stuck
    if (state === 'speaking') {
        if (window._speakingWatchdog) clearTimeout(window._speakingWatchdog);
        window._speakingWatchdog = setTimeout(() => {
            if (State.orbState === 'speaking') {
                console.warn("[SIFRA] Watchdog: SIFRA stuck in speaking too long. Resetting.");
                checkAndTransitionEndSpeech();
            }
        }, 15000); // 15s absolute limit for a single audio turn without new chunks
    } else if (window._speakingWatchdog) {
        clearTimeout(window._speakingWatchdog);
    }
    const subMap = {
        idle:      'Tap to start',
        listening: "I'm all ears 👂",
        thinking:  'Hmm, give me a sec...',
        speaking:  'WALL-E is talking...',
        error:     'Reconnecting...',
    };

    DOM.orbStatus.textContent = statusMap[state] || 'Ready';
    DOM.modeText.textContent  = subMap[state]    || '';

    // Update orb icon
    const micPath = `<path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3Z"/>
                     <path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v4m-4 0h8"/>`;

    const icons = {
        idle: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">${micPath}</svg>`,

        listening: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">${micPath}</svg>`,

        thinking: `<svg class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                     <circle cx="12" cy="12" r="10" stroke-dasharray="40 20" stroke-linecap="round"/>
                   </svg>`,

        speaking: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                     <path d="M9 18V5l12-2v13"/>
                     <path d="M6 15H3a1 1 0 0 0-1 1v3a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-3a1 1 0 0 0-1-1Z"/>
                     <path d="M18 13h-3a1 1 0 0 0-1 1v3a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-3a1 1 0 0 0-1-1Z"/>
                   </svg>`,

        error: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                  <circle cx="12" cy="12" r="10"/>
                  <path d="m15 9-6 6m0-6 6 6"/>
                </svg>`,
    };

    if (DOM.orbCore) {
        DOM.orbCore.innerHTML = icons[state] || icons.idle;
    }
}

// ── Eye Emotion Controller ──────────────────────────────────────────────────
window.setEyeState = function (state) {
    if (typeof EyeRenderer !== 'undefined') {
        EyeRenderer.setState(state);
    }
};

// Expose testing function so user can trigger explicit emotions from console or shortcuts
window.testEmotion = function(emotion) {
    setEyeState(emotion);
    console.log(`[Emotions] Triggered: ${emotion}`);
};

// ── Connection Status ──────────────────────────────────────────────────────
function updateConnectionStatus(status) {
    if (!DOM.connectionDot) return;
    DOM.connectionDot.className = 'dot ' + status;
    const labels = {
        connected:    'Connected',
        connecting:   'Connecting...',
        disconnected: 'Disconnected',
        reconnecting: 'Reconnecting...',
        error:        'Error',
        failed:       'Connection Failed',
    };
    DOM.connectionText.textContent = labels[status] || status;
}

// ── Toast ──────────────────────────────────────────────────────────────────
function showToast(message, type = 'info') {
    // Remove any existing toast immediately
    document.querySelectorAll('.toast').forEach(t => t.remove());

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    // Trigger animation on next frame
    requestAnimationFrame(() => {
        requestAnimationFrame(() => toast.classList.add('visible'));
    });

    setTimeout(() => {
        toast.classList.remove('visible');
        setTimeout(() => toast.remove(), 400);
    }, 3000);
}

// ── Theme Toggle ──────────────────────────────────────────────────────────────
function initThemeToggle() {
    const saved = localStorage.getItem('sifra-theme') || 'dark';
    if (saved === 'light') document.body.classList.add('light');

    function applyTheme(isLight) {
        document.body.classList.toggle('light', isLight);
        localStorage.setItem('sifra-theme', isLight ? 'light' : 'dark');
        const settingsToggle = document.getElementById('settings-theme-toggle');
        if (settingsToggle) settingsToggle.checked = isLight;
        const modeLabel = document.getElementById('toggle-mode-label');
        if (modeLabel) modeLabel.textContent = isLight ? 'Light' : 'Dark';
    }

    // Nav button
    DOM.themeToggleBtn?.addEventListener('click', () => {
        const isLight = !document.body.classList.contains('light');
        applyTheme(isLight);
        showToast(isLight ? '☀️ Light mode' : '🌙 Dark mode');
    });

    // In-settings toggle
    const inSettingsToggle = document.getElementById('settings-theme-toggle');
    if (inSettingsToggle) {
        inSettingsToggle.checked = saved === 'light';
        inSettingsToggle.addEventListener('change', () => {
            applyTheme(inSettingsToggle.checked);
            showToast(inSettingsToggle.checked ? '☀️ Light mode' : '🌙 Dark mode');
        });
    }

    // Sync label on load
    const modeLabel = document.getElementById('toggle-mode-label');
    if (modeLabel) modeLabel.textContent = saved === 'light' ? 'Light' : 'Dark';
}

// ── Settings Panel ─────────────────────────────────────────────────────────
function initSettingsPanel() {
    const panel    = document.getElementById('settings-panel');
    const backdrop = document.getElementById('settings-backdrop');
    const closeBtn = document.getElementById('settings-close');
    const saveBtn  = document.getElementById('settings-save-btn');
    const logoutBtn= document.getElementById('logout-btn');

    function openSettings() {
        panel?.classList.add('open');
        backdrop?.classList.add('open');
        document.body.style.overflow = 'hidden';
    }
    function closeSettings() {
        panel?.classList.remove('open');
        backdrop?.classList.remove('open');
        document.body.style.overflow = '';
    }

    DOM.settingsBtn?.addEventListener('click', (e) => {
        e.stopPropagation();
        panel?.classList.contains('open') ? closeSettings() : openSettings();
    });

    closeBtn?.addEventListener('click', closeSettings);
    backdrop?.addEventListener('click', closeSettings);

    // Keyboard: Escape closes modal
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && panel?.classList.contains('open')) {
            closeSettings();
        }
    });

    // ── Save Preferences ──
    saveBtn?.addEventListener('click', async () => {
        const voice   = document.getElementById('settings-voice')?.value;
        const persona = document.getElementById('settings-persona')?.value;

        if (!voice) { showToast('Please select a voice.', 'error'); return; }

        saveBtn.disabled = true;
        saveBtn.textContent = 'Saving…';

        try {
            const res = await fetch('/api/auth/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ai_voice: voice, ai_persona: persona }),
            });
            if (res.ok) {
                // Update local state so UI is in sync
                State.user.ai_voice   = voice;
                State.user.ai_persona = persona;

                showToast(`Voice set to ${voice} — Reconnecting…`, 'success');

                // Tell server to restart Gemini session with new voice
                sendCommand({ type: 'settings_changed' });

                // Close settings panel after brief delay
                setTimeout(() => closeSettings(), 800);
            } else {
                showToast('Save failed. Try again.', 'error');
            }
        } catch (e) {
            showToast('Network error — check connection.', 'error');
        } finally {
            saveBtn.disabled = false;
            saveBtn.textContent = 'Save Changes';
        }
    });

    // ── Logout (removed — no login system) ──
    logoutBtn?.addEventListener('click', () => {
        closeSettings();
        showToast('No login required — WALL-E is always here.', 'info');
    });
}

// ── Ambient Background — Colorful floating particles ─────────────
function animateParticles() {
    const canvas = document.getElementById('particles-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    function resize() {
        canvas.width  = window.innerWidth;
        canvas.height = window.innerHeight;
    }
    resize();
    window.addEventListener('resize', resize);

    // Vibrant color palette for particles
    const COLORS = [
        [0, 200, 255],    // cyan
        [160, 80, 255],   // purple
        [255, 80, 180],   // pink
        [80, 120, 255],   // blue
        [80, 255, 160],   // green
        [255, 200, 80],   // gold
        [255, 255, 255],  // white
    ];

    class Particle {
        constructor() { this.reset(); }
        reset() {
            this.x = Math.random() * canvas.width;
            this.y = Math.random() * canvas.height;
            this.size = Math.random() * 1.2 + 0.3;
            this.vx = (Math.random() - 0.5) * 0.15;
            this.vy = (Math.random() - 0.5) * 0.10;
            this.color = COLORS[Math.floor(Math.random() * COLORS.length)];
            this.opacity = Math.random() * 0.25 + 0.04;
            this.twinkleSpeed = Math.random() * 0.005 + 0.001;
            this.twinkleDir = Math.random() > 0.5 ? 1 : -1;
        }
        update() {
            this.x += this.vx;
            this.y += this.vy;
            if (this.x < -10 || this.x > canvas.width + 10 ||
                this.y < -10 || this.y > canvas.height + 10) {
                this.reset();
            }
            this.opacity += this.twinkleSpeed * this.twinkleDir;
            if (this.opacity > 0.28 || this.opacity < 0.03) this.twinkleDir *= -1;
        }
        draw() {
            ctx.beginPath();
            ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(${this.color[0]},${this.color[1]},${this.color[2]},${this.opacity})`;
            ctx.fill();
        }
    }

    const particles = Array.from({ length: 80 }, () => new Particle());

    let animId = null;
    function animate() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        particles.forEach(p => { p.update(); p.draw(); });
        animId = requestAnimationFrame(animate);
    }
    animate();

    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            if (animId) cancelAnimationFrame(animId);
        } else {
            animate();
        }
    });
}
