/**
 * orb-renderer.js — Alive Cinematic Fluid Orb v2
 * Plasma cores, breathing particles, chromatic shimmer, reactive waveforms.
 */
'use strict';

const OrbRenderer = (() => {
    let canvas, ctx;
    let animId = null;
    let state = 'idle';
    let time = 0;
    let intensity = 0, tI = 0;
    let vol = 0, sV = 0;
    let dpr = 1;
    let cx, cy, R;
    let lastT = 0;
    let isLight = false;

    // ── Noise helpers ──
    const S = (x, y) => { const n = Math.sin(x * 127.1 + y * 311.7) * 43758.5453; return n - Math.floor(n); };
    function sn(x, y) {
        const ix = Math.floor(x), iy = Math.floor(y);
        const fx = x - ix, fy = y - iy;
        const u = fx * fx * (3 - 2 * fx), v = fy * fy * (3 - 2 * fy);
        return S(ix,iy)*(1-u)*(1-v)+S(ix+1,iy)*u*(1-v)+S(ix,iy+1)*(1-u)*v+S(ix+1,iy+1)*u*v;
    }
    function hsl(h, s, l, a) { return `hsla(${h},${s}%,${l}%,${a})`; }

    function init(el) {
        canvas = el; ctx = canvas.getContext('2d');
        dpr = Math.min(window.devicePixelRatio || 1, 2);
        resize();
        window.addEventListener('resize', resize);
        // Watch for theme changes
        const mo = new MutationObserver(() => { isLight = document.body.classList.contains('light'); });
        mo.observe(document.body, { attributes: true, attributeFilter: ['class'] });
        isLight = document.body.classList.contains('light');
        start();
    }

    function resize() {
        const p = canvas.parentElement; if (!p) return;
        const s = p.offsetWidth || 96;
        canvas.width = s * dpr; canvas.height = s * dpr;
        canvas.style.width = s + 'px'; canvas.style.height = s + 'px';
        cx = canvas.width / 2; cy = canvas.height / 2; R = cx;
    }

    function setState(s) {
        state = s;
        tI = ({ idle:0.90, listening:1, speaking:1, thinking:0.85, error:0.65 })[s] || 0.7;
    }
    function setVolume(v) { vol = Math.min(v, 1); }

    function start() {
        if (animId) return; lastT = performance.now();
        (function loop(now) {
            const dt = Math.min((now - lastT) / 1000, 0.05);
            lastT = now; time += dt;
            intensity += (tI - intensity) * 5 * dt;
            sV += (vol - sV) * 14 * dt;
            draw(); animId = requestAnimationFrame(loop);
        })(performance.now());
    }
    function stop() { if (animId) { cancelAnimationFrame(animId); animId = null; } }

    // ── Blob helper ──
    function blob(x, y, r, h, s, l, alpha) {
        const g = ctx.createRadialGradient(x, y, 0, x, y, r);
        g.addColorStop(0,    hsl(h, s, l, alpha));
        g.addColorStop(0.40, hsl(h, s, l - 4, alpha * 0.75));
        g.addColorStop(0.75, hsl(h, s - 6, l - 12, alpha * 0.28));
        g.addColorStop(1,    'rgba(0,0,0,0)');
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
    }

    // ── Plasma ring (chromatic shimmer around edge) ──
    function plasmaRing(t, hueShift, alpha, thickness) {
        const segs = 120;
        ctx.save();
        for (let i = 0; i < segs; i++) {
            const a  = (i / segs) * Math.PI * 2;
            const n  = sn(Math.cos(a)*2.5 + t*0.4, Math.sin(a)*2.5 + t*0.3);
            const w  = n * R * 0.08;
            const rx = cx + Math.cos(a) * (R * 0.82 + w);
            const ry = cy + Math.sin(a) * (R * 0.82 + w);
            const hue = (hueShift + i * (360 / segs)) % 360;
            ctx.fillStyle = hsl(hue, 75, 65, alpha * intensity);
            ctx.beginPath(); ctx.arc(rx, ry, thickness * dpr, 0, Math.PI * 2); ctx.fill();
        }
        ctx.restore();
    }

    // ── Floating micro-particles ──
    function floatingParticles(t, count, hueBase, baseAlpha) {
        for (let k = 0; k < count; k++) {
            const pa = t * (0.9 + k * 0.12) + k * 0.628;
            const orbit = R * (0.20 + sn(t*0.3+k, k*1.5) * 0.42);
            const px = cx + Math.cos(pa) * orbit;
            const py = cy + Math.sin(pa) * orbit;
            const ps = (0.9 + Math.sin(t * 4 + k * 1.8) * 0.5) * dpr;
            const po = (baseAlpha + Math.sin(t * 3.2 + k * 1.1) * 0.2) * intensity;
            ctx.fillStyle = hsl((hueBase + k * 30) % 360, 80, 75, po);
            ctx.beginPath(); ctx.arc(px, py, ps, 0, Math.PI * 2); ctx.fill();
        }
    }

    function draw() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.save();
        ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.clip();
        ctx.globalCompositeOperation = 'lighter';
        const fn = { idle: drawIdle, listening: drawListening, speaking: drawSpeaking, thinking: drawThinking, error: drawError };
        (fn[state] || fn.idle)();
        ctx.globalCompositeOperation = 'source-over';
        ctx.restore();
    }

    // ════════════════ IDLE — Alive aurora, plasma shimmer, breathes ════════════
    function drawIdle() {
        const t = time * 0.12;
        const breathe = Math.sin(time * 0.9) * 0.06 + 1;
        // Light vs dark palette
        const defs = isLight
            ? [[240,75,62,0.28],[270,65,58,0.22],[200,70,55,0.20],[310,55,55,0.14]]
            : [[220,65,55,0.28],[270,60,52,0.22],[190,65,50,0.20],[310,48,50,0.14]];
        for (let i = 0; i < defs.length; i++) {
            const [h, s, l, base] = defs[i];
            const angle = t + i * 1.571;
            const x = cx + Math.cos(angle) * R * 0.24;
            const y = cy + Math.sin(angle) * R * 0.20;
            blob(x, y, R * (0.78 + i * 0.06) * breathe, h, s, l, base * intensity);
        }
        // Subtle plasma ring (alive feel)
        plasmaRing(time * 0.5, (time * 15) % 360, 0.06, 1.2);
        // Inner gentle core glow
        const cR = R * 0.22 * breathe;
        const cG = ctx.createRadialGradient(cx, cy, 0, cx, cy, cR);
        cG.addColorStop(0, hsl(220, 70, 80, 0.18 * intensity));
        cG.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = cG;
        ctx.beginPath(); ctx.arc(cx, cy, cR, 0, Math.PI * 2); ctx.fill();
        // Tiny drifting particles
        floatingParticles(time * 0.6, 8, (time * 10) % 360, 0.12);
    }

    // ════════════════ LISTENING — Rich swirling aurora, reactive waveform ════
    function drawListening() {
        const t = time;
        const br = Math.sin(t * 1.4) * 0.05 + 1;
        const vB = 1 + sV * 0.8;
        const defs = isLight
            ? [[210,85,55,0.52],[240,80,52,0.44],[270,75,50,0.36],[185,80,48,0.30],[250,70,60,0.22],[300,60,52,0.16]]
            : [[205,80,62,0.52],[230,75,58,0.44],[260,70,55,0.36],[185,75,52,0.30],[240,65,65,0.22],[300,50,55,0.16]];

        for (let i = 0; i < defs.length; i++) {
            const [h, s, l, base] = defs[i];
            const hue = h + Math.sin(t * 0.35 + i * 2) * 14;
            const speed = 0.24 + i * 0.05;
            const angle = t * speed + i * (Math.PI * 2 / defs.length);
            const nX = sn(t * 0.2 + i * 5, i * 3) * R * 0.18;
            const nY = sn(i * 4, t * 0.2 + i * 2) * R * 0.15;
            const x = cx + Math.cos(angle) * R * 0.28 * vB + nX;
            const y = cy + Math.sin(angle) * R * 0.22 * vB + nY;
            const r = R * (0.58 + i * 0.04) * br * vB;
            blob(x, y, r, hue, s, l, base * intensity);
        }

        // Bright core
        const cR = R * (0.30 + sV * 0.22) * br;
        const cG = ctx.createRadialGradient(cx, cy, 0, cx, cy, cR);
        const cA = (0.32 + sV * 0.28) * intensity;
        cG.addColorStop(0, hsl(210, 85, 85, cA));
        cG.addColorStop(0.4, hsl(225, 75, 72, cA * 0.55));
        cG.addColorStop(0.8, hsl(235, 65, 60, cA * 0.15));
        cG.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = cG; ctx.beginPath(); ctx.arc(cx, cy, cR, 0, Math.PI * 2); ctx.fill();

        // Volume-reactive waveform ring
        const segs = 96, ringR = R * 0.80;
        const wA = R * (0.028 + sV * 0.07);
        ctx.beginPath();
        for (let i = 0; i <= segs; i++) {
            const a = (i / segs) * Math.PI * 2;
            const w = Math.sin(a * 6 + t * 4) * wA + Math.sin(a * 3 - t * 2.2) * wA * 0.5;
            const px = cx + Math.cos(a) * (ringR + w);
            const py = cy + Math.sin(a) * (ringR + w);
            i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
        }
        ctx.closePath();
        ctx.strokeStyle = hsl(215, 75, 75, (0.28 + sV * 0.35) * intensity);
        ctx.lineWidth = (1.4 + sV * 2) * dpr; ctx.stroke();

        // Chromatic plasma ring
        plasmaRing(t, (t * 25) % 360, 0.10, 1.4);
        floatingParticles(t, 10, 210, 0.20);
    }

    // ════════════════ SPEAKING — Rainbow plasma, sparkles, alive ════════════
    function drawSpeaking() {
        const t = time;
        const pulse = Math.sin(t * 3.5) * 0.04 + 1;
        const vB = 1 + sV * 0.6;
        const hueBase = (t * 35) % 360;

        // 10 vivid rainbow blobs
        const count = 10;
        for (let i = 0; i < count; i++) {
            const hue = (hueBase + i * (360 / count)) % 360;
            const speed = 0.6 + i * 0.12;
            const angle = t * speed + i * (Math.PI * 2 / count);
            const orbitR = R * (0.22 + sn(t * 0.25 + i * 3, i) * 0.14) * vB;
            const x = cx + Math.cos(angle) * orbitR;
            const y = cy + Math.sin(angle) * orbitR;
            const bR = R * (0.55 + sn(i * 2, t * 0.35) * 0.09) * pulse;
            blob(x, y, bR, hue, 75, 58, (0.38 - i * 0.012) * intensity);
        }

        // Hot shifting center
        const cR = R * (0.32 + sV * 0.14) * pulse;
        const cH = (hueBase + 180) % 360;
        const cG = ctx.createRadialGradient(cx, cy, 0, cx, cy, cR);
        const cA = (0.28 + sV * 0.22) * intensity;
        cG.addColorStop(0, hsl(cH, 70, 82, cA));
        cG.addColorStop(0.3, hsl(cH, 60, 68, cA * 0.4));
        cG.addColorStop(0.7, hsl(cH, 50, 58, cA * 0.08));
        cG.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = cG; ctx.beginPath(); ctx.arc(cx, cy, cR, 0, Math.PI * 2); ctx.fill();

        // Full chromatic plasma ring
        plasmaRing(t * 1.2, hueBase, 0.18, 1.8);

        // Noise-distorted outer aurora
        const segs = 100, ringR = R * 0.76;
        ctx.beginPath();
        for (let i = 0; i <= segs; i++) {
            const a = (i / segs) * Math.PI * 2;
            const n1 = sn(Math.cos(a)*2.5 + t*0.5, Math.sin(a)*2.5 + t*0.4);
            const n2 = sn(Math.cos(a)*3.5 - t*0.35, Math.sin(a)*3.5 + t*0.25);
            const w = (n1 * 0.06 + n2 * 0.03) * R * vB;
            const px = cx + Math.cos(a) * (ringR + w);
            const py = cy + Math.sin(a) * (ringR + w);
            i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
        }
        ctx.closePath();
        ctx.strokeStyle = hsl((hueBase + 90) % 360, 65, 68, 0.30 * intensity);
        ctx.lineWidth = 2 * dpr; ctx.stroke();

        // Bright sparkles
        floatingParticles(t, 16, hueBase, 0.40);
    }

    // ════════════════ THINKING — Orbiting arcs with plasma pulse ════════════
    function drawThinking() {
        const t = time;
        const breathe = Math.sin(t * 2.0) * 0.08 + 1;

        // Center glow
        const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 0.68 * breathe);
        g.addColorStop(0, hsl(230, 65, 62, 0.22 * intensity));
        g.addColorStop(0.45, hsl(250, 55, 55, 0.08 * intensity));
        g.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, R * 0.68 * breathe, 0, Math.PI * 2); ctx.fill();

        // 4 orbiting arcs instead of 3
        for (let i = 0; i < 4; i++) {
            const r = R * (0.46 + i * 0.12);
            const sa = t * (2.8 - i * 0.45) + i * 1.571;
            ctx.strokeStyle = hsl(225 + i * 18, 60, 65, (0.30 - i * 0.04) * intensity);
            ctx.lineWidth = (3.0 - i * 0.5) * dpr; ctx.lineCap = 'round';
            ctx.beginPath(); ctx.arc(cx, cy, r, sa, sa + Math.PI * 0.50); ctx.stroke();
        }

        // Subtle plasma ring
        plasmaRing(t * 0.7, (t * 20) % 360, 0.07, 1.2);
        floatingParticles(t * 0.8, 6, 230, 0.15);
    }

    // ════════════════ ERROR — Red pulse with warning ring ════════════
    function drawError() {
        const p = Math.sin(time * 2.5) * 0.14 + 0.86;
        const r = R * 0.72 * p;
        const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
        g.addColorStop(0, hsl(5, 65, 55, 0.26 * intensity));
        g.addColorStop(0.4, hsl(10, 55, 48, 0.10 * intensity));
        g.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill();

        // Pulsing red ring
        ctx.strokeStyle = hsl(5, 65, 55, (0.20 + Math.sin(time * 2.5) * 0.10) * intensity);
        ctx.lineWidth = 1.5 * dpr;
        ctx.beginPath(); ctx.arc(cx, cy, R * 0.80 * p, 0, Math.PI * 2); ctx.stroke();
    }

    return { init, setState, setVolume, stop, start };
})();
