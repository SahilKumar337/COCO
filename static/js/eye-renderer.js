/**
 * eye-renderer.js — WALL-E Animated Eyes v3
 * - NO cursor tracking
 * - Idle: organic saccadic gaze drift (looks around naturally)
 * - Listening: instantly centers, wide open, locked focus (attentive)
 * - Speaking: gentle happy squint, slow drift off
 * - Thinking: asymmetric upward look
 * - Realistic blink system: random intervals + occasional double-blinks
 * Created by K.Astra and its members.
 */

'use strict';

const EyeRenderer = (() => {

    // ── Canvas & Context ─────────────────────────────────────────────────────
    let lCanvas, rCanvas, lCtx, rCtx;
    let animId = null;
    const CW = 130, CH = 130;

    // ── Current state name ───────────────────────────────────────────────────
    let currentState = null;

    // ── State Presets ────────────────────────────────────────────────────────
    const PRESETS = {
        idle: {
            lOpen: 0.85, rOpen: 0.85,
            pupilX: 0, pupilY: 0,
            irisR: 28, pupilR: 12,
            ir: 56,  ig: 189, ib: 248,   // cyan
            lTilt: 0, rTilt: 0,
            // blink intervals [minMs, maxMs]
            blinkMs: [2800, 5500],
            // allow saccadic drift
            allowDrift: true,
        },
        listening: {
            lOpen: 1.0, rOpen: 1.0,      // Wide open — fully attentive
            pupilX: 0, pupilY: 0,        // Dead centre — locked on speaker
            irisR: 33, pupilR: 17,       // Dilated
            ir: 125, ig: 211, ib: 252,   // bright sky blue
            lTilt: 0, rTilt: 0,
            blinkMs: [4000, 7000],       // blinks less when attentive
            allowDrift: false,           // NO drift — eyes stay locked forward
        },
        thinking: {
            lOpen: 0.75, rOpen: 0.60,    // Asymmetric squint
            pupilX: -0.38, pupilY: -0.45,// Look up-left
            irisR: 26, pupilR: 10,
            ir: 139, ig: 92, ib: 246,    // violet
            lTilt: -0.15, rTilt: 0.20,
            blinkMs: null,               // no blink while thinking
            allowDrift: false,
        },
        speaking: { // Also acts as "Happy"
            lOpen: 0.70, rOpen: 0.70,    // Joyful squint
            pupilX: 0, pupilY: 0,        // Looking straight at user
            irisR: 26, pupilR: 12,
            ir: 52,  ig: 211, ib: 153,   // mint green (vibrant)
            lTilt: -0.15, rTilt: 0.15,   // Joyful arch shape
            blinkMs: null,               // no blink while speaking
            allowDrift: false,
        },
        error: { // Generic error
            lOpen: 0.65, rOpen: 0.65,
            pupilX: 0, pupilY: 0.45,
            irisR: 24, pupilR: 11,
            ir: 239, ig: 68, ib: 68,     // red
            lTilt:  0.25, rTilt: -0.25,
            blinkMs: null,
            allowDrift: false,
        },
        sad: { // Disconnected / lost
            lOpen: 0.40, rOpen: 0.40,    // Droopy eyelids
            pupilX: 0, pupilY: 0.60,     // Looking down at the floor
            irisR: 22, pupilR: 14,
            ir: 100, ig: 116, ib: 139,   // Muted slate blue/grey
            lTilt: 0.25, rTilt: -0.25,   // Sad outer droop
            blinkMs: [5000, 8000],       // Slow, heavy blinks
            allowDrift: false,
        },
        astonished: { // Shocked / surprised
            lOpen: 1.15, rOpen: 1.15,    // Extremely wide open
            pupilX: 0, pupilY: 0,        // Locked center
            irisR: 22, pupilR: 8,        // Pin-prick pupils (shock)
            ir: 250, ig: 204, ib: 21,    // Bright yellow
            lTilt: 0, rTilt: 0,
            blinkMs: null,               // Staring
            allowDrift: false,
        },
        angry: { // Frustrated / intense
            lOpen: 0.50, rOpen: 0.50,    // Heavy angry squint
            pupilX: 0, pupilY: -0.10,    // Glaring straight ahead
            irisR: 28, pupilR: 10,
            ir: 220, ig: 38, ib: 38,     // Deep crimson red
            lTilt: 0.30, rTilt: -0.30,   // Sharp inner V-shape (furrowed brow)
            blinkMs: null,
            allowDrift: false,
        },
    };

    // ── Live animated values (lerped every frame) ────────────────────────────
    const cur = { ...PRESETS.idle };
    const tgt = { ...PRESETS.idle };

    // ── Blink system ─────────────────────────────────────────────────────────
    let blinkTimer   = null;
    let blinkValue   = 1.0;   // 1 = fully open, 0 = fully closed
    let blinkActive  = false;

    /**
     * Execute one blink animation. Pass doDouble=true for a natural double-blink.
     */
    function triggerBlink(doDouble = false) {
        if (blinkActive) return;
        blinkActive = true;

        const closeMs = 75;
        const holdMs  = 25;
        const openMs  = 110;

        function animateBlink(resolve) {
            const t0 = performance.now();
            function frame(now) {
                const e = now - t0;
                if (e < closeMs) {
                    blinkValue = 1 - e / closeMs;
                    requestAnimationFrame(frame);
                } else if (e < closeMs + holdMs) {
                    blinkValue = 0;
                    requestAnimationFrame(frame);
                } else if (e < closeMs + holdMs + openMs) {
                    blinkValue = (e - closeMs - holdMs) / openMs;
                    requestAnimationFrame(frame);
                } else {
                    blinkValue = 1;
                    resolve();
                }
            }
            requestAnimationFrame(frame);
        }

        // First blink always happens; double-blink adds a second after 80ms gap
        new Promise(resolve => animateBlink(resolve)).then(() => {
            if (doDouble) {
                setTimeout(() => {
                    new Promise(resolve => animateBlink(resolve)).then(() => {
                        blinkActive = false;
                    });
                }, 80);
            } else {
                blinkActive = false;
            }
        });
    }

    function scheduleNextBlink(preset) {
        if (blinkTimer) { clearTimeout(blinkTimer); blinkTimer = null; }
        if (!preset || !preset.blinkMs) return;
        const [minMs, maxMs] = preset.blinkMs;
        const delay = minMs + Math.random() * (maxMs - minMs);
        blinkTimer = setTimeout(() => {
            // 15% chance of a double-blink — very natural
            triggerBlink(Math.random() < 0.15);
            scheduleNextBlink(preset);
        }, delay);
    }

    // ── Saccadic Gaze Drift (idle only) ──────────────────────────────────────
    // Real human eyes make rapid micro-jumps (saccades) between fixation points.
    // We simulate this with distinct target positions held for random durations.

    let saccadeTarget = { x: 0, y: 0 };
    let saccadeTimer  = null;
    // Saccade speed multiplier (higher = faster jump to new position)
    let saccadeSpeed  = 1.0;
    // Current saccade lerped values
    let saccadeCur    = { x: 0, y: 0 };

    function scheduleSaccade() {
        if (saccadeTimer) clearTimeout(saccadeTimer);
        // Hold current fixation for 800ms – 2500ms (realistic dwell time)
        const holdMs = 800 + Math.random() * 1700;
        saccadeTimer = setTimeout(() => {
            if (currentState !== 'idle') {
                // Non-idle: park drift at center and stop scheduling
                saccadeTarget.x = 0;
                saccadeTarget.y = 0;
                return;
            }
            // Pick a new random gaze target within a natural range
            // Eyes look left/right more than up/down (natural head still)
            saccadeTarget.x = (Math.random() - 0.5) * 1.10; // Boosted range for visible left/right looking
            saccadeTarget.y = (Math.random() - 0.5) * 0.65; // Boosted range for up/down
            // Saccades are fast (near-instant) but we lerp for smooth canvas look
            saccadeSpeed = 12 + Math.random() * 8;  // faster than normal lerp

            // Occasionally blink just before or after a large saccade (realistic)
            if (!blinkActive && Math.random() < 0.25) {
                setTimeout(() => triggerBlink(), Math.random() * 150);
            }

            scheduleSaccade();
        }, holdMs);
    }

    // ── Draw one eye ─────────────────────────────────────────────────────────
    function drawEye(ctx, dpr, openness, pupX, pupY, irisR, pupR, ir, ig, ib, tilt) {
        const w = CW * dpr, h = CH * dpr;
        ctx.clearRect(0, 0, w, h);

        const cx = w / 2, cy = h / 2;
        const radius = (CW / 2 - 4) * dpr;

        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(tilt);

        // Final pupil position = emotion offset + saccade drift
        let finalPx = pupX + saccadeCur.x;
        let finalPy = pupY + saccadeCur.y;

        // Clamp so pupil stays within iris bounds
        const pLen = Math.sqrt(finalPx * finalPx + finalPy * finalPy);
        if (pLen > 1) { finalPx /= pLen; finalPy /= pLen; }

        // Organic lid-follows-pupil: looking down closes the eye slightly, looking up opens it
        const lidFollowOffset = finalPy * 0.15;
        const adjustedOpenness = Math.max(openness + lidFollowOffset, 0);

        // ── Eyelid clip (openness controls vertical scale of eye opening) ──
        ctx.save();
        ctx.beginPath();
        const ey = Math.max(radius * adjustedOpenness, 1);
        // Squish effect during blink: eye widens slightly as it closes
        const squish = 1 + (1 - adjustedOpenness) * 0.08;
        ctx.ellipse(0, 0, radius * squish, ey, 0, 0, Math.PI * 2);
        ctx.clip();

        // ── Sclera (eye white/glass) ──
        const isLight = document.body.classList.contains('light');
        
        // Shift gradient center up-left for a 3D light source effect
        const wGrad = ctx.createRadialGradient(-15 * dpr, -20 * dpr, 0, 0, 0, radius * 1.1);
        if (isLight) {
            wGrad.addColorStop(0,   'rgba(255, 255, 255, 1)');
            wGrad.addColorStop(0.5, 'rgba(235, 245, 255, 0.98)');
            wGrad.addColorStop(1,   'rgba(190, 215, 245, 0.90)');
        } else {
            // Dark mode: Deep, premium glowing glass sphere
            wGrad.addColorStop(0,   'rgba(240, 248, 255, 0.95)'); // bright highlight
            wGrad.addColorStop(0.3, 'rgba(180, 220, 255, 0.85)'); // mid-tone cyan-blue
            wGrad.addColorStop(0.7, 'rgba(40, 75, 120, 0.80)');   // deep shadowy rim
            wGrad.addColorStop(1,   'rgba(10, 20, 45, 0.95)');    // dark ambient edge
        }

        ctx.beginPath();
        ctx.arc(0, 0, radius, 0, Math.PI * 2);
        ctx.fillStyle = wGrad;
        ctx.fill();

        // Premium inner shadow for spherical depth
        ctx.save();
        ctx.beginPath();
        ctx.arc(0, 0, radius, 0, Math.PI * 2);
        ctx.clip();
        ctx.beginPath();
        ctx.arc(0, 0, radius, 0, Math.PI * 2);
        ctx.lineWidth = 14 * dpr;
        ctx.strokeStyle = isLight ? 'rgba(0,0,0,0.05)' : 'rgba(0,0,0,0.6)';
        ctx.shadowColor = isLight ? 'rgba(0,0,0,0.05)' : 'rgba(0,0,0,0.6)';
        ctx.shadowBlur = 8 * dpr;
        ctx.stroke();
        ctx.restore();

        // Inner border colored rim light
        ctx.beginPath();
        ctx.arc(0, 0, radius, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(${ir},${ig},${ib},${isLight ? 0.3 : 0.7})`;
        ctx.lineWidth   = 2.5 * dpr;
        ctx.stroke();

        // ── Iris ──
        const sIris  = irisR * dpr;
        const sPupil = pupR  * dpr;
        const maxOffset = radius - sIris - (4 * dpr);
        const absPx = finalPx * maxOffset;
        const absPy = finalPy * maxOffset;

        const iGrad = ctx.createRadialGradient(
            absPx - sIris * 0.3, absPy - sIris * 0.3, sIris * 0.1,
            absPx, absPy, sIris
        );
        iGrad.addColorStop(0,   `rgba(${Math.min(ir+80,255)},${Math.min(ig+80,255)},${Math.min(ib+80,255)},1)`);
        iGrad.addColorStop(0.5, `rgba(${ir},${ig},${ib},1)`);
        iGrad.addColorStop(1,   `rgba(${Math.max(ir-60,0)},${Math.max(ig-60,0)},${Math.max(ib-60,0)},1)`);

        ctx.beginPath();
        ctx.arc(absPx, absPy, sIris, 0, Math.PI * 2);
        ctx.fillStyle = iGrad;
        ctx.shadowColor = `rgba(${ir},${ig},${ib},0.6)`;
        ctx.shadowBlur  = 12 * dpr;
        ctx.fill();
        ctx.shadowBlur  = 0;

        // ── Pupil ──
        ctx.beginPath();
        ctx.arc(absPx, absPy, sPupil, 0, Math.PI * 2);
        ctx.fillStyle = '#050914';
        ctx.fill();

        // ── Highlights ──
        ctx.beginPath();
        ctx.arc(absPx + sIris * 0.35, absPy - sIris * 0.35, 5 * dpr, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(255,255,255,0.92)';
        ctx.fill();

        ctx.beginPath();
        ctx.arc(absPx - sIris * 0.25, absPy + sIris * 0.3, 2.5 * dpr, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(255,255,255,0.55)';
        ctx.fill();

        ctx.restore(); // undo clip
        ctx.restore(); // undo tilt
    }

    // ── Animation loop ────────────────────────────────────────────────────────
    let lastTs = 0;

    function tick(ts) {
        animId = requestAnimationFrame(tick);

        const dt  = Math.min((ts - lastTs) / 1000, 0.05);
        lastTs    = ts;

        const spd = 8;
        const t   = 1 - Math.exp(-spd * dt);

        // Saccade lerp — uses its own speed so gaze jumps feel snappy
        const st = 1 - Math.exp(-saccadeSpeed * dt);
        if (currentState === 'idle') {
            saccadeCur.x += (saccadeTarget.x - saccadeCur.x) * st;
            saccadeCur.y += (saccadeTarget.y - saccadeCur.y) * st;
        } else {
            // Smoothly park drift back to zero when not idle
            saccadeCur.x += (0 - saccadeCur.x) * t;
            saccadeCur.y += (0 - saccadeCur.y) * t;
        }

        // Main lerps
        cur.lOpen  += (tgt.lOpen  - cur.lOpen)  * t;
        cur.rOpen  += (tgt.rOpen  - cur.rOpen)  * t;
        cur.irisR  += (tgt.irisR  - cur.irisR)  * t;
        cur.pupilR += (tgt.pupilR - cur.pupilR) * t;
        cur.ir     += (tgt.ir     - cur.ir)     * t;
        cur.ig     += (tgt.ig     - cur.ig)     * t;
        cur.ib     += (tgt.ib     - cur.ib)     * t;
        cur.lTilt  += (tgt.lTilt  - cur.lTilt)  * t;
        cur.rTilt  += (tgt.rTilt  - cur.rTilt)  * t;
        cur.pupilX += (tgt.pupilX - cur.pupilX) * t;
        cur.pupilY += (tgt.pupilY - cur.pupilY) * t;

        // Micro-expressions: occasional tiny eyelid flutters in idle
        let twitch = 0;
        if (currentState === 'idle' && Math.random() < 0.015) {
            twitch = (Math.random() - 0.5) * 0.06;
        }

        // Speaking animations: vertical bounce + subtle pupil jitter (cognitive load)
        let speakBounce = 0;
        let speakJitterX = 0, speakJitterY = 0;
        if (currentState === 'speaking') {
            speakBounce = Math.sin(ts * 0.007) * 0.04;
            speakJitterX = (Math.random() - 0.5) * 0.03;
            speakJitterY = (Math.random() - 0.5) * 0.03;
        }

        // Pupil breathing (subtle constant dilation/constriction)
        const breathe = Math.sin(ts * 0.0015) * 0.8;

        const blink = blinkValue;
        const lOpen = Math.max((cur.lOpen + twitch) * blink + speakBounce, 0);
        const rOpen = Math.max((cur.rOpen - twitch) * blink + speakBounce, 0); // asymmetric twitch

        const dpr = window.devicePixelRatio || 1;

        // Use speak jitter but do NOT add saccadeCur here, it's added inside drawEye()
        const finalPx = cur.pupilX + speakJitterX;
        const finalPy = cur.pupilY + speakJitterY;

        drawEye(lCtx, dpr, lOpen, finalPx, finalPy, cur.irisR, cur.pupilR + breathe,
                Math.round(cur.ir), Math.round(cur.ig), Math.round(cur.ib), cur.lTilt);

        drawEye(rCtx, dpr, rOpen, finalPx, finalPy, cur.irisR, cur.pupilR + breathe,
                Math.round(cur.ir), Math.round(cur.ig), Math.round(cur.ib), cur.rTilt);
    }

    // ── Public API ────────────────────────────────────────────────────────────
    function init() {
        lCanvas = document.getElementById('eye-canvas-left');
        rCanvas = document.getElementById('eye-canvas-right');
        if (!lCanvas || !rCanvas) return;

        const dpr = window.devicePixelRatio || 1;
        [lCanvas, rCanvas].forEach(c => {
            c.width  = CW * dpr;
            c.height = CH * dpr;
            c.style.width  = CW + 'px';
            c.style.height = CH + 'px';
        });

        lCtx = lCanvas.getContext('2d', { alpha: true });
        rCtx = rCanvas.getContext('2d', { alpha: true });

        setState('idle');

        lastTs = performance.now();
        animId = requestAnimationFrame(tick);
    }

    function setState(stateName) {
        const prev = currentState;
        currentState = stateName;
        const p = PRESETS[stateName] || PRESETS.idle;

        tgt.lOpen  = p.lOpen;
        tgt.rOpen  = p.rOpen;
        tgt.pupilX = p.pupilX;
        tgt.pupilY = p.pupilY;
        tgt.irisR  = p.irisR;
        tgt.pupilR = p.pupilR;
        tgt.ir     = p.ir;
        tgt.ig     = p.ig;
        tgt.ib     = p.ib;
        tgt.lTilt  = p.lTilt;
        tgt.rTilt  = p.rTilt;

        scheduleNextBlink(p);

        // Start or stop saccade scheduling based on whether this state allows drift
        if (p.allowDrift) {
            // Entering idle — kick off saccade system
            if (prev !== 'idle') {
                saccadeTarget.x = 0;
                saccadeTarget.y = 0;
                scheduleSaccade();
            }
        } else {
            // Entering focused state — cancel saccade timer, snap drift toward zero
            if (saccadeTimer) { clearTimeout(saccadeTimer); saccadeTimer = null; }
            // saccadeCur will lerp to zero automatically in tick()
        }

        // When switching TO listening: blink once to signal "attention engaged"
        if (stateName === 'listening' && prev !== 'listening') {
            setTimeout(() => triggerBlink(), 120);
        }
    }

    return { init, setState, blink: triggerBlink };

})();

// Auto-init
document.addEventListener('DOMContentLoaded', () => EyeRenderer.init());
