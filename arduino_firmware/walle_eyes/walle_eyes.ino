/*
 * walle_eyes.ino — WALL-E AI Expressive Emotion Eyes
 * ESP32 firmware for two 0.96" SSD1306 OLED displays.
 *
 * ── WIRING (SUPER SIMPLE) ──────────────────────────────────────
 * Wire BOTH displays to the SAME 4 pins:
 *
 *   ESP32 GPIO 21 (SDA) ──→ SDA on LEFT display
 *                        └─→ SDA on RIGHT display   ← same wire!
 *
 *   ESP32 GPIO 22 (SCL) ──→ SCL on LEFT display
 *                        └─→ SCL on RIGHT display   ← same wire!
 *
 *   ESP32 3.3V          ──→ VCC on BOTH displays
 *   ESP32 GND           ──→ GND on BOTH displays
 *
 * Both displays stay at factory default address 0x3C.
 * NO soldering. NO address change. Both show the same image.
 * ──────────────────────────────────────────────────────────────
 *
 * Connection to Raspberry Pi:
 *   Just plug ESP32 USB into Pi USB port. Done.
 *   Pi port: /dev/ttyUSB0 (or /dev/ttyUSB1, etc.)
 *
 * Serial commands from Raspberry Pi (115200 baud):
 *   N = Neutral    H = Happy    S = Sad      A = Angry
 *   U = Surprised  T = Thinking L = Listening K = Speaking
 *   B = Blink      O = Boot-open  X = Sleep-close
 *
 * Created by K.Astra and its members.
 */

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ── Display ───────────────────────────────────────────────────────────────────
#define SCREEN_WIDTH  128
#define SCREEN_HEIGHT 64
#define OLED_RESET    -1
#define OLED_ADDR     0x3C
#define SDA_PIN       21
#define SCL_PIN       22

// ONE display object — both screens wired together receive same data
Adafruit_SSD1306 eyes(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// ── Emotions ──────────────────────────────────────────────────────────────────
enum Emotion {
  EMO_NEUTRAL = 0,
  EMO_HAPPY,
  EMO_SAD,
  EMO_ANGRY,
  EMO_SURPRISED,
  EMO_THINKING,
  EMO_LISTENING,
  EMO_SPEAKING
};

// ── Eye shape parameters ──────────────────────────────────────────────────────
struct EyeParams {
  int16_t eyeX, eyeY;     // Center
  int16_t eyeW, eyeH;     // Half-width, half-height
  int16_t eyeR;           // Corner radius
  int16_t pupilX, pupilY; // Pupil offset from center
  int16_t pupilR;         // Pupil radius
  int16_t lidTop;         // Top eyelid closure (0=open)
  int16_t lidBottom;      // Bottom eyelid closure
  int16_t browAngle;      // Eyebrow angle (for angry/sad)
  bool    showBrow;       // Draw eyebrow?
};

EyeParams targetParams;
EyeParams currentParams;
EyeParams previousParams;
Emotion   currentEmotion = EMO_NEUTRAL;

// ── Timing ────────────────────────────────────────────────────────────────────
unsigned long lastFrameMs     = 0;
unsigned long lastBlinkMs     = 0;
unsigned long lastMicroMs     = 0;
unsigned long emotionStartMs  = 0;
unsigned long animStartMs     = 0;

const uint16_t FPS_MS        = 20;    // 50 FPS
const uint16_t BLINK_MIN_MS  = 2500;
const uint16_t BLINK_MAX_MS  = 5500;
const uint16_t BLINK_DUR_MS  = 150;
const uint16_t TRANSITION_MS = 250;

uint16_t nextBlink    = 3000;
bool     isBlinking   = false;
unsigned long blinkMs = 0;
float    blinkProg    = 0.0f;

// Animation floats
float speakBounce = 0.0f;
float thinkAngle  = 0.0f;
float listenPulse = 0.0f;

// Boot/sleep animation
bool  bootActive  = false;
bool  sleepActive = false;
float openProg    = 0.0f;  // 0=closed 1=open

// Idle micro-movement
int16_t microX = 0, microY = 0;

// ── Math helpers ──────────────────────────────────────────────────────────────
int16_t lerpI(int16_t a, int16_t b, float t) {
  return a + (int16_t)((float)(b - a) * t);
}
float easeIO(float t) {
  return t < 0.5f ? 2*t*t : 1 - (-2*t+2)*(-2*t+2)/2;
}

// ── Emotion definitions ───────────────────────────────────────────────────────
void setTarget(Emotion e) {
  switch (e) {
    case EMO_NEUTRAL:
      targetParams = {64,32, 28,24,10, 0,0,8, 0,0, 0,false};
      break;
    case EMO_HAPPY:
      // Eyes squint — bottom lid rises = smile look
      targetParams = {64,30, 30,20,12, 0,-2,7, 0,10, 0,false};
      break;
    case EMO_SAD:
      // Droopy eyes, sad brows
      targetParams = {64,34, 24,20,8, 0,2,6, 4,0, -15,true};
      break;
    case EMO_ANGRY:
      // Narrowed eyes, angry brows angled inward
      targetParams = {64,32, 30,18,6, 0,0,7, 6,0, 20,true};
      break;
    case EMO_SURPRISED:
      // Wide open, large pupils
      targetParams = {64,32, 34,30,14, 0,0,10, 0,0, 0,false};
      break;
    case EMO_THINKING:
      // Normal size, pupil drifts upward
      targetParams = {64,32, 26,22,10, 4,-5,7, 0,0, 0,false};
      break;
    case EMO_LISTENING:
      // Slightly wider, attentive
      targetParams = {64,32, 30,26,11, 0,0,8, 0,0, 0,false};
      break;
    case EMO_SPEAKING:
      targetParams = {64,32, 28,24,10, 0,0,8, 0,0, 0,false};
      break;
    default:
      targetParams = {64,32, 28,24,10, 0,0,8, 0,0, 0,false};
  }
}

void interpolate(float t) {
  t = constrain(t, 0.0f, 1.0f);
  float e = easeIO(t);
  currentParams.eyeX      = lerpI(previousParams.eyeX,      targetParams.eyeX,      e);
  currentParams.eyeY      = lerpI(previousParams.eyeY,      targetParams.eyeY,      e);
  currentParams.eyeW      = lerpI(previousParams.eyeW,      targetParams.eyeW,      e);
  currentParams.eyeH      = lerpI(previousParams.eyeH,      targetParams.eyeH,      e);
  currentParams.eyeR      = lerpI(previousParams.eyeR,      targetParams.eyeR,      e);
  currentParams.pupilX    = lerpI(previousParams.pupilX,    targetParams.pupilX,    e);
  currentParams.pupilY    = lerpI(previousParams.pupilY,    targetParams.pupilY,    e);
  currentParams.pupilR    = lerpI(previousParams.pupilR,    targetParams.pupilR,    e);
  currentParams.lidTop    = lerpI(previousParams.lidTop,    targetParams.lidTop,    e);
  currentParams.lidBottom = lerpI(previousParams.lidBottom, targetParams.lidBottom, e);
  currentParams.browAngle = lerpI(previousParams.browAngle, targetParams.browAngle, e);
  currentParams.showBrow  = (t > 0.5f) ? targetParams.showBrow : previousParams.showBrow;
}

void changeEmotion(Emotion e) {
  if (e == currentEmotion && !isBlinking) return;
  previousParams = currentParams;
  currentEmotion = e;
  emotionStartMs = millis();
  setTarget(e);
}

// ── Draw the eye frame ────────────────────────────────────────────────────────
void drawFrame() {
  eyes.clearDisplay();

  EyeParams &p = currentParams;
  int16_t cx = p.eyeX, cy = p.eyeY;
  int16_t hw = p.eyeW, hh = p.eyeH, cr = p.eyeR;

  // Eyelid closures from blink / boot / sleep
  int16_t lidT = p.lidTop, lidB = p.lidBottom;

  if (bootActive || sleepActive) {
    int16_t cl = (int16_t)((1.0f - openProg) * hh);
    lidT = max(lidT, cl);
    lidB = max(lidB, cl);
  }
  if (isBlinking) {
    int16_t bl = (int16_t)(blinkProg * hh);
    lidT = max(lidT, bl);
    lidB = max(lidB, bl);
  }

  // Pupil position with micro-drift
  int16_t pdx = p.pupilX + microX;
  int16_t pdy = p.pupilY + microY;

  // Speaking bounce
  int16_t bY = 0;
  if (currentEmotion == EMO_SPEAKING)
    bY = (int16_t)(sin(speakBounce) * 3.0f);

  // Thinking pupil orbit
  if (currentEmotion == EMO_THINKING) {
    pdx = (int16_t)(cos(thinkAngle) * 5.0f);
    pdy = (int16_t)(sin(thinkAngle) * 3.0f) - 2;
  }

  // Listening pulse
  int16_t pw = 0, ph = 0;
  if (currentEmotion == EMO_LISTENING) {
    pw = (int16_t)(sin(listenPulse) * 2.0f);
    ph = (int16_t)(sin(listenPulse) * 1.5f);
  }

  int16_t dW = hw + pw;
  int16_t dH = hh + ph;
  int16_t dY = cy + bY;

  // ── Filled eye shape ──────────────────────────────────────────────────────
  eyes.fillRoundRect(cx - dW, dY - dH, dW*2, dH*2, cr, SSD1306_WHITE);

  // ── Eyelid cuts ───────────────────────────────────────────────────────────
  if (lidT > 0)
    eyes.fillRect(0, 0, SCREEN_WIDTH, dY - dH + lidT, SSD1306_BLACK);
  if (lidB > 0)
    eyes.fillRect(0, dY + dH - lidB, SCREEN_WIDTH, SCREEN_HEIGHT, SSD1306_BLACK);

  // ── Pupil ─────────────────────────────────────────────────────────────────
  int16_t pcx = constrain(cx + pdx, cx - dW + p.pupilR + 2, cx + dW - p.pupilR - 2);
  int16_t pcy = constrain(dY + pdy, dY - dH + lidT + p.pupilR + 2,
                                     dY + dH - lidB - p.pupilR - 2);
  eyes.fillCircle(pcx, pcy, p.pupilR, SSD1306_BLACK);

  // Highlight dot (makes eyes look alive)
  int16_t hr = max((int16_t)1, (int16_t)(p.pupilR / 4));
  eyes.fillCircle(pcx - p.pupilR/3, pcy - p.pupilR/3, hr, SSD1306_WHITE);

  // ── Eyebrow ───────────────────────────────────────────────────────────────
  if (p.showBrow) {
    int16_t bwY  = dY - dH - 6;
    int16_t bwLen = dW - 4;
    int16_t bwDy  = p.browAngle * bwLen / 60;
    for (int i = -1; i <= 1; i++)
      eyes.drawLine(cx - bwLen, bwY - bwDy + i, cx + bwLen, bwY + bwDy + i, SSD1306_WHITE);
  }

  // ── Thinking dots ─────────────────────────────────────────────────────────
  if (currentEmotion == EMO_THINKING) {
    int phase = (millis() / 400) % 3;
    for (int i = 0; i < 3; i++) {
      eyes.fillCircle(cx - 10 + i*10, dY + dH + 8, (i == phase) ? 3 : 2, SSD1306_WHITE);
    }
  }

  eyes.display();  // Send to both displays simultaneously!
}

// ── Update all animation state ────────────────────────────────────────────────
void updateAnimations() {
  unsigned long now = millis();

  // Emotion transition
  float t = (float)(now - emotionStartMs) / TRANSITION_MS;
  if (t < 1.0f) interpolate(t);
  else           currentParams = targetParams;

  // Blink
  if (isBlinking) {
    float bt = (float)(now - blinkMs) / BLINK_DUR_MS;
    if (bt >= 1.0f) {
      isBlinking = false; blinkProg = 0.0f;
      lastBlinkMs = now;
      nextBlink = random(BLINK_MIN_MS, BLINK_MAX_MS);
    } else {
      blinkProg = (bt < 0.5f) ? bt*2.0f : 2.0f - bt*2.0f;
    }
  } else if (!bootActive && !sleepActive) {
    if (now - lastBlinkMs >= nextBlink) {
      isBlinking = true; blinkMs = now; blinkProg = 0.0f;
    }
  }

  // Micro-movement (natural idle look)
  if (now - lastMicroMs >= 3000 && currentEmotion == EMO_NEUTRAL) {
    microX = random(-2, 3);
    microY = random(-1, 2);
    lastMicroMs = now;
  }

  // Per-emotion animations
  if (currentEmotion == EMO_SPEAKING)   speakBounce += 0.25f; else speakBounce = 0;
  if (currentEmotion == EMO_THINKING) { thinkAngle  += 0.04f; if (thinkAngle > 6.283f) thinkAngle -= 6.283f; }
  if (currentEmotion == EMO_LISTENING)  listenPulse += 0.12f; else listenPulse = 0;

  // Boot open animation
  if (bootActive) {
    float bt = (float)(now - animStartMs) / 800.0f;
    if (bt >= 1.0f) { openProg = 1.0f; bootActive = false; }
    else             openProg = easeIO(bt);
  }

  // Sleep close animation
  if (sleepActive) {
    float st = (float)(now - animStartMs) / 600.0f;
    if (st >= 1.0f) { openProg = 0.0f; sleepActive = false; }
    else             openProg = 1.0f - easeIO(st);
  }
}

// ── Serial command handler ────────────────────────────────────────────────────
// Reads from USB Serial connection (Raspberry Pi or PC)
void handleCmd(char c) {
  switch (c) {
    case 'N': changeEmotion(EMO_NEUTRAL);   Serial.println("ACK:NEUTRAL");   break;
    case 'H': changeEmotion(EMO_HAPPY);     Serial.println("ACK:HAPPY");     break;
    case 'S': changeEmotion(EMO_SAD);       Serial.println("ACK:SAD");       break;
    case 'A': changeEmotion(EMO_ANGRY);     Serial.println("ACK:ANGRY");     break;
    case 'U': changeEmotion(EMO_SURPRISED); Serial.println("ACK:SURPRISED"); break;
    case 'T': changeEmotion(EMO_THINKING);  Serial.println("ACK:THINKING");  break;
    case 'L': changeEmotion(EMO_LISTENING); Serial.println("ACK:LISTENING"); break;
    case 'K': changeEmotion(EMO_SPEAKING);  Serial.println("ACK:SPEAKING");  break;
    case 'B':
      if (!isBlinking) { isBlinking = true; blinkMs = millis(); blinkProg = 0; }
      Serial.println("ACK:BLINK");
      break;
    case 'O':
      bootActive = true; sleepActive = false;
      openProg = 0.0f; animStartMs = millis();
      changeEmotion(EMO_NEUTRAL);
      Serial.println("ACK:BOOT_OPEN");
      break;
    case 'X':
      sleepActive = true; bootActive = false;
      animStartMs = millis();
      Serial.println("ACK:SLEEP_CLOSE");
      break;
    case '\n': case '\r': break;
    default:
      if (c != 0) { Serial.print("ERR:UNKNOWN:"); Serial.println(c); }
  }
}

void processSerial() {
  while (Serial.available() > 0) handleCmd(Serial.read());
}

// ── Setup ─────────────────────────────────────────────────────────────────────
void setup() {
  // USB Serial — for commands and debugging
  Serial.begin(115200);
  delay(100);

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);

  Serial.println("WALL-E Eyes: Starting...");
  Serial.println("Waiting for commands on USB Serial...");

  if (!eyes.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println("ERR: Display not found on GPIO 21/22!");
  } else {
    Serial.println("OK: Both eyes active on GPIO 21(SDA)/22(SCL).");
  }

  eyes.clearDisplay();
  eyes.display();

  setTarget(EMO_NEUTRAL);
  currentParams  = targetParams;
  previousParams = targetParams;

  bootActive  = true;
  openProg    = 0.0f;
  animStartMs = millis();

  lastBlinkMs = millis();
  lastMicroMs = millis();
  nextBlink   = random(BLINK_MIN_MS, BLINK_MAX_MS);
  randomSeed(analogRead(0));

  Serial.println("WALL-E Eyes: Ready! Waiting for Pi commands on USB...");
}

// ── Main loop ─────────────────────────────────────────────────────────────────
void loop() {
  unsigned long now = millis();
  processSerial();
  if (now - lastFrameMs < FPS_MS) return;
  lastFrameMs = now;
  updateAnimations();
  drawFrame();  // One draw call — both displays update together
}
