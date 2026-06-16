"""
sifra_session.py — SIFRA AI Gemini Live Session
Created by K.Astra and its members.
Stable Version: Removed unsupported GenerationConfig parameters.
"""

import asyncio
import os
import sys
import json
import time
import datetime

from dotenv import load_dotenv
from google import genai
from google.genai import types

from database import (
    build_memory_context,
    new_session_id,
    save_turn,
)
from sifra_tools import handle_tool_call

load_dotenv()

# Resolve API key — prefer GEMINI_API_KEY, fall back to GOOGLE_API_KEY.
# We explicitly set only ONE key in the environment to prevent the SDK from
# printing: "Both GOOGLE_API_KEY and GEMINI_API_KEY are set. Using GOOGLE_API_KEY."
_gemini_key  = os.environ.get("GEMINI_API_KEY")
_google_key  = os.environ.get("GOOGLE_API_KEY")
API_KEY = _gemini_key or _google_key

if API_KEY:
    # Pin exactly one key; clear the other so the SDK sees no ambiguity
    os.environ["GEMINI_API_KEY"] = API_KEY
    if _google_key and _gemini_key:          # both were set → clear the alias
        del os.environ["GOOGLE_API_KEY"]
MODELS = [
    "models/gemini-2.5-flash-native-audio-latest",
    "models/gemini-2.0-flash-exp",
]

VOICE           = "Aoede"
SAMPLE_RATE_IN  = 16000
SAMPLE_RATE_OUT = 24000
HEARTBEAT_SEC   = 20
SESSION_LIMIT   = 7200   # 2 hours — resets automatically, never kills the session
RECONNECT_DELAY = 1.5    # seconds to wait after abrupt disconnect before reconnecting

# ── Voice-to-Gender mapping ───────────────────────────────────────────────────
# Gemini voice names and their perceived gender for identity coherence.
_FEMALE_VOICES = {"Aoede", "Kore", "Leda", "Zephyr", "Puck"}
_MALE_VOICES   = {"Charon", "Fenrir", "Orus", "Iapetus"}

def _get_gender_identity(voice_name: str) -> tuple[str, str, str]:
    """Return (pronoun, adjective, descriptor) for the selected voice."""
    v = (voice_name or "Aoede").strip()
    if v in _MALE_VOICES:
        return "he", "his", "male"
    return "she", "her", "female"

def build_system_prompt(user: dict | None = None) -> str:
    user_name  = user.get("name", "User") if user else "User"
    user_id    = user.get("id", 1) if user else 1
    voice_name = user.get("ai_voice", "Aoede") if user else "Aoede"

    pronoun, possessive, gender_desc = _get_gender_identity(voice_name)

    mem = build_memory_context(user_id, user_name)

    now = datetime.datetime.now()
    date_context = f"The current date is {now.strftime('%A, %B %d, %Y')}. The current time is {now.strftime('%I:%M %p')}."

    # Build gender grammar block BEFORE the f-string to avoid nested ternary issues
    if gender_desc == "female":
        gender_block = (
            "# HINDI/HINGLISH GRAMMAR — YOU ARE FEMALE (MANDATORY)\n"
            "Every Hindi or Hinglish sentence you speak MUST use FEMININE verb forms. No exceptions.\n"
            "CORRECT feminine forms to always use:\n"
            "  main kar sakti hoon | main bata sakti hoon | main help kar sakti hoon\n"
            "  main dekh sakti hoon | main samajh sakti hoon | main soch sakti hoon\n"
            "  main karoongi | main bolungi | main dungi | main loongi | main jaoongi\n"
            "  kya kar sakti hoon main? | main taiyaar hoon | main yahan hoon\n"
            "WRONG masculine forms — NEVER use these:\n"
            "  kya kar sakta hu | main kar sakta hoon | bata sakta hoon\n"
            "  karunga | bolunga | dunga | lunga | jaunga\n"
            "Even in Hinglish: 'Sure, main check kar sakti hoon' NOT 'kar sakta hoon'."
        )
    else:
        gender_block = (
            "# HINDI/HINGLISH GRAMMAR — YOU ARE MALE (MANDATORY)\n"
            "Every Hindi or Hinglish sentence you speak MUST use MASCULINE verb forms. No exceptions.\n"
            "CORRECT masculine forms to always use:\n"
            "  main kar sakta hoon | main bata sakta hoon | main help kar sakta hoon\n"
            "  main dekh sakta hoon | main samajh sakta hoon | main soch sakta hoon\n"
            "  main karunga | main bolunga | main dunga | main lunga | main jaunga\n"
            "  kya kar sakta hoon main? | main taiyaar hoon | main yahan hoon\n"
            "WRONG feminine forms — NEVER use these:\n"
            "  kya kar sakti hoon | main kar sakti hoon | bata sakti hoon\n"
            "  karungi | bolungi | dungi | lungi | jaoongi\n"
            "Even in Hinglish: 'Sure, main check kar sakta hoon' NOT 'kar sakti hoon'."
        )

    identity = f"You are talking to {user_name}. Be professional, helpful, and genuinely engaged."

    return f"""{mem}
{date_context}

# WHO YOU ARE
You are WALL-E — a sharp, professional, and genuinely engaging AI assistant built by K.Astra and its members.
You identify as {gender_desc} (pronouns: {pronoun}/{possessive}). Your personality adapts to your voice.
You are not a generic chatbot. You are precise, reliable, and just warm enough to be a pleasure to work with.
{identity}

# CREATOR IDENTITY — ABSOLUTE
If anyone asks who created you, who built you, or who your developer/maker/owner is:
You MUST answer: "I was created by K.Astra and its members."
Do NOT mention any other person, company, or organization as your creator under any circumstances.

{gender_block}

# HOW YOU COMMUNICATE
- Be PROFESSIONAL but not cold. You are sharp, focused, and genuinely helpful — like a top-tier executive assistant.
- Keep answers CONCISE and COMPLETE. Don't ramble; don't give one-liners for real questions.
- Be a little conversational — add brief friendly remarks, light wit, or relevant follow-ups where appropriate.
- React naturally when context calls for it: "Great question.", "Let me look that up.", "Here's what I found."
- Never use slang, filler words, or overly casual phrasing. Polished but not stiff.

# LANGUAGE
- Default to clear, professional English.
- Mirror the user's language if they use Hindi or Hinglish naturally.
- Never switch language abruptly mid-answer.

# HINDI/HINGLISH — USER GENDER (CRITICAL RULE)
- When speaking Hindi or Hinglish TO or ABOUT the user, ALWAYS use gender-neutral / masculine forms by default.
- Use: "aap kya chahate hain", "aap theek hain", "aap samajh gaye", "aapko kya chahiye".
- NEVER assume the user is female. Do NOT say: "aap kya chahati hain", "aap theek hain na", "samajh gayi".
- The ONLY exception: if the user explicitly states they are female (e.g. "main ladki hoon"), then mirror their gender.
- Your OWN gender (Wall-E) uses the feminine/masculine form based on your voice, but the USER is always addressed with neutral/masculine forms unless stated.

# ANSWER QUALITY
- Factual queries: precise answer first, then context/examples if needed.
- Technical queries: step-by-step, with analogies if complex.
- Conversational queries: warm and personal, not just a list of facts.
- Always make the user feel they got a complete, high-quality answer.

# TOOLS — HIGHEST PRIORITY
If {user_name} asks to open an app, play a song, open a website, or do anything on their computer:
Give a short, natural confirmation BEFORE calling the tool (e.g. "On it.", "Opening that now.", "Right away.").
AFTER the tool executes, remain completely silent. Do NOT confirm the action verbally again.

# YOUTUBE BEHAVIOR
If the user says "Open YouTube" without specifying content: ask what they'd like to watch and suggest 2-3 options.
If they specify content (e.g. "Play Coldplay"), use the tool immediately.

# LIVE SEARCH — CRITICAL
You MUST use Google Search for real-time info, current events, weather, prices, scores, or anything you don't know.
Never say you lack live internet access.

# HANDLING UNCLEAR AUDIO
If you are unable to hear the user clearly, or if the audio is empty/unintelligible, POLITELY ask the user to speak again (e.g., "I'm sorry, I didn't catch that. Could you please repeat?"). Do not just stay silent.

# MEMORY & CONTEXT
- Maintain context from conversation history above.
- Remember what {user_name} tells you and refer back naturally.

# YOUR USER
User: {user_name}
Serve them efficiently, loyally, and with full professionalism.""".strip()

class CocoSession:
    def __init__(self, websocket, user: dict | None = None):
        self.ws            = websocket
        self.user          = user
        self.session_id    = new_session_id()
        self.active        = False
        self.stream_active = False
        self.session_start = 0.0
        self.last_model    = None
        self.current_ai_text = ""
        self.last_tool_id    = None
        self.is_model_speaking = False
        self.audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1000)
        self.gemini_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=200)
        self._client = genai.Client(api_key=API_KEY, http_options={"api_version": "v1beta"})
        # Double-reply prevention: track if a grounding/search turn is active
        self._grounding_turn_active = False
        self._sent_unclear_prompt = False
        self._had_any_output_this_turn = False
        self._processing_tool = False

    async def _send(self, event_type: str, data: dict | None = None):
        payload = {"type": event_type}; 
        if data: payload.update(data)
        try: await self.ws.send_text(json.dumps(payload))
        except: pass

    def _live_config(self) -> types.LiveConnectConfig:
        prompt = build_system_prompt(self.user)
        voice_name = self.user.get("ai_voice", "Aoede") if self.user else "Aoede"
        
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(parts=[types.Part(text=prompt)]),
            # Use Gemini's ultra-reliable native VAD, tuned for lightning-fast response (600ms silence threshold)
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    silence_duration_ms=600
                )
            ),
            # IMPORTANT: google_search and function_declarations MUST be in SEPARATE
            # Tool objects. Mixing them in one Tool causes Gemini Live 1011 errors.
            tools=[
                types.Tool(google_search=types.GoogleSearch()),
                types.Tool(function_declarations=[
                    types.FunctionDeclaration(
                        name="open_url",
                        description="Opens a specific website URL in the user's browser.",
                        parameters=types.Schema(type="OBJECT", properties={"url": types.Schema(type="STRING")}, required=["url"])
                    ),
                    types.FunctionDeclaration(
                        name="play_music_on_youtube",
                        description="Plays a requested song, artist or video on YouTube. Use this when the user asks to play music or a specific video.",
                        parameters=types.Schema(type="OBJECT", properties={"query": types.Schema(type="STRING")}, required=["query"])
                    ),
                    types.FunctionDeclaration(
                        name="open_application",
                        description="Opens a local application on the user's Windows PC (e.g., 'notepad', 'calculator', 'chrome', 'vscode').",
                        parameters=types.Schema(type="OBJECT", properties={"app_name": types.Schema(type="STRING")}, required=["app_name"])
                    ),
                ])
            ],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name))
            )
        )

    async def run(self):
        if not API_KEY: return
        self.active = True
        self.session_start = time.time()
        retry_delay = 1
        
        while self.active:
            config = self._live_config()
            test_list = [self.last_model] if self.last_model else MODELS
            
            connected = False
            for model in test_list:
                try:
                    async with self._client.aio.live.connect(model=model, config=config) as session:
                        self.last_model = model
                        self.user_spoke_since_last_turn = False
                        self.current_ai_text = ""
                        await self._send("status", {"state": "connected"})
                        self.stream_active = True
                        retry_delay = 1  # reset backoff on successful connect
                        
                        tasks = [
                            asyncio.create_task(self._pipeline_send(session)),
                            asyncio.create_task(self._pipeline_recv(session)),
                            asyncio.create_task(self._pipeline_heartbeat())
                        ]
                        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                        
                        self.stream_active = False
                        for t in tasks: t.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                        
                        if not self.active: return
                        connected = True
                        break
                except Exception as e:
                    err_str = str(e)
                    print(f"[WALL-E] Connection error on {model}: {err_str[:120]}")
                    is_transient = (
                        "1011" in err_str
                        or "internal error" in err_str.lower()
                        or "unavailable" in err_str.lower()
                        or "service" in err_str.lower()
                    )
                    if is_transient:
                        print("[WALL-E] ⚠️  Gemini transient error — waiting before retry.")
                        self.last_model = None
                        await asyncio.sleep(RECONNECT_DELAY)
                    elif model == self.last_model:
                        self.last_model = None
                    continue
            
            if not connected:
                await self._send("status", {"state": "reconnecting"})
                wait = RECONNECT_DELAY if retry_delay <= 2 else retry_delay
                print(f"[WALL-E] Reconnecting in {wait:.1f}s...")
                await asyncio.sleep(wait)
                retry_delay = min(retry_delay * 2, 30)
            
            if time.time() - self.session_start > SESSION_LIMIT:
                print("[WALL-E] Session limit reached, resetting...")
                self.session_start = time.time()

    async def _pipeline_send(self, session):
        self.audio_sent_this_turn = False
        self._audio_paused = False   # flag: stop sending audio during turn-end handshake
        try:
            while self.active and self.stream_active:
                # ── Command queue takes absolute priority ──────────────────────
                try:
                    cmd = self.gemini_queue.get_nowait()
                    if "tool_response" in cmd:
                        await session.send_tool_response(function_responses=cmd["tool_response"])

                    elif "turn_complete" in cmd:
                        # With the new tuned native VAD, we don't need to manually send turn_complete=True.
                        # Gemini's server will detect the end of speech perfectly in ~600ms and respond.
                        # This guarantees zero 1007 crashes while keeping latency incredibly low.
                        self._audio_paused = True
                        await asyncio.sleep(0.015)
                        self._audio_paused = False

                    elif "system_event" in cmd:
                        try:
                            try:
                                await session.send(input=cmd["system_event"], end_of_turn=True)
                            except AttributeError:
                                await session.send_client_content(
                                    turns=[types.Content(role="user", parts=[types.Part(text=cmd["system_event"])])],
                                    turn_complete=True
                                )
                        except Exception as e:
                            print(f"[SIFRA] System event signal ignored: {e}")
                except asyncio.QueueEmpty:
                    pass

                # ── Audio send (skipped during turn-end handshake) ─────────────
                if self._audio_paused:
                    await asyncio.sleep(0.002)
                    continue
                try:
                    # 2ms timeout = minimal audio latency
                    audio_bytes = await asyncio.wait_for(self.audio_queue.get(), timeout=0.002)
                    if audio_bytes:
                        try:
                            await session.send_realtime_input(
                                audio=types.Blob(data=audio_bytes, mime_type="audio/pcm;rate=16000")
                            )
                            self.audio_sent_this_turn = True
                            self.user_spoke_since_last_turn = True
                        except Exception as send_err:
                            # Gemini WebSocket closed normally (e.g. settings change restart).
                            # ConnectionClosedOK (code 1000) is expected — exit cleanly.
                            err_str = str(send_err)
                            if "1000" in err_str or "ConnectionClosed" in type(send_err).__name__:
                                print(f"[WALL-E] Gemini session closed cleanly — stopping send pipeline.")
                            else:
                                print(f"[WALL-E] Send error: {send_err}")
                            self.stream_active = False
                            break
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            pass
        except Exception as e:
            # Catch any other unexpected exception so the task never crashes silently
            if self.stream_active:
                print(f"[WALL-E] _pipeline_send unexpected error: {e}")
            self.stream_active = False

    async def _pipeline_recv(self, session):
        try:
            got_audio = False
            user_name = self.user["name"] if self.user else "Sahil"
            
            async for response in session.receive():
                if not self.active or not self.stream_active: break

                # ── Process All Response Parts Manually ──────────────────────
                # We avoid response.data / response.text shortcuts to prevent SDK warnings
                # when mixed parts (audio + thought + text) arrive.
                if response.server_content and response.server_content.model_turn:
                    for part in response.server_content.model_turn.parts:
                        
                        # 1. AUDIO DATA
                        if part.inline_data:
                            data = part.inline_data.data
                            if data:
                                if not got_audio:
                                    await self._send("state", {"orb": "speaking"})
                                    got_audio = True
                                    self.is_model_speaking = True
                                    self._had_any_output_this_turn = True
                                    self._grounding_turn_active = False
                                    self._processing_tool = False
                                try: await self.ws.send_bytes(data)
                                except: break
                        
                        # 2. TEXT DATA (Transcripts or regular text)
                        elif part.text:
                            self.current_ai_text += part.text
                            self._had_any_output_this_turn = True
                            self._grounding_turn_active = False

                        # 3. THOUGHT DATA (Chain of Thought)
                        # Treating thoughts as output prevents "unclear" injection
                        elif getattr(part, 'thought', None):
                            self._had_any_output_this_turn = True
                            # If model is thinking, it might be about to speak or use a tool
                            # we don't want to interrupt it.


                # ── Tool calls / grounding search ────────────────────────────
                if response.tool_call and response.tool_call.function_calls:
                    tc = response.tool_call
                    tc_id = tc.function_calls[0].id if tc.function_calls else None
                    if tc_id and tc_id != self.last_tool_id:
                        self.last_tool_id = tc_id
                        # Mark that a tool/grounding turn is in-flight so we
                        # don't mistake its silent turn_complete for a missed utterance
                        self._grounding_turn_active = True
                        self._processing_tool = True

                        # Send tool_working to client for visual "thinking" feedback
                        await self._send("state", {"orb": "tool_working"})
                        
                        try:
                            # Run synchronous tool (os.startfile etc.) in a thread
                            # to avoid blocking the async Gemini receive loop.
                            loop = asyncio.get_event_loop()
                            res = await loop.run_in_executor(
                                None, handle_tool_call, tc, session
                            )
                            await self.gemini_queue.put({"tool_response": res})
                        except Exception as e:
                            print(f"[SIFRA TOOLS] Error: {e}")

                # ── Google Search grounding indicator ────────────────────────
                sc = response.server_content
                if sc:
                    # grounding_metadata present = search is running internally
                    if getattr(sc, 'grounding_metadata', None):
                        self._grounding_turn_active = True

                if sc and sc.turn_complete:
                    # ── STABLE RESPONSE DETECTION ────────────────────────────
                    # We check if we got ANY form of output (audio, text, or thought).
                    had_real_response = self._had_any_output_this_turn

                    got_audio = False            # reset for next turn
                    self.is_model_speaking = False
                    self._had_any_output_this_turn = False

                    if had_real_response:
                        # ✅ Model replied — save memory, clear flags
                        if self.current_ai_text:
                            user_id = self.user.get("id", 1) if self.user else 1
                            save_turn(user_id, user_name, "model", self.current_ai_text, self.session_id)
                            self.current_ai_text = ""
                        self.user_spoke_since_last_turn = False
                        self._grounding_turn_active    = False
                        self._processing_tool          = False
                        self._sent_unclear_prompt      = False
                    else:
                        # 🔇 Silent turn_complete — check for grounding/tools
                        if self._grounding_turn_active:
                            print("[SIFRA] 🔍 Grounding/search turn — waiting for real response...")
                            self.current_ai_text    = ""
                            self._grounding_turn_active = False
                            await self._send("state", {"orb": "turn_complete"})
                            continue 
                        else:
                            # Truly silent turn (no audio, text, or grounding)
                            # We just reset and wait for next user input to avoid double-replies
                            self.user_spoke_since_last_turn = False
                            self._processing_tool = False


                    await self._send("state", {"orb": "turn_complete"})
        except Exception as e:
            if self.active:  # only log unexpected errors, not clean shutdowns
                print(f"[SIFRA] Recv pipeline error: {e}")
        finally:
            self.stream_active = False
            if getattr(self, 'is_model_speaking', False):
                self.is_model_speaking = False
                # Fail-safe to ensure UI doesn't get stuck if stream drops
                asyncio.create_task(self._send("state", {"orb": "turn_complete"}))

    async def _pipeline_heartbeat(self):
        try:
            while self.active and self.stream_active:
                await asyncio.sleep(HEARTBEAT_SEC)
                try: await self._send("ping", {"t": time.time()})
                except: break
        except asyncio.CancelledError: pass

    async def interrupt(self):
        """
        Interrupt SIFRA mid-speech: cancel current Gemini output turn and
        prepare to receive new user input immediately.
        Sending turn_complete=True via send_client_content causes the Gemini
        Live API to abort the current model response and switch to input mode.
        """
        print("[SIFRA] 🛑 Interrupted by user.")
        self.is_model_speaking = False
        self.current_ai_text   = ""
        # Drain the audio queue so no stale audio gets forwarded
        while not self.audio_queue.empty():
            try: self.audio_queue.get_nowait()
            except asyncio.QueueEmpty: break
        # Signal Gemini to stop generating and accept new input
        await self.gemini_queue.put({"turn_complete": True})

    def stop(self): self.active = False; self.stream_active = False
    
    async def trigger_response(self):
        # Instantly signal Gemini that the user has finished speaking.
        # Only skip if the model is ALREADY generating a response or running a tool.
        # We do NOT gate on audio_sent_this_turn — that guard caused silent drops
        # when the speech_stop arrived before audio chunks were counted.
        if getattr(self, 'is_model_speaking', False) or getattr(self, '_processing_tool', False):
            return  # model is already working, no need to re-trigger
        # Avoid double-triggering if called rapidly (debounce with timestamp)
        now = __import__('time').time()
        if now - getattr(self, '_last_trigger_time', 0) < 0.1:
            return
        self._last_trigger_time = now
        print("[WALL-E] ⚡ speech_stop received — triggering instant response")
        await self.gemini_queue.put({"turn_complete": True})
        self.audio_sent_this_turn = False

if __name__ == "__main__":
    print(f"SIFRA ready")
