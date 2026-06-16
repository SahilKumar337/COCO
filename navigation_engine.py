import json
import logging
import threading
from vosk import Model, KaldiRecognizer
from serial_engine import SerialEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NavigationEngine")

class NavigationEngine(threading.Thread):
    def __init__(self, offline_audio_queue):
        super().__init__()
        self.audio_queue = offline_audio_queue
        self.running = False
        
        # Start Serial Engine silently (won't crash if Arduino is unplugged)
        self.serial_engine = SerialEngine()
        
        # Load the lightweight offline Vosk model (en-us downloads automatically)
        logger.info("Loading offline Vosk voice model...")
        try:
            self.model = Model(lang="en-us")
            self.recognizer = KaldiRecognizer(self.model, 16000) # 16kHz matches AudioEngine
            logger.info("Vosk model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load Vosk model: {e}")
            self.model = None
            
    def run(self):
        self.running = True
        logger.info("Navigation Engine: Waiting for voice commands...")
        
        while self.running:
            try:
                # Grab a chunk of raw audio from the Virtual Split offline queue
                data = self.audio_queue.get(timeout=1.0)
                
                # Check if it contains a full phrase (offline transcription)
                if self.recognizer.AcceptWaveform(data):
                    result = json.loads(self.recognizer.Result())
                    text = result.get('text', '').lower()
                    
                    if text:
                        logger.info(f"[HEARD OFFLINE] '{text}'")
                        self.process_command(text)
                        
            except Exception as e:
                # Queue is empty or timeout reached, just keep spinning
                pass

    def stop(self):
        self.running = False
        logger.info("Navigation Engine stopped.")

    def process_command(self, text: str):
        """
        Looks for wake words to physically move the robot over Serial.
        We check if the exact word exists in the transcribed sentence.
        """
        command = None
        
        # Emergency Stop takes absolute priority
        if "stop" in text:
            command = 'S'
            logger.warning("=> EXECUTING 'STOP' COMMAND")
            
        elif "forward" in text:
            command = 'F'
            logger.info("=> EXECUTING 'FORWARD' COMMAND")
            
        elif "backward" in text or "back" in text:
            command = 'B'
            logger.info("=> EXECUTING 'BACKWARD' COMMAND")
            
        elif "left" in text:
            command = 'L'
            logger.info("=> EXECUTING 'LEFT' COMMAND")
            
        elif "right" in text:
            command = 'R'
            logger.info("=> EXECUTING 'RIGHT' COMMAND")
            
        elif "hello" in text or "shake" in text:
            command = 'H'
            logger.info("=> EXECUTING 'HELLO/SHAKE' COMMAND")

        # If a command was found, send it down the USB cable to Arduino
        if command:
            self.serial_engine.send_command(command)

if __name__ == "__main__":
    from audio_engine import AudioEngine
    import time
    
    # Testing the entire offline flow
    print("\n--- Testing Virtual Split + Offline Navigation ---\n")
    
    # 1. Start the shared audio splitter
    audio_engine = AudioEngine()
    audio_engine.start()
    
    # 2. Start the Navigation listener thread
    nav_engine = NavigationEngine(audio_engine.offline_queue)
    nav_engine.start()
    
    print("\nTry speaking! Say: 'move forward', 'stop', 'turn left', etc.")
    print("Press Ctrl+C to quit.\n")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")
        nav_engine.stop()
        nav_engine.join()
        audio_engine.stop()
