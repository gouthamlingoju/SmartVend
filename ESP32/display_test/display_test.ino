/*
 * SmartVend — TFT Display Test v3 (Force parallel verification)
 *kkk
 * The library build may have been cached with old SPI config.
 * This sketch forces a recompile by changing the main file.
 *
 * Pins:
 *   LCD_CS=27  LCD_DC=14  LCD_RST=26  LCD_WR=12  LCD_RD=13
 *   D0=16 D1=4 D2=23 D3=22 D4=21 D5=19 D6=18 D7=17
 *   5V=VIN  GND=GND
 */

#include <TFT_eSPI.h>

// Compile-time check that parallel mode is actually enabled
#ifndef TFT_PARALLEL_8_BIT
  #error "PARALLEL MODE NOT ENABLED! User_Setup.h not loaded correctly."
#endif

#ifndef ESP32_PARALLEL
  #error "ESP32_PARALLEL not defined — library config not applied!"
#endif

TFT_eSPI tft = TFT_eSPI();

void setup() {
  Serial.begin(115200);
  delay(2000);

  Serial.println("\n=== TFT Test v3 ===");
  Serial.printf("TFT_CS  = %d\n", TFT_CS);
  Serial.printf("TFT_DC  = %d\n", TFT_DC);
  Serial.printf("TFT_RST = %d\n", TFT_RST);
  Serial.printf("TFT_WR  = %d\n", TFT_WR);
  Serial.printf("TFT_RD  = %d\n", TFT_RD);
  Serial.printf("D0=%d D1=%d D2=%d D3=%d\n", TFT_D0,TFT_D1,TFT_D2,TFT_D3);
  Serial.printf("D4=%d D5=%d D6=%d D7=%d\n", TFT_D4,TFT_D5,TFT_D6,TFT_D7);
  Serial.println("[OK] Parallel mode confirmed at compile time");

  // Manual RST pulse
  pinMode(TFT_RST, OUTPUT);
  digitalWrite(TFT_RST, HIGH); delay(5);
  digitalWrite(TFT_RST, LOW);  delay(20);
  digitalWrite(TFT_RST, HIGH); delay(150);
  Serial.println("[RST] Done");

  tft.init();
  tft.setRotation(0);
  Serial.println("[INIT] Done");

  Serial.println("[TEST] Filling BLACK");
  tft.fillScreen(TFT_BLACK);
  delay(1000);

  Serial.println("[TEST] Filling RED");
  tft.fillScreen(TFT_RED);
  delay(1000);

  Serial.println("[TEST] Filling GREEN");
  tft.fillScreen(TFT_GREEN);
  delay(1000);

  Serial.println("[TEST] Filling BLUE");
  tft.fillScreen(TFT_BLUE);
  delay(1000);

  Serial.println("[TEST] Drawing text");
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextSize(3);
  tft.setCursor(30, 140);
  tft.print("WORKING!");

  Serial.println("[DONE] Setup complete");
}

void loop() {
  static unsigned long last = 0;
  if (millis() - last > 2000) {
    Serial.println("[ALIVE] Loop running...");
    last = millis();
  }
}
