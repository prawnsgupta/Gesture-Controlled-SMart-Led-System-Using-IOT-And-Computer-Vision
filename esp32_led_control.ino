/*
  ESP32 Smart LED System Controller (FastLED Version)
  
  This sketch runs on the ESP32. It listens for commands over the Serial 
  interface (baud rate 115200) sent by the MediaPipe Python script:
    - "HSV,h,s,v": Set LED color using custom Hue, Saturation, Value inputs (0-255)
    - "WARM": Set LED color to a warm orange/tungsten color (cycles through warm colors)
    - "DARK": Set LED color to a dark color (cycles through dark colors)
    - "LIGHT_OFF": Turn off the LEDs (keeping current color state)
    - "LIGHT_ON": Turn on the LEDs (restoring the previous active color)
    - "BRIGHTNESS_UP": Increase LED brightness
    - "BRIGHTNESS_DOWN": Decrease LED brightness
*/

#include <FastLED.h>

#define BAUD_RATE   115200
#define LED_PIN     18         // Data In pin connected to GPIO 18
#define NUM_LEDS    60         // Set to 60 to ensure all LEDs on the strip glow (was 30, which left 50% dark)
#define LED_TYPE    WS2812B
#define COLOR_ORDER GRB

CRGB leds[NUM_LEDS];

// State variables
int brightness = 30;           // Initial brightness set to 30 as requested
CRGB currentColor = CRGB::Blue; // Default color
CRGB lastActiveColor = CRGB::Blue; // Keep track of last non-black color
bool lightState = true;         // True if light is ON, False if light is OFF

// Color cycle tables
CRGB warmColors[] = {
  CRGB(255, 120, 10),   // Warm Amber / Orange
  CRGB(255, 180, 25),   // Warm Yellow
  CRGB(230, 45, 0),     // Warm Red-Orange
  CRGB(255, 235, 180)   // Soft Warm White
};
const int numWarmColors = 4;
int activeWarmIndex = 0;

CRGB darkColors[] = {
  CRGB(0, 0, 15),       // Very Dim Blue
  CRGB(10, 0, 20),      // Very Dim Indigo
  CRGB(15, 5, 0),       // Very Dim Amber
  CRGB(5, 5, 5)         // Very Dim White
};
const int numDarkColors = 4;
int activeDarkIndex = 0;

void setup() {
  Serial.begin(BAUD_RATE);
  while (!Serial) {
    ; // Wait for serial port to connect
  }
  Serial.println("ESP32 FastLED Controller Started.");

  // Initialize FastLED with WS2812B configuration
  FastLED.addLeds<LED_TYPE, LED_PIN, COLOR_ORDER>(leds, NUM_LEDS).setCorrection(TypicalLEDStrip);
  
  // Set initial brightness
  FastLED.setBrightness(brightness);
  
  // Set initial color (Blue)
  fill_solid(leds, NUM_LEDS, currentColor);
  FastLED.show();
}

void loop() {
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim(); // Remove whitespace or carriage returns
    
    if (cmd.length() > 0) {
      Serial.print("Received command: ");
      Serial.println(cmd);
      
      if (cmd.startsWith("HSV,")) {
        // Parse HSV values: cmd format is "HSV,h,s,v"
        int firstComma = cmd.indexOf(',');
        int secondComma = cmd.indexOf(',', firstComma + 1);
        int thirdComma = cmd.indexOf(',', secondComma + 1);
        
        if (firstComma != -1 && secondComma != -1 && thirdComma != -1) {
          int h = cmd.substring(firstComma + 1, secondComma).toInt();
          int s = cmd.substring(secondComma + 1, thirdComma).toInt();
          int v = cmd.substring(thirdComma + 1).toInt();
          
          h = constrain(h, 0, 255);
          s = constrain(s, 0, 255);
          v = constrain(v, 0, 255);
          
          currentColor = CHSV(h, s, v);
          
          // Only update lastActiveColor if it's not completely black
          if (h != 0 || s != 0 || v != 0) {
            lastActiveColor = currentColor;
          }
          
          if (lightState) {
            fill_solid(leds, NUM_LEDS, currentColor);
            FastLED.show();
          }
        }
      }
      else if (cmd.equalsIgnoreCase("RED")) {
        currentColor = CRGB::Red;
        lastActiveColor = currentColor;
        if (lightState) {
          fill_solid(leds, NUM_LEDS, currentColor);
          FastLED.show();
        }
      } 
      else if (cmd.equalsIgnoreCase("GREEN")) {
        currentColor = CRGB::Green;
        lastActiveColor = currentColor;
        if (lightState) {
          fill_solid(leds, NUM_LEDS, currentColor);
          FastLED.show();
        }
      } 
      else if (cmd.equalsIgnoreCase("BLUE")) {
        currentColor = CRGB::Blue;
        lastActiveColor = currentColor;
        if (lightState) {
          fill_solid(leds, NUM_LEDS, currentColor);
          FastLED.show();
        }
      }
      else if (cmd.equalsIgnoreCase("WARM")) {
        // Cycle through warm colors
        currentColor = warmColors[activeWarmIndex];
        activeWarmIndex = (activeWarmIndex + 1) % numWarmColors;
        lastActiveColor = currentColor;
        if (lightState) {
          fill_solid(leds, NUM_LEDS, currentColor);
          FastLED.show();
        }
      }
      else if (cmd.equalsIgnoreCase("DARK")) {
        // Cycle through dark colors
        currentColor = darkColors[activeDarkIndex];
        activeDarkIndex = (activeDarkIndex + 1) % numDarkColors;
        lastActiveColor = currentColor;
        if (lightState) {
          fill_solid(leds, NUM_LEDS, currentColor);
          FastLED.show();
        }
      }
      else if (cmd.equalsIgnoreCase("LIGHT_OFF")) {
        lightState = false;
        fill_solid(leds, NUM_LEDS, CRGB::Black);
        FastLED.show();
      }
      else if (cmd.equalsIgnoreCase("LIGHT_ON")) {
        lightState = true;
        currentColor = lastActiveColor;
        fill_solid(leds, NUM_LEDS, currentColor);
        FastLED.show();
      }
      else if (cmd.startsWith("BRIGHTNESS,")) {
        int firstComma = cmd.indexOf(',');
        if (firstComma != -1) {
          int val = cmd.substring(firstComma + 1).toInt();
          brightness = constrain(val, 5, 255);
          FastLED.setBrightness(brightness);
          FastLED.show();
          Serial.print("New Brightness: "); Serial.println(brightness);
        }
      }
      else if (cmd.equalsIgnoreCase("BRIGHTNESS_UP")) {
        // Increase brightness in steps, keeping it within 5 to 255
        brightness = constrain(brightness + 25, 5, 255);
        FastLED.setBrightness(brightness);
        FastLED.show();
        Serial.print("New Brightness: "); Serial.println(brightness);
      } 
      else if (cmd.equalsIgnoreCase("BRIGHTNESS_DOWN")) {
        // Decrease brightness in steps, keeping it within 5 to 255
        brightness = constrain(brightness - 25, 5, 255);
        FastLED.setBrightness(brightness);
        FastLED.show();
        Serial.print("New Brightness: "); Serial.println(brightness);
      }
    }
  }
}

