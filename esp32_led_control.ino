#define BLYNK_TEMPLATE_ID "TMPL3XypukIM0"
#define BLYNK_TEMPLATE_NAME "Smart LED System"
#define BLYNK_AUTH_TOKEN "Sk6HmY3gfXDNjmIHc9UTDQNDNRnq-1iE"

#include <WiFi.h>
#include <WiFiClient.h>
#include <BlynkSimpleEsp32.h>
#include <FastLED.h>

// Enter your WiFi Credentials here
char ssid[] = "pry";
char pass[] = "priy@123";

#define BAUD_RATE   115200

#define LED_PIN     18
#define NUM_LEDS    64
#define LED_TYPE    WS2812B
#define COLOR_ORDER GRB

#define LDR_PIN     34
#define PIR_PIN     27

#define ACS712_PIN  35
#define RELAY_PIN   26

// Set to true if your relay turns ON with HIGH signal, false if it turns ON with LOW signal (active-low)
#define RELAY_ACTIVE_HIGH false

CRGB leds[NUM_LEDS];

enum SystemMode {
    MODE_NORMAL,
    MODE_STUDY,
    MODE_RELAX,
    MODE_NIGHT,
    MODE_ENERGY,
    MODE_EMERGENCY
};

SystemMode currentMode = MODE_NORMAL;
SystemMode previousMode = MODE_NORMAL;

// Sensor reporting configuration
unsigned long lastSensorSendTime = 0;
const unsigned long sensorSendInterval = 500;

// State variables
int brightness = 20;      // Reduced for safety
int previousBrightness = 20; // To store before emergency
CRGB currentColor = CRGB(255, 120, 10); // Default to light/warm orange
CRGB lastActiveColor = CRGB(255, 120, 10);
bool lightState = true;
bool securityMode = false;

bool emergencyActive = false;
bool notificationSent = false;

unsigned long emergencyStart = 0;
unsigned long emergencyCounter = 0;

//==============================
// Animation Timers
//==============================

unsigned long lastAnimationFrame = 0;
const int animationFPS = 60;
const unsigned long animationInterval = 1000 / animationFPS;
bool ledsNeedUpdate = false;

// Energy calculations variables
unsigned long lastEnergyCalcTime = 0;
double actualEnergyWh = 0.0;
double baselineEnergyWh = 0.0;
double energySavedWh = 0.0;
const double LED_VOLTAGE = 5.0;        // WS2812B works at 5V
const double BASELINE_POWER_W = 5.0;  // Estimated power draw if strip stays ON constantly (5W)
int zeroCurrentOffsetRaw = 2750;       // Will be calibrated automatically at boot

// Warm colors
CRGB warmColors[] = {
  CRGB(255, 120, 10),
  CRGB(255, 180, 25),
  CRGB(230, 45, 0),
  CRGB(255, 235, 180)
};

const int numWarmColors = 4;
int activeWarmIndex = 0;

// Dark colors
CRGB darkColors[] = {
  CRGB(0, 0, 15),
  CRGB(10, 0, 20),
  CRGB(15, 5, 0),
  CRGB(5, 5, 5)
};

const int numDarkColors = 4;
int activeDarkIndex = 0;

void activateEmergency();
void clearEmergency();
void showEmergency();
void renderCurrentMode();
void updateAnimations();
void updateBlynkDashboard();

void setup() {
  Serial.begin(BAUD_RATE);
  delay(1000);
  Serial.println("ESP32 FastLED Controller Started.");

  pinMode(LDR_PIN, INPUT);
  pinMode(PIR_PIN, INPUT);
  pinMode(RELAY_PIN, OUTPUT);

  // Initialize relay state to ON on boot based on configured polarity
  digitalWrite(RELAY_PIN, RELAY_ACTIVE_HIGH ? HIGH : LOW);

  FastLED.addLeds<LED_TYPE, LED_PIN, COLOR_ORDER>(leds, NUM_LEDS).setCorrection(TypicalLEDStrip);
  FastLED.setBrightness(brightness);
  fill_solid(leds, NUM_LEDS, currentColor);
  FastLED.show();

  currentMode = MODE_NORMAL;
  previousMode = MODE_NORMAL;
  emergencyActive = false;
  notificationSent = false;
  securityMode = false;

  // Start WiFi connection (non-blocking, attempts connection in background)
  WiFi.begin(ssid, pass);
  Blynk.config(BLYNK_AUTH_TOKEN);

  // Calibrate ACS712 current sensor (average 50 samples at startup while light is stable)
  long acsSum = 0;
  for (int i = 0; i < 50; i++) {
    acsSum += analogRead(ACS712_PIN);
    delay(10);
  }
  zeroCurrentOffsetRaw = acsSum / 50;
  Serial.print("ACS712 Calibrated Offset Raw: ");
  Serial.println(zeroCurrentOffsetRaw);
}

void renderCurrentMode() {
    if (millis() - lastAnimationFrame < animationInterval) return;
    
    switch(currentMode) {
        case MODE_EMERGENCY:
            if (emergencyActive) showEmergency();
            break;
        default:
            break; // Static modes preserve colors, updated in parsers
    }
}

void updateAnimations() {
    if (millis() - lastAnimationFrame >= animationInterval) {
        lastAnimationFrame = millis();
        if (ledsNeedUpdate) {
            FastLED.show();
            ledsNeedUpdate = false;
        }
    }
}

void activateEmergency() {
    if (!emergencyActive) {
        previousMode = currentMode;
        previousBrightness = brightness;
        currentMode = MODE_EMERGENCY;
        emergencyActive = true;
        emergencyStart = millis();
        notificationSent = false;
        brightness = 255;
        FastLED.setBrightness(255);
        fill_solid(leds, NUM_LEDS, CRGB::Red);
        digitalWrite(RELAY_PIN, RELAY_ACTIVE_HIGH ? HIGH : LOW);
        lightState = true;
        Blynk.logEvent("emergency_alert");
        emergencyCounter++;
        ledsNeedUpdate = true;
    }
}

void clearEmergency() {
    emergencyActive = false;
    notificationSent = false;
    currentMode = previousMode;
    currentColor = lastActiveColor;
    brightness = previousBrightness;
    FastLED.setBrightness(brightness);
    if (lightState) {
        fill_solid(leds, NUM_LEDS, currentColor);
    } else {
        fill_solid(leds, NUM_LEDS, CRGB::Black);
    }
    ledsNeedUpdate = true;
}

void showEmergency() {
    FastLED.setBrightness(255);
    fill_solid(leds, NUM_LEDS, CRGB::Red);
    ledsNeedUpdate = true;
}

void updateBlynkDashboard() {
    static unsigned long lastDashboardSync = 0;
    if (millis() - lastDashboardSync >= 1000) {
        lastDashboardSync = millis();
        if (WiFi.status() == WL_CONNECTED && Blynk.connected()) {
            Blynk.virtualWrite(V21, emergencyActive ? 1 : 0);
            Blynk.virtualWrite(V26, brightness);
            Blynk.virtualWrite(V27, (int)currentMode);
            Blynk.virtualWrite(V29, emergencyCounter);
        }
    }
}

void loop() {
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    if (cmd.length() > 0) {
      Serial.print("Received command: ");
      Serial.println(cmd);

      if (cmd.startsWith("HSV,")) {
        int firstComma = cmd.indexOf(',');
        int secondComma = cmd.indexOf(',', firstComma + 1);
        int thirdComma = cmd.indexOf(',', secondComma + 1);

        if (firstComma != -1 && secondComma != -1 && thirdComma != -1) {
          int h = cmd.substring(firstComma + 1, secondComma).toInt();
          int s = cmd.substring(secondComma + 1, thirdComma).toInt();
          int v = cmd.substring(thirdComma + 1).toInt();
          currentColor = CHSV(constrain(h, 0, 255), constrain(s, 0, 255), constrain(v, 0, 255));
          if (h != 0 || s != 0 || v != 0) lastActiveColor = currentColor;
          if (lightState) {
            fill_solid(leds, NUM_LEDS, currentColor);
            ledsNeedUpdate = true;
          }
        }
      }
      else if (cmd.equalsIgnoreCase("RED")) {
        currentColor = CRGB::Red;
        lastActiveColor = currentColor;
        if (lightState) {
          fill_solid(leds, NUM_LEDS, currentColor);
          ledsNeedUpdate = true;
        }
      }
      else if (cmd.equalsIgnoreCase("GREEN")) {
        currentColor = CRGB::Green;
        lastActiveColor = currentColor;
        if (lightState) {
          fill_solid(leds, NUM_LEDS, currentColor);
          ledsNeedUpdate = true;
        }
      }
      else if (cmd.equalsIgnoreCase("BLUE")) {
        currentColor = CRGB::Blue;
        lastActiveColor = currentColor;
        if (lightState) {
          fill_solid(leds, NUM_LEDS, currentColor);
          ledsNeedUpdate = true;
        }
      }
      else if (cmd.equalsIgnoreCase("WARM")) {
        currentColor = warmColors[activeWarmIndex];
        activeWarmIndex = (activeWarmIndex + 1) % numWarmColors;
        lastActiveColor = currentColor;
        if (lightState) {
          fill_solid(leds, NUM_LEDS, currentColor);
          ledsNeedUpdate = true;
        }
      }
      else if (cmd.equalsIgnoreCase("DARK")) {
        currentColor = darkColors[activeDarkIndex];
        activeDarkIndex = (activeDarkIndex + 1) % numDarkColors;
        lastActiveColor = currentColor;
        if (lightState) {
          fill_solid(leds, NUM_LEDS, currentColor);
          ledsNeedUpdate = true;
        }
      }
      else if (cmd.equalsIgnoreCase("MODE_STUDY")) {
        currentColor = CRGB::White;
        brightness = 255;
        lastActiveColor = currentColor;
        if (lightState) {
          FastLED.setBrightness(brightness);
          fill_solid(leds, NUM_LEDS, currentColor);
          ledsNeedUpdate = true;
        }
        currentMode = MODE_STUDY;
        Serial.println("Mode: STUDY");
      }
      else if (cmd.equalsIgnoreCase("MODE_RELAX")) {
        currentColor = CRGB::Blue;
        brightness = 150;
        lastActiveColor = currentColor;
        if (lightState) {
          FastLED.setBrightness(brightness);
          fill_solid(leds, NUM_LEDS, currentColor);
          ledsNeedUpdate = true;
        }
        currentMode = MODE_RELAX;
        Serial.println("Mode: RELAX");
      }
      else if (cmd.equalsIgnoreCase("MODE_NIGHT")) {
        currentColor = CRGB(255, 120, 0); // Warm yellow
        brightness = 20;
        lastActiveColor = currentColor;
        if (lightState) {
          FastLED.setBrightness(brightness);
          fill_solid(leds, NUM_LEDS, currentColor);
          ledsNeedUpdate = true;
        }
        currentMode = MODE_NIGHT;
        Serial.println("Mode: NIGHT");
      }
      else if(cmd.equalsIgnoreCase("MODE_EMERGENCY")) {
        activateEmergency();
      }
      else if(cmd.equalsIgnoreCase("EMERGENCY_CLEAR")) {
        clearEmergency();
      }
      else if (cmd.equalsIgnoreCase("LIGHT_OFF")) {
        lightState = false;
        currentMode = MODE_NORMAL;
        fill_solid(leds, NUM_LEDS, CRGB::Black);
        ledsNeedUpdate = true;
      }
      else if (cmd.equalsIgnoreCase("LIGHT_ON")) {
        lightState = true;
        currentMode = previousMode;
        currentColor = lastActiveColor;
        fill_solid(leds, NUM_LEDS, currentColor);
        ledsNeedUpdate = true;
      }
      else if (cmd.equalsIgnoreCase("RELAY_ON")) {
        digitalWrite(RELAY_PIN, RELAY_ACTIVE_HIGH ? HIGH : LOW);
        Serial.println("Relay ON");
      }
      else if (cmd.equalsIgnoreCase("RELAY_OFF")) {
        digitalWrite(RELAY_PIN, RELAY_ACTIVE_HIGH ? LOW : HIGH);
        Serial.println("Relay OFF");
      }
      else if (cmd.startsWith("BRIGHTNESS,")) {
        int firstComma = cmd.indexOf(',');
        if (firstComma != -1) {
          int val = cmd.substring(firstComma + 1).toInt();
          brightness = constrain(val, 5, 255);
          FastLED.setBrightness(brightness);
          ledsNeedUpdate = true;
          Serial.print("New Brightness: ");
          Serial.println(brightness);
        }
      }
      else if (cmd.equalsIgnoreCase("BRIGHTNESS_UP")) {
        brightness = constrain(brightness + 60, 5, 255);
        FastLED.setBrightness(brightness);
        ledsNeedUpdate = true;
        Serial.print("New Brightness: ");
        Serial.println(brightness);
      }
      else if (cmd.equalsIgnoreCase("BRIGHTNESS_DOWN")) {
        brightness = constrain(brightness - 60, 5, 255);
        FastLED.setBrightness(brightness);
        ledsNeedUpdate = true;
        Serial.print("New Brightness: ");
        Serial.println(brightness);
      }
    }
  }

  unsigned long currentMillis = millis();

  if (WiFi.status() == WL_CONNECTED) {
    Blynk.run();
  }

  renderCurrentMode();
  updateAnimations();
  updateBlynkDashboard();

  if (currentMillis - lastSensorSendTime >= 1000) {
    double timeStepHours = (currentMillis - lastSensorSendTime) / 3600000.0;
    lastSensorSendTime = currentMillis;

    int ldrVal = digitalRead(LDR_PIN);
    int pirVal = digitalRead(PIR_PIN);
    
    if (pirVal == 1 && !emergencyActive) {
        bool relayOff = (digitalRead(RELAY_PIN) == (RELAY_ACTIVE_HIGH ? LOW : HIGH));
        if (securityMode || relayOff || !lightState) {
            activateEmergency();
        }
    }
    
    int acsVal = analogRead(ACS712_PIN);
    double rawDifference = abs(acsVal - zeroCurrentOffsetRaw);
    if (rawDifference < 15.0) rawDifference = 0.0;
    double acsVoltage = (rawDifference / 4095.0) * 3.3;
    double currentAmps = acsVoltage / 0.066; 

    baselineEnergyWh += BASELINE_POWER_W * timeStepHours;
    if (lightState) {
      double actualPowerW = LED_VOLTAGE * currentAmps;
      actualEnergyWh += actualPowerW * timeStepHours;
    }

    energySavedWh = baselineEnergyWh - actualEnergyWh;
    if (energySavedWh < 0) energySavedWh = 0;

    Serial.print("SENSOR,");
    Serial.print(ldrVal);
    Serial.print(",");
    Serial.print(pirVal);
    Serial.print(",");
    Serial.println(acsVal);

    if (WiFi.status() == WL_CONNECTED && Blynk.connected()) {
      Blynk.virtualWrite(V1, lightState ? 1 : 0);
      Blynk.virtualWrite(V2, ldrVal ? 255 : 0);      
      Blynk.virtualWrite(V3, pirVal ? 255 : 0);      
      Blynk.virtualWrite(V4, currentAmps * 1000.0); 
      Blynk.virtualWrite(V5, energySavedWh);         
    }
  }

}

BLYNK_WRITE(V1) {
  int value = param.asInt();
  if (value == 1) {
    lightState = true;
    digitalWrite(RELAY_PIN, RELAY_ACTIVE_HIGH ? HIGH : LOW);
    currentColor = lastActiveColor;
    fill_solid(leds, NUM_LEDS, currentColor);
    ledsNeedUpdate = true;
  } else {
    lightState = false;
    digitalWrite(RELAY_PIN, RELAY_ACTIVE_HIGH ? LOW : HIGH);
    fill_solid(leds, NUM_LEDS, CRGB::Black);
    ledsNeedUpdate = true;
  }
}

BLYNK_WRITE(V30) {
    securityMode = param.asInt() ? true : false;
}   
