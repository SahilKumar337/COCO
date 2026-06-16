"""
server.py — WALL-E AI FastAPI Server
Web entry point. Delegates all AI logic to pipelines.
Serves the web UI and handles WebSocket connections for
real-time bidirectional audio streaming with Gemini Live.

Usage:
    python server.py
    # Then open http://localhost:8000 in your browser

Created by K.Astra and its members.
"""

import asyncio
import hashlib
import json
import os
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# ── Bootstrap ─────────────────────────────────────────────────────────────────
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    # Fix: Windows ProactorEventLoop has a known DNS resolver bug where
    # getaddrinfo fails after a WebSocket abnormal closure (1006).
    # SelectorEventLoop is stable and fully supports asyncio + websockets.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from core.config import settings
from core.logger import get_logger
from core.registry import registry
from pipelines.gemini_pipeline import WalleSession
from pipelines.tool_pipeline import update_session_location

log = get_logger("server")

# ── In-memory user settings store ─────────────────────────────────────────────
# Loaded from .env on startup; updated via POST /api/auth/settings
_USER_SETTINGS: dict = {
    "name":       settings.default_user_name,
    "ai_voice":   settings.default_voice,
    "ai_persona": settings.default_persona,
}


def _make_user() -> dict:
    return {
        "id":         1,
        "name":       _USER_SETTINGS["name"],
        "email":      "user@walle.ai",
        "ai_voice":   _USER_SETTINGS["ai_voice"],
        "ai_persona": _USER_SETTINGS["ai_persona"],
    }


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(f"WALL-E AI server starting on port {settings.port}")

    # Auto-open browser in local dev mode
    if not settings.is_production:
        def _open():
            time.sleep(1.2)
            webbrowser.open(f"http://localhost:{settings.port}")
        threading.Thread(target=_open, daemon=True).start()

    yield

    log.info("Shutting down WALL-E AI server.")
    await registry.stop_all()


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="WALL-E AI",
    description="Professional voice-controlled AI assistant by K.Astra",
    version="2.0.0",
    lifespan=lifespan,
)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


# ── JS: content-hash ETags, strict no-cache ───────────────────────────────────
@app.get("/static/js/{filename:path}")
async def serve_js(filename: str, request: Request):
    """Serve JS files with SHA-256 ETags and no-store headers."""
    file_path = os.path.join(STATIC_DIR, "js", filename)
    if not os.path.isfile(file_path):
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "not found"}, status_code=404)
    file_bytes = open(file_path, "rb").read()
    etag = '"' + hashlib.sha256(file_bytes).hexdigest()[:16] + '"'
    return Response(
        content=file_bytes,
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma":        "no-cache",
            "ETag":          etag,
        },
    )


# All other statics: normal caching (CSS, images, fonts)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── Noise suppression ─────────────────────────────────────────────────────────
@app.get("/hybridaction/{path:path}")
@app.post("/hybridaction/{path:path}")
async def silence_tracker():
    return Response(status_code=204)


# ── PWA ───────────────────────────────────────────────────────────────────────
@app.get("/manifest.json")
async def manifest():
    return FileResponse(os.path.join(STATIC_DIR, "manifest.json"))


@app.get("/sw.js")
async def service_worker():
    return FileResponse(os.path.join(STATIC_DIR, "sw.js"))


@app.get("/favicon.ico")
async def favicon():
    for candidate in ["walle-logo.png", "sifra-logo.png", "coco-logo.png"]:
        p = os.path.join(STATIC_DIR, "assets", candidate)
        if os.path.exists(p):
            return FileResponse(p, media_type="image/png")
    return Response(status_code=204)


# ── Pages ─────────────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return FileResponse(
        os.path.join(STATIC_DIR, "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
    )


@app.get("/login")
async def login_page():
    return RedirectResponse(url="/")


# ── Auth API ──────────────────────────────────────────────────────────────────
@app.get("/api/auth/me")
async def auth_me():
    """Returns the current user profile."""
    return _make_user()


@app.post("/api/auth/settings")
async def auth_settings(request: Request):
    """Save voice/persona settings into the in-memory store."""
    global _USER_SETTINGS
    try:
        body = await request.json()
    except Exception:
        body = {}
    if body.get("ai_voice"):
        _USER_SETTINGS["ai_voice"] = body["ai_voice"]
    if body.get("ai_persona"):
        _USER_SETTINGS["ai_persona"] = body["ai_persona"]
    if body.get("name"):
        _USER_SETTINGS["name"] = body["name"]
    log.info(
        f"Settings saved: voice={_USER_SETTINGS['ai_voice']} "
        f"persona={_USER_SETTINGS['ai_persona'][:40]}"
    )
    return {"status": "success", "settings": _USER_SETTINGS}


@app.post("/api/auth/logout")
async def auth_logout():
    return {"status": "success"}


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    """Aggregated health check across all registered pipelines."""
    pipeline_health = await registry.health_all()
    return {
        "service":        "WALL-E AI",
        "version":        "2.0.0",
        "gemini_key_set": bool(settings.gemini_api_key),
        **pipeline_health,
    }


# ── WebSocket — Real-time audio bridge ───────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    user = _make_user()
    log.info(f"Client connected: {user['name']} | voice={user['ai_voice']}")

    session: WalleSession | None = None
    session_task: asyncio.Task | None = None

    async def _start_session():
        nonlocal session, session_task
        session = WalleSession(mode="web", websocket=ws, user=_make_user())
        session_task = asyncio.create_task(session.run())

    try:
        await _start_session()

        while True:
            message = await ws.receive()

            if message["type"] == "websocket.receive":
                if "bytes" in message and message["bytes"]:
                    payload = message["bytes"]
                    # Security: drop oversized payloads (DDoS guard)
                    if len(payload) > settings.ws_max_payload_bytes:
                        log.warning("Dropped oversized WebSocket payload.")
                        continue
                    try:
                        session.audio_queue.put_nowait(payload)
                    except asyncio.QueueFull:
                        try:
                            session.audio_queue.get_nowait()
                            session.audio_queue.put_nowait(payload)
                        except Exception:
                            pass

                elif "text" in message and message["text"]:
                    try:
                        cmd = json.loads(message["text"])
                        action = await _handle_command(session, cmd)
                        if action == "restart":
                            session.stop()
                            if session_task and not session_task.done():
                                session_task.cancel()
                                try:
                                    await session_task
                                except asyncio.CancelledError:
                                    pass
                            await _start_session()
                    except json.JSONDecodeError:
                        pass

            elif message["type"] == "websocket.disconnect":
                break

    except WebSocketDisconnect:
        log.info("Client disconnected.")
    except Exception as e:
        log.error(f"WebSocket error: {e}")
    finally:
        if session:
            session.stop()
        if session_task and not session_task.done():
            session_task.cancel()
            try:
                await session_task
            except asyncio.CancelledError:
                pass


async def _handle_command(session: WalleSession, cmd: dict) -> str | None:
    """Route JSON commands from the browser client."""
    cmd_type = cmd.get("type")

    if cmd_type == "set_user":
        session.current_user = cmd.get("name", "Unknown")

    elif cmd_type == "listening_state":
        session.client_is_listening = bool(cmd.get("active", False))

    elif cmd_type == "settings_changed":
        new_user = _make_user()
        session.user = new_user
        log.info(f"Settings applied: voice={new_user['ai_voice']}")
        return "restart"

    elif cmd_type == "stop":
        session.stop()

    elif cmd_type == "ping":
        await session._send("pong", {"time": cmd.get("time")})

    elif cmd_type == "pong":
        pass  # heartbeat acknowledged

    elif cmd_type == "speech_stop":
        await session.trigger_response()

    elif cmd_type == "interrupt":
        await session.interrupt()

    elif cmd_type == "location_update":
        # Browser sent geolocation data (reverse-geocoded city/country + coords)
        loc = cmd.get("location")
        if loc and isinstance(loc, dict):
            update_session_location(loc)

    return None


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not settings.gemini_api_key:
        print("=" * 55)
        print("  ERROR: GEMINI_API_KEY environment variable not set!")
        print()
        print("  Set it with:")
        print("    set GEMINI_API_KEY=your_api_key_here")
        print()
        print("  Get a key at: https://aistudio.google.com/apikey")
        print("=" * 55)
        sys.exit(1)

    print("=" * 55)
    print("  WALL-E AI  v2.0  — Voice Assistant Server")
    print("  Created by K.Astra and its members")
    print(f"  -> http://localhost:{settings.port}")
    print("  Press Ctrl+C to stop")
    print("=" * 55)

    uvicorn.run(
        "server:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
        # Use asyncio selector loop on Windows (fixes DNS getaddrinfo bug on reconnect)
        loop="asyncio",
        ws_ping_interval=20,
        ws_ping_timeout=30,
        timeout_keep_alive=60,
    )
