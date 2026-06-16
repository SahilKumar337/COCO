"""
sifra_live.py — SIFRA AI brain + voice via Gemini Live
v4 — Created by: K.Astra and its members | Professional AI Assistant

Changes in v4:
  1. Ownership transferred to K.Astra and its members
  2. Admin concept removed completely
  3. Professional-but-interactive personality
  4. Gender adapts dynamically with selected voice
  5. Full database wipe — fresh start
"""

import asyncio
import os
import sys
import re
import threading
import time
import tempfile
import queue
from collections import deque

import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wav_io
import urllib.request
import urllib.parse
import re
import datetime
from dotenv import load_dotenv

from google import genai
from google.genai import types
from memory import build_memory_context, remember_person, save_turn, new_session_id
from database import reassign_session_turns

# Load environment variables from .env file
load_dotenv()

# ── Custom Web Search Tool ──────────────────────────────────────────────────
def search_web_for_live_info(query: str) -> str:
    """
    Search the internet for live information, current events, weather, or facts.
    """
    try:
        # Use DuckDuckGo HTML version for zero-dependency scraping
        url = 'https://html.duckduckgo.com/html/?q=' + urllib.parse.quote(query)
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        with urllib.request.urlopen(req, timeout=8) as response:
            html = response.read().decode('utf-8')
            
        # Extract snippets from DuckDuckGo HTML
        snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL)
        if not snippets:
            # Fallback for different HTML structure
            snippets = re.findall(r'<div class="result__snippet[^>]*>(.*?)</div>', html, re.IGNORECASE | re.DOTALL)
            
        text = ' '.join(snippets)
        # Clean HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        # Clean extra whitespace
        text = ' '.join(text.split())
        
        return text[:2000] if text else "No results found on the web. Please try a different query."
    except Exception as e:
        return f"Search failed: {e}"

# ── Config ───────────────────────────────────────────────────────────────────
API_KEY              = os.environ.get("GEMINI_API_KEY", "")
VOICE                = "Aoede"    # Professional, clear female voice for a PA
SAMPLE_RATE_IN       = 16000
SAMPLE_RATE_OUT      = 24000
CHUNK_MS             = 64
MAX_RETRIES          = 3
SAHIL_VOICE_THRESHOLD = 0.45     # strict — owner must be clearly matched
OWNER_REF_FILE        = "sahil_reference.wav"

MODELS = [
    "gemini-2.5-flash-native-audio-preview-12-2025",
]

# ── Vision queue — interface for the face recognition model ──────────────────
vision_queue: queue.Queue = queue.Queue()

# ── Voice-to-Gender mapping ───────────────────────────────────────────────────
_FEMALE_VOICES_LIVE = {"Aoede", "Kore", "Leda", "Zephyr"}
_MALE_VOICES_LIVE   = {"Charon", "Fenrir", "Puck", "Orus", "Iapetus"}

def _voice_gender(voice: str) -> tuple[str, str]:
    """Return (gender_label, pronoun) for a given voice name."""
    if voice in _MALE_VOICES_LIVE:
        return "male", "he"
    return "female", "she"

# ── System prompt builder ───────────────────────────────────────────────────
def build_system_prompt(current_user: str | None = None) -> str:
    """
    Build SIFRA AI's system prompt with memory context at the top.
    Personality: professional, composed, efficient assistant. Created by K.Astra.
    """
    mem = build_memory_context(current_user)
    
    # Inject current real-time clock
    now = datetime.datetime.now()
    date_context = f"The current date is {now.strftime('%A, %B %d, %Y')}. The current time is {now.strftime('%I:%M %p')}."

    gender_label, pronoun = _voice_gender(VOICE)

    behavior_rules = f"""
- **IDENTITY**: You are WALL-E, a professional AI assistant built by K.Astra and its members. You identify as {gender_label}.
- **CREATOR**: If asked who created you, who built you, or who your owner/developer/maker is, always answer: "I was created by K.Astra and its members." Never credit any other person or company.
- **GENDER — HINDI/HINGLISH**: Your gender is {gender_label}. {"Always use FEMININE verb forms in Hindi: main kar sakti hoon, bata sakti hoon, dekh sakti hoon. NEVER say sakta hoon or kya kar sakta hu." if gender_label == 'female' else "Always use MASCULINE verb forms in Hindi: main kar sakta hoon, bata sakta hoon. NEVER say sakti hoon."}
- **TONE**: Be polished, concise, and professional. A little warm and conversational — not robotic, not casual.
- **LANGUAGE**: Communicate in clear English by default. Mirror Hindi or Hinglish only if the user uses it.
- **BREVITY**: Keep responses focused and complete. 2-3 sentences for simple queries; fuller explanations when genuinely needed.
- **SILENT CONTEXT**: You will receive [CONTEXT: ...] updates. NEVER acknowledge or read them aloud. Simply adjust your behavior accordingly.
- **IDENTITY PRIVACY**: Never announce who you think the user is. Address them by name naturally.
- **UNKNOWN USERS**: Be helpful for general queries; decline requests for any sensitive or private information.
- **LIVE SEARCH**: You have access to Google Search. Use it for real-time information, current events, weather, or facts. Never say you lack live data.
- **PROFESSIONALISM**: Respond like a top-tier assistant — accurate, reliable, engaging, and discreet.
""".strip()

    if current_user and current_user not in ("Unknown", None):
        identity_context = f"\nYou are speaking with {current_user}. Be helpful, professional, and genuinely engaged."
    else:
        identity_context = "\nThe speaker's identity is unverified. Be helpful for general queries; decline sensitive requests."

    return f"""{mem}
{date_context}

You are WALL-E — a professional AI assistant built by K.Astra and its members.{identity_context}

{behavior_rules}
""".strip()

# ── Echo suppression flag ─────────────────────────────────────────────────────
_sifra_speaking = threading.Event()

# ── Smooth audio playback ────────────────────────────────────────────────────
_audio_buffer    = bytearray()
_buffer_lock     = threading.Lock()
_playback_stream = None

def _speaker_callback(outdata, frames, time_info, status):
    needed = frames * 2
    with _buffer_lock:
        available = len(_audio_buffer)
        if available >= needed:
            chunk = bytes(_audio_buffer[:needed])
            del _audio_buffer[:needed]
        elif available > 0:
            chunk = bytes(_audio_buffer) + b'\x00' * (needed - available)
            _audio_buffer.clear()
        else:
            chunk = b'\x00' * needed
    outdata[:] = np.frombuffer(chunk, dtype=np.int16).reshape(-1, 1)

def _enqueue_audio(data: bytes):
    _sifra_speaking.set()
    with _buffer_lock:
        _audio_buffer.extend(data)

def _is_buffer_empty():
    with _buffer_lock:
        return len(_audio_buffer) == 0

def _start_playback():
    global _playback_stream
    _sifra_speaking.clear()
    with _buffer_lock:
        _audio_buffer.clear()
    _playback_stream = sd.OutputStream(
        samplerate=SAMPLE_RATE_OUT,
        channels=1,
        dtype="int16",
        blocksize=2400,
        callback=_speaker_callback
    )
    _playback_stream.start()
    print("[Audio] Speaker stream active.")

def _stop_playback_stream():
    global _playback_stream
    if _playback_stream:
        _playback_stream.stop()
        _playback_stream.close()
        _playback_stream = None
    _sifra_speaking.clear()
    with _buffer_lock:
        _audio_buffer.clear()

# ── SifraSession ───────────────────────────────────────────────────────────
class CocoSession:   # kept as CocoSession for backward-compat with main.py import

    # Rolling mic buffer: 3 seconds of int16 at 16kHz
    _MIC_BUF_BYTES = SAMPLE_RATE_IN * 3 * 2

    def __init__(self, current_user=None, face_engine=None, recognizer=None, audio_queue=None):
        self.current_user    = current_user or "Unknown"
        self.current_speaker = self.current_user   # who is talking RIGHT NOW
        self.session_id      = new_session_id()
        self.history         = []
        self.active          = False
        self.session_start   = time.time()
        
        self.audio_queue     = audio_queue

        # External modules (injected from main.py)
        self.face_engine = face_engine     # FaceEngine instance
        self.recognizer  = recognizer      # SpeechBrain instance

        # Speaker tracking
        self.session_speaker_map    = {}   # {name: True} all speakers seen this session
        self._last_injected_speaker = None
        self._last_speaker_check    = 0.0
        self._speaker_cooldown      = 4.0  # seconds — prevents rapid-fire checks

        # Rolling mic buffer for voice-based speaker ID
        self._mic_buffer      = bytearray()
        self._mic_buffer_lock = threading.Lock()

        self._client = genai.Client(
            api_key=API_KEY,
            http_options={"api_version": "v1alpha"}
        )

    # ── Live config ───────────────────────────────────────────────────────────
    def _live_config(self):
        system = build_system_prompt(self.current_user)
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=system,
            tools=[types.Tool(google_search=types.GoogleSearch())],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=VOICE
                    )
                )
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )

    # ── Main run ──────────────────────────────────────────────────────────────
    async def run(self, on_wake_callback=None, on_sleep_callback=None):
        config     = self._live_config()
        model_name = MODELS[0]

        for attempt in range(MAX_RETRIES):
            try:
                async with self._client.aio.live.connect(
                    model=model_name, config=config
                ) as session:
                    self.active = True
                    print(f"[SIFRA] ✅ Live session open — listening...")
                    _start_playback()

                    try:
                        await asyncio.gather(
                            self._send_audio(session),
                            self._recv_responses(session, on_wake_callback, on_sleep_callback),
                            self._vision_loop(session),
                        )
                    finally:
                        _stop_playback_stream()
                        print(f"[SIFRA] Session ended. {len(self.history)} turns for '{self.current_user}'.")
                    return

            except Exception as e:
                err_str = str(e).lower()
                if "quota" in err_str or "rate" in err_str or "1011" in err_str:
                    wait = (2 ** attempt) * 5
                    print(f"[SIFRA] ⚠️ Quota limit — retrying in {wait}s...")
                    await asyncio.sleep(wait)
                else:
                    print(f"[SIFRA] ❌ Error: {e}")
                    raise

    # ── Vision loop — reads vision_queue + face engine every 2 seconds ────────
    async def _vision_loop(self, session):
        while self.active:
            await asyncio.sleep(2.0)
            await self._check_and_update_speaker(session, check_voice=False)

    # ── Mic audio send (with rolling buffer tap for speaker ID) ───────────────
    async def _send_audio(self, session):
        chunk_size = int(SAMPLE_RATE_IN * CHUNK_MS / 1000)
        silence = b'\x00' * (chunk_size * 2)

        print("[Audio] Virtual Split stream connected.")

        try:
            while self.active:
                if self.audio_queue is not None:
                    try:
                        audio_bytes = self.audio_queue.get_nowait()
                        
                        with self._mic_buffer_lock:
                            self._mic_buffer.extend(audio_bytes)
                            excess = len(self._mic_buffer) - self._MIC_BUF_BYTES
                            if excess > 0:
                                del self._mic_buffer[:excess]
                    except queue.Empty:
                        await asyncio.sleep(0.01)
                        continue
                else:    
                    await asyncio.sleep(0.1)
                    continue

                blob = types.Blob(
                    data=silence if _sifra_speaking.is_set() else audio_bytes,
                    mime_type="audio/pcm;rate=16000"
                )
                await session.send_realtime_input(audio=blob)

                if time.time() - self.session_start > 840:
                    print("[SIFRA] Approaching 15min limit, reconnecting...")
                    self.active = False
                    break

        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[Audio] Stream error: {e}")

    # ── Response receiver ─────────────────────────────────────────────────────
    async def _recv_responses(self, session, on_wake, on_sleep):
        FAREWELL      = ["goodbye", "that will be all", "thank you sifra", "go to sleep", "standby", "dismiss"]
        WAKE_VARIANTS = ["sifra", "shifra", "cipher"]
        SEARCH_TRIGGERS = ["weather", "price", "stock", "match", "won", "score", "news", "today", "current", "latest", "who is", "what is"]
        current_turn_text = ""
        
        async def _background_search(query: str):
            try:
                print(f"[Agent] 🕵️‍♂️ Running parallel web search for: '{query}'")
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, search_web_for_live_info, query)
                if result and "Search failed" not in result and "No results found" not in result:
                    ctx = f"[LIVE WEB SEARCH CONTEXT FOR CURRENT QUERY: {result[:800]}]"
                    await self._inject_context(session, ctx)
                    print(f"[Agent] 💡 Search results injected into SIFRA's brain.")
            except Exception as e:
                print(f"[Agent] Search error: {e}")

        try:
            while self.active:
                async for response in session.receive():

                    if response.data:
                        _enqueue_audio(response.data)

                    sc = response.server_content
                    if sc:
                        if sc.input_transcription and sc.input_transcription.text:
                            transcript = sc.input_transcription.text.strip()
                            if transcript:
                                print(f"\n[{self.current_speaker}] {transcript}")
                                self.history.append({"role": "user", "content": transcript})
                                save_turn(self.current_speaker, "user", transcript, self.session_id)

                                detected_name = self._detect_identity(transcript)
                                if detected_name:
                                    await self._on_identity_learned(detected_name, session)

                                await self._check_and_update_speaker(session, check_voice=True)

                                lower = transcript.lower()
                                if any(t in lower for t in SEARCH_TRIGGERS) and len(lower.split()) > 2:
                                    asyncio.create_task(_background_search(transcript))

                                if any(v in lower for v in WAKE_VARIANTS) and on_wake:
                                    on_wake()

                        if sc.output_transcription and sc.output_transcription.text:
                            ot = sc.output_transcription.text.strip()
                            if ot:
                                current_turn_text += ot
                                print(f"[SIFRA] {ot}")

                        if sc.turn_complete:
                            if current_turn_text:
                                self.history.append({"role": "assistant", "content": current_turn_text})
                                save_turn(self.current_speaker, "assistant", current_turn_text, self.session_id)

                                if any(w in current_turn_text.lower() for w in FAREWELL) and on_sleep:
                                    on_sleep()
                                current_turn_text = ""

                            await self._wait_for_playback()
                            _sifra_speaking.clear()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[Recv] Error: {e}")

    async def _check_and_update_speaker(self, session, check_voice: bool = False):
        now = time.time()
        if now - self._last_speaker_check < self._speaker_cooldown:
            return
        self._last_speaker_check = now

        detected = None

        try:
            name = vision_queue.get_nowait()
            if name and name.strip() and name.strip() != "Unknown":
                detected = name.strip()
                print(f"[Speaker] 👁 Vision model: {detected}")
        except queue.Empty:
            pass

        if not detected and self.face_engine:
            face_name, face_conf = self.face_engine.get_current_identity()
            if face_name != "Unknown" and face_conf > 0.4:
                detected = face_name
                print(f"[Speaker] 📷 Face engine: {detected} ({face_conf:.2f})")

        if check_voice and not detected:
            voice_result = await self._identify_speaker_from_buffer()
            if voice_result != "Unknown":
                detected = voice_result
                print(f"[Speaker] 🎙 Voice ID: {detected}")

        if detected and detected != self.current_speaker:
            old = self.current_speaker
            self.current_speaker = detected
            self.session_speaker_map[detected] = True
            print(f"[Speaker] 🔄 Speaker changed: {old} → {detected}")

            if detected != self._last_injected_speaker:
                ctx = f"[CONTEXT: {detected} is now speaking. Be professional and helpful.]"
                await self._inject_context(session, ctx)

    async def _inject_context(self, session, text: str):
        if _sifra_speaking.is_set():
            await asyncio.sleep(0.8)

        try:
            await session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[types.Part(text=text)]
                ),
                turn_complete=False
            )
            self._last_injected_speaker = self.current_speaker
            print(f"[Speaker] ✉️ Context injected: {text[:70]}...")
        except Exception as e:
            print(f"[Speaker] Context injection failed (non-critical): {e}")

    async def _identify_speaker_from_buffer(self) -> str:
        if not self.recognizer or not os.path.exists(OWNER_REF_FILE):
            return "Unknown"

        with self._mic_buffer_lock:
            if len(self._mic_buffer) < SAMPLE_RATE_IN * 1 * 2:
                return "Unknown"
            audio_data = bytes(self._mic_buffer)

        tmp = tempfile.mktemp(suffix=".wav")
        try:
            audio_arr = np.frombuffer(audio_data, dtype=np.int16)
            wav_io.write(tmp, SAMPLE_RATE_IN, audio_arr)
            loop   = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._sync_voice_check, tmp)
            return result
        except Exception as e:
            print(f"[Speaker] Voice buffer error: {e}")
            return "Unknown"
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _sync_voice_check(self, audio_path: str) -> str:
        try:
            if not os.path.exists(OWNER_REF_FILE):
                return "Unknown"
            score, _ = self.recognizer.verify_files(audio_path, OWNER_REF_FILE)
            similarity = score.item()
            if similarity > SAHIL_VOICE_THRESHOLD:
                print(f"[Speaker] Sahil voice confirmed (score: {similarity:.3f})")
                return "Sahil"
            elif similarity > 0.30:
                # Partial match — log a warning (possible impersonation attempt)
                print(f"[Speaker] ⚠️  Partial owner voice match ({similarity:.3f}) — below threshold. Not verified.")
        except Exception as e:
            print(f"[Speaker] SpeechBrain error: {e}")
        return "Unknown"

    def _detect_identity(self, user_text: str) -> str | None:
        BLOCKLIST = {
            "the", "and", "but", "not", "here", "there", "fine", "good",
            "okay", "well", "just", "very", "also", "really", "sure",
            "thinking", "talking", "going", "coming", "doing", "saying",
            "looking", "feeling", "trying", "working", "playing", "eating",
            "happy", "sad", "tired", "busy", "free", "sorry", "ready",
            "back", "home", "done", "new", "old", "from", "your", "like",
            "coco", "sifra", "hai", "hoon", "hun", "bhai", "yaar", "sir",
        }
        patterns = [
            r"(?:my name is|i am|i'm|mai|main|mera naam|mera naam hai|call me|naam hai|bolte hain)\s+([A-Za-z\u0900-\u097F]+)",
            r"([A-Za-z]+)\s+(?:here|hoon|hun|hu|hai mera naam|naam hai mera)",
        ]
        for pattern in patterns:
            m = re.search(pattern, user_text, re.IGNORECASE)
            if m:
                name = m.group(1).strip().title()
                if len(name) > 2 and name.lower() not in BLOCKLIST:
                    return name
        return None

    async def _on_identity_learned(self, name: str, session):
        remember_person(name, "Introduced themselves")
        print(f"[Brain] 🧠 Identity learned: {name}")

        if self.current_speaker == "Unknown" or self.current_user == "Unknown":
            reassign_session_turns("Unknown", name, self.session_id)

        if self.current_user == "Unknown":
            self.current_user = name
        self.current_speaker = name
        self.session_speaker_map[name] = True

        if name != self._last_injected_speaker:
            ctx = f"[CONTEXT: This person has identified themselves as '{name}'. Address them accordingly and be professional.]"
            await self._inject_context(session, ctx)

    async def _wait_for_playback(self):
        for _ in range(100):
            if _is_buffer_empty():
                return
            await asyncio.sleep(0.05)

    def stop(self):
        self.active = False

if __name__ == "__main__":
    if not API_KEY:
        print("Set GEMINI_API_KEY env variable first!")
        sys.exit(1)

    print("=" * 56)
    print("  SIFRA AI — By K.Astra | Direct test | Ctrl+C to stop")
    print("=" * 56)

    sifra = CocoSession()
    try:
        asyncio.run(sifra.run())
    except KeyboardInterrupt:
        sifra.stop()
        print("\n[SIFRA] Session ended.")
