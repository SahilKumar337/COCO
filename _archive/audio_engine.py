import queue
import logging
import sounddevice as sd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AudioEngine")

class AudioEngine:
    def __init__(self, samplerate=16000, channels=1):
        self.samplerate = samplerate
        self.channels = channels
        
        # The Virtual Split: Two separate queues for the same audio
        self.offline_queue = queue.Queue()  # For Navigation / Arduino
        self.online_queue = queue.Queue()  
        
        self.stream = None
    def audio_callback(self, indata, frames, time, status):
        """
        This is called for each audio block by sounddevice.
        It instantly duplicates the audio data into both queues.
        """
        if status:
            logger.warning(f"Audio status: {status}")
            
        # Put the raw byte data into both queues
        self.offline_queue.put(bytes(indata))
        self.online_queue.put(bytes(indata))

    def start(self):
        """Starts the microphone stream."""
        try:
            self.stream = sd.RawInputStream(
                samplerate=self.samplerate,
                blocksize=8000, # 0.5 seconds chunks
                dtype='int16',  # 16-bit PCM (Required by Vosk)
                channels=self.channels,
                callback=self.audio_callback
            )
            self.stream.start()
            logger.info("Microphone stream started. Virtual Split active.")
        except Exception as e:
            logger.error(f"Failed to start microphone: {e}")

    def stop(self):
        """Stops the microphone stream."""
        if self.stream:
            self.stream.stop()
            self.stream.close()
            logger.info("Microphone stream stopped.")

if __name__ == "__main__":
    # Test the virtual split
    engine = AudioEngine()
    engine.start()
    print("Listening... Press Ctrl+C to stop.")
    try:
        import time
        while True:
            time.sleep(1)
            # Just to show it's pulling data
            print(f"Queue sizes -> Offline: {engine.offline_queue.qsize()}, Online: {engine.online_queue.qsize()}")
    except KeyboardInterrupt:
        engine.stop()
