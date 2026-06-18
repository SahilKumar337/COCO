"""
emotion_engine.py — WALL-E AI Emotion Engine
Analyzes conversation text for sentiment and drives ESP32 eye displays
via serial commands. Thread-safe for concurrent pipeline access.

Serial protocol (to ESP32):
  N = Neutral    H = Happy    S = Sad      A = Angry
  U = Surprised  T = Thinking L = Listening K = Speaking
  B = Blink      O = Boot-open  X = Sleep-close

Created by K.Astra and its members.
"""

import re
import serial
import threading
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("EmotionEngine")


# ── Emotion Constants ─────────────────────────────────────────────────────────
EMOTION_NEUTRAL   = "neutral"
EMOTION_HAPPY     = "happy"
EMOTION_SAD       = "sad"
EMOTION_ANGRY     = "angry"
EMOTION_SURPRISED = "surprised"
EMOTION_THINKING  = "thinking"
EMOTION_LISTENING = "listening"
EMOTION_SPEAKING  = "speaking"

# Map emotion names to serial command characters
_EMOTION_TO_CMD = {
    EMOTION_NEUTRAL:   "N",
    EMOTION_HAPPY:     "H",
    EMOTION_SAD:       "S",
    EMOTION_ANGRY:     "A",
    EMOTION_SURPRISED: "U",
    EMOTION_THINKING:  "T",
    EMOTION_LISTENING: "L",
    EMOTION_SPEAKING:  "K",
}

# ── Keyword-Based Sentiment Analysis ──────────────────────────────────────────
# Each list is ordered roughly by strength. We count weighted matches.
_EMOTION_KEYWORDS = {
    EMOTION_HAPPY: [
        "thanks", "thank you", "thankyou", "shukriya", "dhanyavaad",
        "great", "awesome", "amazing", "wonderful", "fantastic", "excellent",
        "perfect", "beautiful", "brilliant", "superb", "love", "loved",
        "haha", "hahaha", "lol", "lmao", "rofl", "funny", "hilarious",
        "good", "nice", "cool", "wow", "yay", "hooray", "yes",
        "happy", "glad", "excited", "proud", "blessed", "grateful",
        "bahut accha", "maza aa gaya", "bahut badhiya", "khush",
        "best", "impressive", "outstanding", "incredible",
    ],
    EMOTION_SAD: [
        "sad", "sorry", "miss", "missed", "unfortunate", "terrible",
        "cry", "crying", "cried", "tears", "pain", "painful", "hurt",
        "lost", "lose", "fail", "failed", "failure", "disappointed",
        "depressed", "lonely", "alone", "heartbroken", "broken",
        "bad", "worst", "horrible", "awful", "miserable",
        "dukhi", "udaas", "bura laga", "dard", "takleef",
        "regret", "wish", "unfortunately", "tragic", "death", "died",
    ],
    EMOTION_ANGRY: [
        "angry", "hate", "stupid", "idiot", "fool", "dumb",
        "worst", "annoying", "annoyed", "frustrated", "furious",
        "damn", "shut up", "useless", "pathetic", "ridiculous",
        "disgusting", "nonsense", "rubbish", "trash", "garbage",
        "gussa", "chup", "bakwas", "bewakoof", "pagal",
        "irritating", "fed up", "sick of", "enough", "stop it",
    ],
    EMOTION_SURPRISED: [
        "wow", "really", "no way", "oh my god", "omg", "oh my",
        "seriously", "what", "unbelievable", "incredible", "shocked",
        "oh", "whoa", "damn", "holy", "are you kidding",
        "can't believe", "impossible", "insane", "crazy",
        "sach mein", "kya baat", "arre", "oh ho", "hai na",
        "unexpected", "never expected", "mind blown", "blown away",
    ],
}

# Hindi/Hinglish sentiment boosters
_POSITIVE_HINDI = {"accha", "badhiya", "mast", "zabardast", "shandar", "wah"}
_NEGATIVE_HINDI = {"bura", "kharab", "ghatiya", "bekar", "wahiyat"}


class EmotionEngine:
    """
    Manages AI eye emotions via ESP32 serial connection.

    Usage:
        engine = EmotionEngine(port="/dev/ttyUSB1")
        engine.set_emotion("happy")
        detected = engine.analyze_text("Thank you so much!")  # returns "happy"
        engine.shutdown()
    """

    def __init__(self, port: str = "/dev/ttyUSB1", baudrate: int = 115200, enabled: bool = True):
        self.port = port
        self.baudrate = baudrate
        self.enabled = enabled
        self.ser = None
        self._lock = threading.Lock()
        self._current_emotion = EMOTION_NEUTRAL
        self._blink_thread = None
        self._running = False

        if self.enabled:
            self._connect()
            self._start_idle_thread()

    def _connect(self):
        """Establish serial connection to ESP32."""
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=1)
            time.sleep(2)  # ESP32 reset delay after serial open
            logger.info(f"EmotionEngine: Connected to ESP32 on {self.port}")

            # Flush any startup messages from ESP32
            while self.ser.in_waiting:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if line:
                    logger.debug(f"  ESP32: {line}")
        except serial.SerialException as e:
            logger.warning(f"EmotionEngine: ESP32 not connected ({e}) — running in dry-run mode")
            self.ser = None

    def _send_cmd(self, cmd: str):
        """Send a single character command to ESP32. Thread-safe."""
        with self._lock:
            if self.ser and self.ser.is_open:
                try:
                    self.ser.write(cmd.encode("utf-8"))
                    # Read ACK (non-blocking)
                    time.sleep(0.01)
                    while self.ser.in_waiting:
                        ack = self.ser.readline().decode("utf-8", errors="ignore").strip()
                        if ack:
                            logger.debug(f"  ESP32 ACK: {ack}")
                    return True
                except Exception as e:
                    logger.error(f"EmotionEngine send error: {e}")
                    return False
            else:
                logger.debug(f"EmotionEngine (dry-run): would send '{cmd}'")
                return False

    # ── Public API ────────────────────────────────────────────────────────────

    def set_emotion(self, emotion: str):
        """
        Set the eye emotion. Thread-safe.
        Valid emotions: neutral, happy, sad, angry, surprised, thinking, listening, speaking
        """
        emotion = emotion.lower().strip()
        cmd = _EMOTION_TO_CMD.get(emotion)
        if cmd is None:
            logger.warning(f"EmotionEngine: Unknown emotion '{emotion}'")
            return

        if emotion == self._current_emotion:
            return  # Already showing this emotion

        self._current_emotion = emotion
        self._send_cmd(cmd)
        logger.info(f"EmotionEngine: → {emotion.upper()}")

    def get_emotion(self) -> str:
        """Get the current emotion state."""
        return self._current_emotion

    def blink(self):
        """Trigger a manual blink."""
        self._send_cmd("B")

    def boot_open(self):
        """Play the boot-open eye animation (eyes open from closed)."""
        self._send_cmd("O")
        logger.info("EmotionEngine: → BOOT OPEN")

    def sleep_close(self):
        """Play the sleep-close eye animation (eyes close)."""
        self._send_cmd("X")
        self._current_emotion = EMOTION_NEUTRAL
        logger.info("EmotionEngine: → SLEEP CLOSE")

    def analyze_text(self, text: str) -> str:
        """
        Analyze text for emotional sentiment and return the detected emotion.
        Also automatically sets the eye emotion if a strong sentiment is detected.

        Returns the detected emotion string.
        """
        if not text or not text.strip():
            return self._current_emotion

        text_lower = text.lower().strip()
        scores = {emo: 0 for emo in _EMOTION_KEYWORDS}

        for emotion, keywords in _EMOTION_KEYWORDS.items():
            for keyword in keywords:
                # Use word boundary matching for single words,
                # substring matching for multi-word phrases
                if " " in keyword:
                    if keyword in text_lower:
                        scores[emotion] += 2  # Phrases are stronger signals
                else:
                    # Word boundary match (handles Hindi transliteration too)
                    pattern = r'(?:^|\s|[,!?;.])' + re.escape(keyword) + r'(?:\s|[,!?;.]|$)'
                    if re.search(pattern, text_lower):
                        scores[emotion] += 1

        # Hindi boosters
        words = set(text_lower.split())
        if words & _POSITIVE_HINDI:
            scores[EMOTION_HAPPY] += 2
        if words & _NEGATIVE_HINDI:
            scores[EMOTION_SAD] += 1
            scores[EMOTION_ANGRY] += 1

        # Exclamation marks boost surprise
        exclamation_count = text.count("!")
        if exclamation_count >= 2:
            scores[EMOTION_SURPRISED] += exclamation_count

        # Question marks in certain contexts
        question_count = text.count("?")
        if question_count >= 2:
            scores[EMOTION_SURPRISED] += 1

        # Find the strongest emotion
        max_emotion = max(scores, key=scores.get)
        max_score = scores[max_emotion]

        # Only trigger if signal is strong enough (threshold = 1)
        if max_score >= 1:
            detected = max_emotion
        else:
            detected = EMOTION_NEUTRAL

        # Auto-set the emotion on the eyes
        # Only override if not in a system state (thinking/speaking)
        if self._current_emotion not in (EMOTION_THINKING, EMOTION_SPEAKING):
            self.set_emotion(detected)

        return detected

    # ── Idle Blink Thread ─────────────────────────────────────────────────────

    def _start_idle_thread(self):
        """Start background thread for periodic idle blinks."""
        self._running = True
        self._blink_thread = threading.Thread(
            target=self._idle_loop, daemon=True, name="EmotionIdle"
        )
        self._blink_thread.start()

    def _idle_loop(self):
        """Background loop: sends periodic blink commands when idle."""
        while self._running:
            time.sleep(4.0)  # Check every 4 seconds
            # Only send idle blinks when in neutral state
            # (ESP32 has its own blink timer, but this is a fallback)
            if self._current_emotion == EMOTION_NEUTRAL:
                # Don't send blinks — ESP32 handles its own idle blinking
                # This thread exists primarily for future idle behaviors
                pass

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def shutdown(self):
        """Gracefully shut down: sleep animation + close serial."""
        self._running = False
        if self.enabled:
            self.sleep_close()
            time.sleep(0.8)  # Let the animation play
        with self._lock:
            if self.ser and self.ser.is_open:
                self.ser.close()
                logger.info("EmotionEngine: Serial port closed.")

    def reconnect(self):
        """Attempt to reconnect to ESP32 if disconnected."""
        with self._lock:
            if self.ser and self.ser.is_open:
                self.ser.close()
        self._connect()


# ── Standalone Test Mode ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB1"
    print(f"EmotionEngine Test Mode — connecting to {port}")
    print("Commands: neutral, happy, sad, angry, surprised, thinking, listening, speaking")
    print("          blink, boot, sleep, quit")
    print("Or type a sentence to test sentiment analysis.\n")

    engine = EmotionEngine(port=port, enabled=True)
    engine.boot_open()
    time.sleep(1)

    while True:
        try:
            cmd = input("emotion> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if not cmd:
            continue
        elif cmd == "quit":
            break
        elif cmd == "blink":
            engine.blink()
        elif cmd == "boot":
            engine.boot_open()
        elif cmd == "sleep":
            engine.sleep_close()
        elif cmd in _EMOTION_TO_CMD:
            engine.set_emotion(cmd)
        else:
            # Treat as a sentence to analyze
            detected = engine.analyze_text(cmd)
            print(f"  → Detected emotion: {detected}")

    engine.shutdown()
    print("Goodbye!")
