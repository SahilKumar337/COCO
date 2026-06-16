#include <Arduino.h>

// Arduino C++ Code: robot_control.ino
// This runs on the Arduino Uno and acts as the "Muscle"
// It listens to the USB Serial port for commands from the Raspberry Pi

void setup() {
  // Start the Serial communication at a baud rate of 115200 (fast and stable)
  Serial.begin(115200);
  
  // NOTE: Later we will configure your motor driver pins here (e.g., L298N)
  // pinMode(motorPin1, OUTPUT);
  
  Serial.println("Arduino: Ready for commands from Charlie!");
}

void loop() {
  // Check if the Raspberry Pi sent an instruction over the USB cable
  if (Serial.available() > 0) {
    char command = Serial.read(); // Read the single incoming character
    
    switch (command) {
      case 'F':
        moveForward();
        break;
      case 'B':
        moveBackward();
        break;
      case 'L':
        turnLeft();
        break;
      case 'R':
        turnRight();
        break;
      case 'S':
        stopMotors();
        break;
      case 'H':
        shakeArmToHello();
        break;
      default:
        // Ignore any other characters or line breaks (like \n)
        break;
    }
  }
}

// --- Motor & Servo Control Functions ---
// We will fill these in with exact pin numbers once we know your motor driver

void moveForward() {
  Serial.println("ACK: Moving Forward");
  // motor1_forward(HIGH); etc...
}

void moveBackward() {
  Serial.println("ACK: Moving Backward");
}

void turnLeft() {
  Serial.println("ACK: Turning Left");
}

void turnRight() {
  Serial.println("ACK: Turning Right");
}

void stopMotors() {
  Serial.println("ACK: Stopping Motors");
}

void shakeArmToHello() {
  Serial.println("ACK: Shaking Arm (Hello)");
  // servo.write(angle); etc...
}
