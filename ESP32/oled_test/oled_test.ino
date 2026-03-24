/*
 * OLED Display Test Sketch
 * ========================
 * Tests if your SSD1306 OLED is working.
 * 
 * Wiring:
 *   GND → GND
 *   VDD → 3.3V
 *   SCK → GPIO 22
 *   SDA → GPIO 21
 */

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define SCREEN_WIDTH  128
#define SCREEN_HEIGHT 64
#define OLED_RESET    -1

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

void setup() {
  Serial.begin(115200);
  Serial.println("\n=== OLED Display Test ===\n");

  // --- Step 1: I2C Scanner ---
  Wire.begin(21, 22);  // SDA=21, SCL=22
  Serial.println("Scanning I2C bus...");
  
  int devicesFound = 0;
  uint8_t oledAddress = 0;
  
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      Serial.printf("  Found device at 0x%02X\n", addr);
      devicesFound++;
      if (addr == 0x3C || addr == 0x3D) {
        oledAddress = addr;
      }
    }
  }
  
  if (devicesFound == 0) {
    Serial.println("  ❌ NO I2C devices found!");
    Serial.println("  Check wiring:");
    Serial.println("    SDA → GPIO 21");
    Serial.println("    SCK → GPIO 22");
    Serial.println("    VDD → 3.3V");
    Serial.println("    GND → GND");
    while (true) delay(1000);  // Stop here
  }
  
  if (oledAddress == 0) {
    Serial.println("  ⚠️  No OLED at 0x3C or 0x3D");
    Serial.println("  Trying 0x3C anyway...");
    oledAddress = 0x3C;
  } else {
    Serial.printf("  ✅ OLED found at 0x%02X\n", oledAddress);
  }
  
  // --- Step 2: Initialize Display ---
  Serial.println("\nInitializing display...");
  if (!display.begin(SSD1306_SWITCHCAPVCC, oledAddress)) {
    Serial.println("  ❌ SSD1306 init FAILED!");
    while (true) delay(1000);
  }
  Serial.println("  ✅ Display initialized!\n");

  // --- Step 3: Show Test Pattern ---
  display.clearDisplay();
  
  // Header
  display.setTextSize(2);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(10, 2);
  display.println("SmartVend");
  
  // Divider line
  display.drawLine(0, 20, 127, 20, SSD1306_WHITE);
  
  // Status text
  display.setTextSize(1);
  display.setCursor(20, 28);
  display.println("Display OK!");
  
  // Draw a small rectangle
  display.drawRect(10, 42, 108, 18, SSD1306_WHITE);
  display.setCursor(18, 48);
  display.println("OLED Working :)");
  
  display.display();
  
  Serial.println("=========================");
  Serial.println("  ✅ TEST PASSED!");
  Serial.println("  You should see text on");
  Serial.println("  the OLED display now.");
  Serial.println("=========================");
}

void loop() {
  // Blink a pixel to prove display is alive
  static bool blink = false;
  blink = !blink;
  display.drawPixel(124, 3, blink ? SSD1306_WHITE : SSD1306_BLACK);
  display.display();
  delay(500);
}
