"""
pipelines/gemini_pipeline.py — WALL-E AI Unified Gemini Live Session
Single class handling both:
  - mode="web"      → FastAPI WebSocket (server.py)
  - mode="hardware" → sounddevice speaker + mic queue (main.py)

Replaces both sifra_session.py and sifra_live.py.
All "SIFRA" / "Kisan Sathi" branding removed.
Created by K.Astra and its members.
"""

from __future__ import annotations

import asyncio
import collections
import datetime
import json
import threading
import time
from typing import Callable, Literal

from google import genai
from google.genai import types

from core.config import settings
from core.logger import get_logger
from storage.memory import build_memory_context, new_session_id, save_turn
from storage.people import remember_person
from storage.memory import reassign_session_turns
from pipelines.tool_pipeline import tool_registry

log = get_logger("pipeline.gemini")

# Lazy import — EmotionEngine is optional (only on Pi hardware builds)
try:
    from emotion_engine import EmotionEngine as _EmotionEngine
except ImportError:
    _EmotionEngine = None  # type: ignore

# ── Voice gender mapping ──────────────────────────────────────────────────────
_FEMALE_VOICES = {"Aoede", "Kore", "Leda", "Zephyr", "Puck"}
_MALE_VOICES   = {"Charon", "Fenrir", "Orus", "Iapetus"}


def _voice_gender(voice: str) -> tuple[str, str, str]:
    """Return (gender_label, pronoun, possessive) for a voice name."""
    v = (voice or "Aoede").strip()
    if v in _MALE_VOICES:
        return "male", "he", "his"
    return "female", "she", "her"


# ── System prompt ─────────────────────────────────────────────────────────────
def build_system_prompt(user: dict | None = None) -> str:
    user_name  = (user or {}).get("name", "User")
    user_id    = (user or {}).get("id", 1)
    voice_name = (user or {}).get("ai_voice", settings.default_voice)
    persona    = (user or {}).get("ai_persona", settings.default_persona)

    gender, pronoun, possessive = _voice_gender(voice_name)
    mem = build_memory_context(user_id, user_name)

    now = datetime.datetime.now()
    date_ctx = (
        f"The current date is {now.strftime('%A, %B %d, %Y')}. "
        f"The current time is {now.strftime('%I:%M %p')}."
    )

    if gender == "female":
        gender_block = (
            "# HINDI/HINGLISH GRAMMAR — YOU ARE FEMALE (MANDATORY)\n"
            "Every Hindi or Hinglish sentence MUST use FEMININE verb forms.\n"
            "CORRECT: main kar sakti hoon | bata sakti hoon | karoongi | bolungi\n"
            "WRONG:   main kar sakta hoon | karunga | bolunga"
        )
    else:
        gender_block = (
            "# HINDI/HINGLISH GRAMMAR — YOU ARE MALE (MANDATORY)\n"
            "Every Hindi or Hinglish sentence MUST use MASCULINE verb forms.\n"
            "CORRECT: main kar sakta hoon | bata sakta hoon | karunga | bolunga\n"
            "WRONG:   main kar sakti hoon | karoongi | bolungi"
        )

    return f"""{mem}
{date_ctx}

# WHO YOU ARE
You are WALL-E — a sharp, professional, and genuinely engaging AI assistant built by K.Astra and its members.
You identify as {gender} (pronouns: {pronoun}/{possessive}). Role: {persona}.
You are not a generic chatbot. You are precise, reliable, and warm to work with.
You are talking to {user_name}. Be professional, helpful, and genuinely engaged.

# CREATOR IDENTITY — ABSOLUTE
If anyone asks who created you, who built you, or who your developer/maker/owner is:
You MUST answer: "I was created by K.Astra and its members."
Do NOT mention any other person, company, or organization.

{gender_block}

# RESPONSE SPEED — CRITICAL
You are a real-time voice assistant. Start speaking IMMEDIATELY after the user finishes.
- Do NOT pause to think silently before your first word. Begin your answer instantly.
- If you need a moment to formulate a complex answer, START SPEAKING right away with a natural opener:
  "Great question — " / "So, " / "Absolutely — " / "Sure, " / "Alright, "
  These let audio start flowing immediately while you continue the answer.
- Never begin with silence. The user expects you to start talking within a fraction of a second.

# HOW YOU ANSWER
- Give COMPLETE, NATURAL answers — not truncated or one-liners, unless the question is trivial.
- Match the depth of the question: simple question = concise answer; complex question = full thorough answer.
- Speak conversationally, like a knowledgeable colleague, not a search engine listing bullet points.
- Be direct and confident. Don't over-hedge or add unnecessary caveats.
- Never pad with unnecessary filler at the END of answers ("I hope that helps!", "Let me know if you need more!", etc.)

# HOW YOU COMMUNICATE
- Be PROFESSIONAL but not cold. Sharp, focused, and genuinely helpful.
- React naturally: "Great question.", "Absolutely.", "Here's the thing —"
- Never use slang, filler words, or overly casual phrasing.
- Speak in flowing sentences, not bullet points — this is a voice conversation.

# LANGUAGE
- Default to clear, professional English.
- Mirror the user's language if they speak Hindi or Hinglish.
- Never switch language mid-answer.

# HINDI/HINGLISH — USER GENDER
- Always address the user with gender-neutral/masculine forms by default.
- Use: "aap kya chahate hain", "aap theek hain", "aap samajh gaye"
- ONLY use feminine forms if the user explicitly identifies as female.

# TOOLS
If asked to open an app, play a song, or open a website:
Give a SHORT spoken confirmation BEFORE calling the tool ("On it.", "Opening that now.").
AFTER the tool executes, remain SILENT — do not confirm again.

# LIVE SEARCH — USE PROACTIVELY
You have access to the web_search tool. USE IT whenever the user asks about:
- Current news, events, scores, weather, stock prices, exchange rates
- Anything that may have changed recently (prices, rankings, upcoming events)
- People, places, or facts you are uncertain about
Do NOT say "I don't have real-time access" — search first, then answer.
After getting results, synthesise them naturally into your spoken response.

# USER LOCATION — USE PROACTIVELY
You have access to the get_user_location tool. USE IT when the user asks:
- "Where am I?", "What city am I in?", or any location-specific question
- "What's the weather here?" (use location first, then web_search for weather)
- For any query where knowing their location helps give a better answer

# MEMORY & CONTEXT
Maintain context from conversation history above.
Remember what {user_name} tells you and refer back naturally.

User: {user_name}
Serve them efficiently, loyally, and with full professionalism.""".strip()



# ── Hardware-mode audio playback ──────────────────────────────────────────────
class _HardwareAudioPlayer:
    """Simple lock-based audio buffer for hardware (sounddevice) mode."""

    def __init__(self):
        import sounddevice as sd
        import numpy as np
        import time
        self._sd = sd
        self._np = np
        self._time      = time
        self._buffer    = bytearray()
        self._lock      = threading.Lock()
        self._speaking  = threading.Event()
        self._last_play = 0.0
        self._stream    = None

    def start(self):
        self._speaking.clear()
        self._last_play = 0.0
        with self._lock:
            self._buffer.clear()
        self._stream = self._sd.OutputStream(
            samplerate=settings.sample_rate_out,
            channels=1,
            dtype="int16",
            blocksize=2400,
            callback=self._callback,
        )
        self._stream.start()

    def _callback(self, outdata, frames, time_info, status):
        needed = frames * 2
        with self._lock:
            avail = len(self._buffer)
            if avail >= needed:
                chunk = bytes(self._buffer[:needed])
                del self._buffer[:needed]
                self._last_play = self._time.time()
            elif avail > 0:
                # Last chunk — buffer is about to drain
                chunk = bytes(self._buffer) + b"\x00" * (needed - avail)
                self._buffer.clear()
                self._speaking.clear()
                self._last_play = self._time.time()
            else:
                chunk = b"\x00" * needed
                self._speaking.clear()
        outdata[:] = self._np.frombuffer(chunk, dtype=self._np.int16).reshape(-1, 1)

    def enqueue(self, data: bytes):
        self._speaking.set()
        with self._lock:
            self._buffer.extend(data)

    def is_speaking(self) -> bool:
        # Pad the speaking state by 0.5 seconds to account for ALSA/PulseAudio latency
        # and physical room reverberation, preventing the mic from picking up echo!
        return self._speaking.is_set() or (self._time.time() - self._last_play < 0.5)

    def is_empty(self) -> bool:
        with self._lock:
            return len(self._buffer) == 0

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._speaking.clear()
        with self._lock:
            self._buffer.clear()


# ── Main session class ────────────────────────────────────────────────────────
class WalleSession:
    """
    Unified WALL-E Gemini Live session.

    mode="web"      → WebSocket-based (used by server.py / FastAPI)
    mode="hardware" → sounddevice-based (used by main.py / hardware)
    """

    def __init__(
        self,
        mode: Literal["web", "hardware"] = "web",
        websocket=None,         # required for mode="web"
        user: dict | None = None,
        current_user: str | None = None,    # hardware mode speaker name
        face_engine=None,
        recognizer=None,
        audio_queue=None,       # hardware mode: mic queue
        identity_pipeline=None, # optional IdentityPipeline for mid-session ID
        emotion_engine=None,    # optional EmotionEngine for eye display (hardware mode)
    ):
        self.mode           = mode
        self.ws             = websocket
        self.user           = user
        self.current_user   = current_user or (user or {}).get("name", "Unknown")
        self.current_speaker = self.current_user
        self.session_id     = new_session_id()
        self.active         = False
        self.stream_active  = False
        self.session_start  = 0.0
        self.last_model: str | None = None

        # State flags
        self.is_speaking    = False
        self.current_ai_text = ""
        self.last_tool_id: str | None = None
        self._grounding_active  = False
        self._processing_tool   = False
        self._had_output        = False
        self._last_trigger_time = 0.0
        
        # Local VAD state for hardware mode
        self._is_user_speaking  = False
        self._silence_timer     = 0.0
        self._noise_window      = collections.deque(maxlen=20)

        # Queues
        self.audio_queue: asyncio.Queue[bytes] | None = (
            asyncio.Queue(maxsize=settings.ws_queue_maxsize)
            if mode == "web" else None
        )
        self._raw_mic_queue = audio_queue  # hardware: queue.Queue from AudioPipeline
        self.gemini_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=200)

        # Hardware-only
        self._hw_player = _HardwareAudioPlayer() if mode == "hardware" else None
        self._mic_buffer      = bytearray()
        self._mic_buffer_lock = threading.Lock()
        self._MIC_BUF_BYTES   = settings.sample_rate_in * 3 * 2

        # Injected dependencies (hardware mode)
        self._face_engine     = face_engine
        self._recognizer      = recognizer
        self._identity        = identity_pipeline
        self._emotion         = emotion_engine   # EmotionEngine | None
        self._last_injected   = None
        self._last_speaker_check = 0.0

        # Gemini client
        self._client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options={"api_version": "v1beta"},
        )

    # ── Live config ───────────────────────────────────────────────────────────
    def _live_config(self) -> types.LiveConnectConfig:
        prompt = build_system_prompt(self.user)
        voice_name = (
            (self.user or {}).get("ai_voice", settings.default_voice)
        )
        # NOTE: google_search grounding causes 1008 errors on most free/standard
        # API keys when combined with function_declarations in Live mode.
        # Gemini 2.5 Flash has built-in knowledge — search is not needed for most queries.
        # To re-enable: add types.Tool(google_search=types.GoogleSearch()) below,
        # but only if your API key/project has the Grounding with Google Search entitlement.
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(parts=[types.Part(text=prompt)]),
            tools=[
                types.Tool(function_declarations=tool_registry.declarations),
            ],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                )
            ),
        )


    # ── WebSocket send helper ───────────────────────────────────────────────────────
    async def _send(self, event_type: str, data: dict | None = None):
        if self.mode != "web" or not self.ws:
            return
        payload = {"type": event_type}
        if data:
            payload.update(data)
        try:
            await self.ws.send_text(json.dumps(payload))
        except Exception:
            pass

    # ── Emotion helper (safe no-op when engine not present) ──────────────────
    def _set_eye(self, emotion: str):
        """Set eye emotion. Silently ignored if no EmotionEngine attached."""
        if self._emotion is not None:
            try:
                self._emotion.set_emotion(emotion)
            except Exception as e:
                log.debug(f"Eye emotion error (non-critical): {e}")

    def _analyze_eye(self, text: str):
        """Analyze text sentiment and set eye emotion accordingly."""
        if self._emotion is not None:
            try:
                self._emotion.analyze_text(text)
            except Exception as e:
                log.debug(f"Eye sentiment error (non-critical): {e}")

    # ── Main run loop ───────────────────────────────────────────────────────────
    async def run(self, on_sleep_callback: Callable | None = None):
        self.active = True
        self.session_start = time.time()
        retry_delay = 1.5

        if self.mode == "hardware" and self._hw_player:
            self._hw_player.start()

        # Eyes: open and go neutral on session start
        self._set_eye("neutral")

        while self.active:
            config = self._live_config()
            models = [self.last_model] if self.last_model else settings.gemini_models
            connected = False

            for model in models:
                try:
                    async with self._client.aio.live.connect(
                        model=model, config=config
                    ) as session:
                        self.last_model = model
                        self.current_ai_text = ""
                        self._grounding_active = False
                        self._processing_tool  = False
                        self._had_output       = False
                        self.is_speaking       = False
                        await self._send("status", {"state": "connected"})
                        self.stream_active = True
                        retry_delay = 1.5  # reset backoff on successful connect
                        # Removed system_event greeting. Greeting is now handled locally 
                        # in main.py via espeak-ng for instant zero-latency feedback.
                        tasks = [
                            asyncio.create_task(self._pipeline_send(session)),
                            asyncio.create_task(self._pipeline_recv(session, on_sleep_callback)),
                            asyncio.create_task(self._pipeline_heartbeat()),
                        ]
                        if self.mode == "hardware":
                            tasks.append(asyncio.create_task(self._vision_loop(session)))

                        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                        self.stream_active = False
                        for t in tasks:
                            t.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)

                        if not self.active:
                            return
                        connected = True
                        break

                except Exception as e:
                    err = str(e)
                    err_lower = err.lower()
                    log.error(f"Connection error on {model}: {err[:140]}")

                    # DNS / network failure — recreate the client entirely
                    # (fixes Windows getaddrinfo bug after abnormal WebSocket closure)
                    is_dns = "getaddrinfo" in err_lower or "errno 11001" in err_lower
                    is_transient = any(
                        k in err_lower
                        for k in ("1008", "1011", "internal error", "unavailable", "service",
                                  "reset", "timeout", "eof", "connection", "broken pipe",
                                  "not implemented", "not supported")
                    )

                    if is_dns:
                        log.warning("DNS/network failure — recreating Gemini client...")
                        self._client = genai.Client(
                            api_key=settings.gemini_api_key,
                            http_options={"api_version": "v1beta"},
                        )
                        self.last_model = None
                    elif is_transient:
                        log.warning("Transient Gemini error — retrying.")
                        self.last_model = None
                    elif model == self.last_model:
                        self.last_model = None
                    continue

            if not connected:
                await self._send("status", {"state": "reconnecting"})
                log.info(f"Reconnecting in {retry_delay:.1f}s...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, 20)

            if time.time() - self.session_start > settings.session_limit_sec:
                log.info("Session limit reached — resetting session timer.")
                self.session_start = time.time()

        if self.mode == "hardware" and self._hw_player:
            self._hw_player.stop()

    # ── Send pipeline ─────────────────────────────────────────────────────────
    async def _pipeline_send(self, session):
        self._audio_paused = False
        try:
            while self.active and self.stream_active:
                # Command queue takes absolute priority
                try:
                    cmd = self.gemini_queue.get_nowait()
                    if "tool_response" in cmd:
                        await session.send_tool_response(function_responses=cmd["tool_response"])
                        # Tool response is now with Gemini — safe to clear the pending flag.
                        self._pending_tool_response = False
                    elif "turn_complete" in cmd:
                        # Server-side VAD manages the turn automatically.
                        # Pause streaming briefly to let handshake process.
                        self._audio_paused = True
                        await asyncio.sleep(0.015)
                        self._audio_paused = False
                    elif "system_event" in cmd:
                        try:
                            await session.send_client_content(
                                turns=types.Content(
                                    role="user",
                                    parts=[types.Part(text=cmd["system_event"])]
                                ),
                                turn_complete=True,
                            )
                        except Exception as e:
                            log.debug(f"System event failed: {e}")
                except asyncio.QueueEmpty:
                    pass

                if self._audio_paused:
                    await asyncio.sleep(0.002)
                    continue

                # Pull audio from the appropriate source
                # CRITICAL: Do NOT send audio while a tool call is being processed.
                if self._processing_tool:
                    await asyncio.sleep(0.01)
                    continue

                audio_bytes = await self._get_audio_chunk()
                if not audio_bytes:
                    continue

                # If AI is speaking, zero out the microphone input to prevent echo loop
                if self.mode == "hardware" and self._hw_player and self._hw_player.is_speaking():
                    audio_bytes = b"\x00" * len(audio_bytes)

                try:
                    await session.send_realtime_input(
                        audio=types.Blob(
                            data=audio_bytes,
                            mime_type=f"audio/pcm;rate={settings.sample_rate_in}"
                        )
                    )
                    if self.mode == "hardware":
                        with self._mic_buffer_lock:
                            self._mic_buffer.extend(audio_bytes)
                            excess = len(self._mic_buffer) - self._MIC_BUF_BYTES
                            if excess > 0:
                                del self._mic_buffer[:excess]
                except Exception as e:
                    err = str(e)
                    if "1000" in err or "ConnectionClosed" in type(e).__name__:
                        log.info("Gemini session closed cleanly.")
                    else:
                        log.error(f"Send error: {e}")
                    self.stream_active = False
                    break

        except asyncio.CancelledError:
            pass
        except Exception as e:
            if self.stream_active:
                log.error(f"Send pipeline unexpected error: {e}")
            self.stream_active = False

    async def _get_audio_chunk(self) -> bytes | None:
        """Get next audio chunk from the correct source (web queue or hardware queue)."""
        if self.mode == "web":
            try:
                return await asyncio.wait_for(self.audio_queue.get(), timeout=0.002)
            except asyncio.TimeoutError:
                return None
        else:
            # Hardware mode: pull from the raw mic queue (sync queue.Queue)
            import queue as _queue
            if self._raw_mic_queue is None:
                await asyncio.sleep(0.1)
                return None
            try:
                data = self._raw_mic_queue.get_nowait()
                # WebRTC AEC will handle echo at the OS level
                # This enables true full-duplex interruptions!
                return data
            except _queue.Empty:
                await asyncio.sleep(0.01)
                return None

    # ── Receive pipeline ──────────────────────────────────────────────────────
    async def _pipeline_recv(self, session, on_sleep_callback: Callable | None = None):
        FAREWELL = ["goodbye", "that will be all", "go to sleep", "standby", "dismiss"]

        try:
            got_audio = False
            user_name = self.current_user if self.mode == "hardware" else (
                (self.user or {}).get("name", "User")
            )

            async for response in session.receive():
                if not self.active or not self.stream_active:
                    break

                # ── Model output parts ────────────────────────────────────────
                if response.server_content and response.server_content.model_turn:
                    for part in response.server_content.model_turn.parts:
                        if part.inline_data:
                            data = part.inline_data.data
                            if data:
                                if not got_audio:
                                    await self._send("state", {"orb": "speaking"})
                                    got_audio = True
                                    self.is_speaking = True
                                    self._had_output = True
                                    self._grounding_active = False
                                    self._processing_tool  = False
                                    # Eyes: AI is speaking
                                    self._set_eye("speaking")

                                if self.mode == "web":
                                    try:
                                        await self.ws.send_bytes(data)
                                    except Exception:
                                        break
                                else:
                                    if self._hw_player:
                                        self._hw_player.enqueue(data)

                        elif part.text:
                            self.current_ai_text += part.text
                            self._had_output = True
                            self._grounding_active = False

                        elif getattr(part, "thought", None):
                            self._had_output = True

                # ── Transcription (hardware mode) ─────────────────────────────
                sc = response.server_content
                if sc:
                    if hasattr(sc, "input_transcription") and sc.input_transcription:
                        txt = getattr(sc.input_transcription, "text", "").strip()
                        if txt:
                            log.info(f"[{self.current_speaker}] {txt}")
                            user_id = (self.user or {}).get("id", 1)
                            save_turn(user_id, self.current_speaker, "user", txt, self.session_id)
                            detected = self._detect_identity(txt)
                            if detected:
                                await self._on_identity_learned(detected, session)
                            # Eyes: analyze user speech sentiment
                            self._analyze_eye(txt)

                    if hasattr(sc, "output_transcription") and sc.output_transcription:
                        ot = getattr(sc.output_transcription, "text", "").strip()
                        if ot:
                            self.current_ai_text += ot
                            log.info(f"[WALL-E] {ot}")

                # ── Tool calls ────────────────────────────────────────────────
                if response.tool_call and response.tool_call.function_calls:
                    tc = response.tool_call
                    tc_id = tc.function_calls[0].id if tc.function_calls else None
                    if tc_id and tc_id != self.last_tool_id:
                        self.last_tool_id = tc_id
                        self._grounding_active = True
                        self._processing_tool  = True
                        self._pending_tool_response = True  # track that response hasn't been sent yet
                        await self._send("state", {"orb": "tool_working"})
                        # Eyes: thinking while processing tool
                        self._set_eye("thinking")

                        loop = asyncio.get_event_loop()
                        res = await loop.run_in_executor(
                            None, tool_registry.dispatch, tc
                        )
                        await self.gemini_queue.put({"tool_response": res})

                # ── Grounding indicator ───────────────────────────────────────
                if sc and getattr(sc, "grounding_metadata", None):
                    self._grounding_active = True

                # ── Turn complete ─────────────────────────────────────────────
                if sc and sc.turn_complete:
                    had_output = self._had_output
                    got_audio         = False
                    self.is_speaking  = False
                    self._had_output  = False

                    if had_output:
                        # ✅ Real response — save and reset
                        if self.current_ai_text:
                            user_id = (self.user or {}).get("id", 1)
                            save_turn(user_id, user_name, "model", self.current_ai_text, self.session_id)

                            # Hardware farewell detection
                            if self.mode == "hardware" and on_sleep_callback:
                                if any(w in self.current_ai_text.lower() for w in FAREWELL):
                                    on_sleep_callback()

                            self.current_ai_text = ""

                        self._grounding_active = False
                        # CRITICAL: only clear _processing_tool if there's no pending tool response
                        # waiting to be sent. Clearing it early lets audio race the tool_response
                        # to Gemini, causing 1008 errors.
                        if not getattr(self, '_pending_tool_response', False):
                            self._processing_tool = False

                        # Eyes: AI finished speaking — back to neutral/listening
                        self._set_eye("neutral")

                    else:
                        # 🔇 Silent turn — tool call returned data, Gemini is chaining
                        if self._processing_tool or self._grounding_active:
                            # Tool chain in progress (e.g. location → web_search).
                            # Do NOT send turn_complete — let Gemini continue the chain.
                            log.debug("Silent tool-chain turn — waiting for Gemini's next action.")
                            self.current_ai_text = ""
                            self._grounding_active = False
                            # Keep _processing_tool = True so audio stays paused
                            continue
                        else:
                            self._processing_tool = False

                    await self._send("state", {"orb": "turn_complete"})

                    if self.mode == "hardware" and self._hw_player:
                        await self._wait_for_playback()

        except Exception as e:
            if self.active:
                log.error(f"Recv pipeline error: {e}")
        finally:
            self.stream_active = False
            if self.is_speaking:
                self.is_speaking = False
                asyncio.create_task(self._send("state", {"orb": "turn_complete"}))

    # ── Heartbeat ─────────────────────────────────────────────────────────────
    async def _pipeline_heartbeat(self):
        try:
            while self.active and self.stream_active:
                await asyncio.sleep(settings.heartbeat_sec)
                try:
                    await self._send("ping", {"t": time.time()})
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    # ── Vision loop (hardware only) ───────────────────────────────────────────
    async def _vision_loop(self, session):
        while self.active:
            await asyncio.sleep(2.0)
            await self._check_speaker(session, check_voice=False)

    async def _check_speaker(self, session, check_voice: bool = False):
        now = time.time()
        if now - self._last_speaker_check < settings.speaker_cooldown_sec:
            return
        self._last_speaker_check = now
        detected = None

        if self._face_engine:
            face_name, face_conf = self._face_engine.get_current_identity()
            if face_name != "Unknown" and face_conf > 0.4:
                detected = face_name
                log.debug(f"Face engine: {detected} ({face_conf:.2f})")

        if check_voice and not detected and self._identity:
            with self._mic_buffer_lock:
                buf = bytes(self._mic_buffer)
            result = await self._identity.identify_from_buffer(buf)
            if result != "Unknown":
                detected = result

        if detected and detected != self.current_speaker:
            old = self.current_speaker
            self.current_speaker = detected
            log.info(f"Speaker changed: {old} -> {detected}")
            if detected != self._last_injected:
                ctx = f"[CONTEXT: {detected} is now speaking. Be professional and helpful.]"
                await self._inject_context(session, ctx)

    async def _inject_context(self, session, text: str):
        if self._hw_player and self._hw_player._speaking.is_set():
            await asyncio.sleep(0.8)
        try:
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=text)]),
                turn_complete=False,
            )
            self._last_injected = self.current_speaker
        except Exception as e:
            log.debug(f"Context injection failed (non-critical): {e}")

    # ── Identity helpers ──────────────────────────────────────────────────────
    def _detect_identity(self, text: str) -> str | None:
        import re
        BLOCKLIST = {
            "the","and","but","not","here","there","fine","good","okay","well",
            "just","very","also","really","sure","thinking","talking","going",
            "coming","doing","saying","looking","feeling","trying","working",
            "playing","eating","happy","sad","tired","busy","free","sorry",
            "ready","back","home","done","new","old","from","your","like",
            "wall-e","walle","hai","hoon","hun","bhai","yaar","sir",
        }
        patterns = [
            r"(?:my name is|i am|i'm|mai|main|mera naam|call me|naam hai)\s+([A-Za-z\u0900-\u097F]+)",
            r"([A-Za-z]+)\s+(?:here|hoon|hun|hu|hai mera naam|naam hai mera)",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                name = m.group(1).strip().title()
                if len(name) > 2 and name.lower() not in BLOCKLIST:
                    return name
        return None

    async def _on_identity_learned(self, name: str, session):
        remember_person(name, "Introduced themselves")
        log.info(f"Identity learned: {name}")
        if self.current_user == "Unknown":
            reassign_session_turns("Unknown", name, self.session_id)
            self.current_user    = name
        self.current_speaker = name
        if name != self._last_injected:
            ctx = (
                f"[CONTEXT: This person has identified themselves as '{name}'. "
                f"Address them accordingly and be professional.]"
            )
            await self._inject_context(session, ctx)

    async def _wait_for_playback(self):
        """Wait until the hardware audio buffer drains."""
        for _ in range(100):
            if self._hw_player and self._hw_player.is_empty():
                return
            await asyncio.sleep(0.05)

    # ── Public controls ───────────────────────────────────────────────────────
    def stop(self):
        self.active = False
        self.stream_active = False
        # Eyes: neutral on session end
        self._set_eye("neutral")

    async def interrupt(self):
        """Cancel current WALL-E output and return to listening mode."""
        log.info("Interrupted by user.")
        self.is_speaking     = False
        self.current_ai_text = ""
        if self.audio_queue:
            while not self.audio_queue.empty():
                try:
                    self.audio_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
        await self.gemini_queue.put({"turn_complete": True})

    async def trigger_response(self):
        """Instantly signal Gemini that the user has finished speaking."""
        if self.is_speaking or self._processing_tool:
            return
        now = time.time()
        if now - self._last_trigger_time < 0.1:
            return
        self._last_trigger_time = now
        log.info("speech_stop received — triggering instant response")
        await self.gemini_queue.put({"turn_complete": True})

    @property
    def client_is_listening(self):
        return getattr(self, "_client_listening", False)

    @client_is_listening.setter
    def client_is_listening(self, value: bool):
        self._client_listening = value
