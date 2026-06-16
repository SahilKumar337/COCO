import serial
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SerialEngine")

class SerialEngine:
    def __init__(self, port='/dev/ttyACM0', baudrate=115200):
        """
        Initializes the communication with the Arduino.
        Note: The port might be /dev/ttyUSB0 depending on the Arduino connection.
        """
        self.port = port
        self.baudrate = baudrate
        self.ser = None
        self.connect()

    def connect(self):
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=1)
            time.sleep(2)  # Give the Arduino 2 seconds to reset after connection
            logger.info(f"Successfully connected to Arduino on {self.port}")
        except serial.SerialException as e:
            logger.error(f"Failed to connect to Arduino: {e}")
            self.ser = None

    def send_command(self, command: str):
        """
        Sends a single character command ('F', 'B', 'S', etc.) to the Arduino.
        """
        if self.ser is None or not self.ser.is_open:
            logger.warning("Serial connection is not open. Attempting to reconnect...")
            self.connect()
            if self.ser is None:
                return False
        
        try:
            # Send the command encoded as bytes
            self.ser.write(command.encode('utf-8'))
            logger.info(f"Sent command: {command}")
            return True
        except Exception as e:
            logger.error(f"Error sending command: {e}")
            return False

if __name__ == "__main__":
    # Quick test when running this file directly
    print("Testing SerialEngine. Ensure Arduino is plugged in.")
    engine = SerialEngine()
    
    # Test sending a few commands
    print("Sending Forward command...")
    engine.send_command('F')
    time.sleep(1)
    
    print("Sending Stop command...")
    engine.send_command('S')
