/*
 * SmartVend ESP32 Firmware v3.1 — QR-Based Session System
 * ========================================================
 *
 * Hardware:
 *   - ESP32 DevKit V1
 *   - 2.4" ILI9341 TFT LCD (240×320px) — 8-bit parallel interface via UNO shield adapter
 *   - L298N Motor Driver (ENA=25, IN1=32, IN2=33)
 *   - Current sensor on GPIO34 for jam detection
 *   - Built-in LED on GPIO2
 *
 * v3.1 Changes from v3.0:
 *   - 2.4" ILI9341 TFT (240×320) replaces 0.96" OLED SSD1306 (128×64)
 *   - Library: TFT_eSPI (configured for ILI9341 8-bit parallel)
 *   - Fullscreen color UI — green idle, orange in-use, blue dispensing, red error
 *   - Larger QR code (up to 200×200px on screen)
 *   - Text is readable from a distance
 *
 * Libraries required (install via Arduino Library Manager):
 *   1. TFT_eSPI  (configure User_Setup.h for ILI9341 8-bit parallel)
 *   2. QRCode by ricmoo  (https://github.com/ricmoo/QRCode)
 *   3. WebSocketsClient
 *   4. ArduinoJson
 *   5. WebServer (built-in)
 *   6. esp_task_wdt (built-in)
 *
 * IMPORTANT — TFT_eSPI User_Setup.h config needed:
 *   #define ILI9341_DRIVER
 *   #define TFT_PARALLEL_8_BIT
 *   #define TFT_CS   27
 *   #define TFT_DC   14
 *   #define TFT_RST  26
 *   #define TFT_WR   12
 *   #define TFT_RD   13
 *   #define TFT_D0   16
 *   #define TFT_D1    4
 *   #define TFT_D2   23
 *   #define TFT_D3   22
 *   #define TFT_D4   21
 *   #define TFT_D5   19
 *   #define TFT_D6   18
 *   #define TFT_D7   17
 *   #define TFT_WIDTH  240
 *   #define TFT_HEIGHT 320
 */

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WebServer.h>
#include <esp_task_wdt.h>

// TFT Display (ILI9341 via TFT_eSPI)
#include <TFT_eSPI.h>

// QR Code generation
#include "qrcode.h"

// ══════════════════════════════════════════════
//  CONFIGURATION
// ══════════════════════════════════════════════

struct WiFiNetwork {
  const char *ssid;
  const char *password;
};

WiFiNetwork networks[] = {
  {"Goutham's Galaxy", "23456789"},
  {"VNRVJIET_WIFI",    "vnrvjiet@123"},
  {"VNRVJIET_E",       "vnrvjiet@123"}
};
const int networkCount = sizeof(networks) / sizeof(networks[0]);

// Server
const char *serverHost  = "smartvend.onrender.com";
const char *serverHttps = "https://smartvend.onrender.com";
const int   serverPort  = 443;
const char *serverPath  = "/ws";

// Machine identity
const char *machine_id      = "M001";
const char *machine_api_key = "sv_001mmsg";

// ══════════════════════════════════════════════
//  HARDWARE PINS
// ══════════════════════════════════════════════

// Motor Driver (L298N)
const int ENA = 25;
const int IN1 = 32;
const int IN2 = 33;
// NOTE: GPIO26/GPIO27 are reserved for TFT RST/CS in this build.

// LED
const int LED_BUILTIN_PIN = 2;

// Jam Detection (analog current sensor)
const int JAM_SENSOR_PIN        = 34;
const int JAM_CURRENT_THRESHOLD = 800;
const int JAM_DURATION_THRESHOLD = 200;

// TFT Screen dimensions (ILI9341 portrait)
#define SCREEN_W 240
#define SCREEN_H 320
#define QR_VERSION_MIN 8
#define QR_VERSION_MAX 12

// ── Colour palette ──────────────────────────
#define C_BG_IDLE       0x0841   // Deep navy blue
#define C_BG_INUSE      0xA200   // Deep orange-red
#define C_BG_DISPENSE   0x0410   // Deep blue-green
#define C_BG_COMPLETED  0x0480   // Deep green
#define C_BG_ERROR      0xA000   // Deep red
#define C_BG_OFFLINE    0x39C7   // Dark slate
#define C_BG_BOOT       0x18C3   // Very dark blue
#define C_WHITE         TFT_WHITE
#define C_ACCENT        0x07FF   // Cyan
#define C_YELLOW        TFT_YELLOW
#define C_GREEN         0x07E0
#define C_ORANGE        TFT_ORANGE

// ══════════════════════════════════════════════
//  STATE MACHINE
// ══════════════════════════════════════════════

enum DeviceState {
  STATE_BOOTING,
  STATE_IDLE,
  STATE_IN_USE,
  STATE_DISPENSING,
  STATE_COMPLETED,
  STATE_ERROR,
  STATE_OFFLINE
};

DeviceState state = STATE_BOOTING;

// ══════════════════════════════════════════════
//  GLOBAL VARIABLES
// ══════════════════════════════════════════════

WebSocketsClient webSocket;
WebServer server(80);
WiFiClientSecure secureClient;
TFT_eSPI tft = TFT_eSPI();

// Session
String currentSessionToken = "";
String currentSessionUrl   = "";
String currentExpiresAt    = "";
String claimedByName       = "";

// Motor
bool motorRunning = false;
unsigned long motorStartTime    = 0;
unsigned long motorRunDuration  = 0;
unsigned long dispenseQuantity  = 0;
String currentTransactionId     = "";
unsigned long jamStartTime      = 0;

// Timing constants
const unsigned long BASE_RUN_TIME         = 4000;
const unsigned long LOCK_TIMEOUT          = 600000;
const unsigned long WIFI_CHECK_INTERVAL   = 30000;
const unsigned long HEARTBEAT_INTERVAL    = 30000;
const unsigned long COMMAND_POLL_INTERVAL = 15000;
const unsigned long COMPLETED_FLASH_MS   = 2000;

// Timing trackers
unsigned long lastHeartbeat      = 0;
unsigned long lastCommandPoll    = 0;
unsigned long lastWiFiCheck      = 0;
unsigned long stateEnteredAt     = 0;
unsigned long completedFlashStart = 0;

// Manual motor (web panel)
int  manualMotorSpeed  = 200;
bool manualMotorControl = false;

// Display cache (for web panel JSON)
String displayLine1 = "";
String displayLine2 = "";

// ══════════════════════════════════════════════
//  TFT HELPER UTILITIES
// ══════════════════════════════════════════════

// Draw a centered string at a given y, with given text size and color
void drawCentered(const char *text, int y, uint8_t sz, uint16_t color) {
  tft.setTextSize(sz);
  tft.setTextColor(color, tft.textcolor);  // transparent bg workaround
  // Calculate pixel width: each char is 6*sz pixels wide
  int txtW = strlen(text) * 6 * sz;
  int x = (SCREEN_W - txtW) / 2;
  if (x < 0) x = 0;
  tft.setCursor(x, y);
  tft.print(text);
}

// Draw a reusable header bar at the top (50px tall)
void drawHeader(uint16_t bgColor) {
  tft.fillRect(0, 0, SCREEN_W, 50, C_ACCENT);
  tft.setTextColor(TFT_BLACK);
  tft.setTextSize(3);
  int txtW = 9 * 6 * 3;  // "SmartVend" = 9 chars
  tft.setCursor((SCREEN_W - txtW) / 2, 12);
  tft.print("SmartVend");
  // Divider at y=50
  tft.drawLine(0, 50, SCREEN_W, 50, TFT_WHITE);
}

// Draw footer bar at the bottom (30px)
void drawFooter(const char *text, uint16_t bgColor) {
  tft.fillRect(0, SCREEN_H - 30, SCREEN_W, 30, bgColor);
  tft.drawLine(0, SCREEN_H - 30, SCREEN_W, SCREEN_H - 30, TFT_WHITE);
  tft.setTextColor(TFT_WHITE);
  tft.setTextSize(1);
  int txtW = strlen(text) * 6;
  tft.setCursor((SCREEN_W - txtW) / 2, SCREEN_H - 18);
  tft.print(text);
}

// Helper: centered text with background fill (avoids flicker on partial updates)
void drawCenteredBg(const char *text, int y, uint8_t sz, uint16_t color, uint16_t bg) {
  int txtW = strlen(text) * 6 * sz;
  int txtH = 8 * sz;
  int x = (SCREEN_W - txtW) / 2;
  if (x < 0) x = 0;
  tft.fillRect(0, y, SCREEN_W, txtH + 4, bg);
  tft.setTextColor(color);
  tft.setTextSize(sz);
  tft.setCursor(x, y + 2);
  tft.print(text);
}

// ══════════════════════════════════════════════
//  DISPLAY FUNCTIONS
// ══════════════════════════════════════════════

void displayBootScreen(const char *statusText) {
  tft.fillScreen(C_BG_BOOT);
  drawHeader(C_BG_BOOT);

  // Big "SmartVend" label area
  tft.setTextColor(C_ACCENT);
  tft.setTextSize(2);
  int txtW = 9 * 6 * 2;
  tft.setCursor((SCREEN_W - txtW) / 2, 90);
  tft.print("SmartVend");

  // "v3.1" subtitle
  tft.setTextColor(TFT_DARKGREY);
  tft.setTextSize(1);
  tft.setCursor((SCREEN_W - 6 * 4) / 2, 115);
  tft.print("v3.1");

  // Divider
  tft.drawLine(20, 140, SCREEN_W - 20, 140, TFT_DARKGREY);

  // Status text
  tft.setTextColor(C_WHITE);
  tft.setTextSize(2);
  int stW = strlen(statusText) * 6 * 2;
  tft.setCursor((SCREEN_W - stW) / 2, 170);
  tft.print(statusText);

  // Spinner dots
  static uint8_t dotFrame = 0;
  dotFrame = (dotFrame + 1) % 4;
  tft.setCursor((SCREEN_W / 2) - 18, 200);
  tft.setTextColor(C_ACCENT);
  for (int i = 0; i < 3; i++) {
    tft.print(i < (int)dotFrame ? "." : " ");
  }

  drawFooter(machine_id, C_BG_BOOT);

  displayLine1 = "SmartVend";
  displayLine2 = String(statusText);
  Serial.printf("[TFT] Boot: %s\n", statusText);
}

void displayQRCode(const char *url) {
  tft.fillScreen(TFT_WHITE);

  // Draw header on white background with dark text
  tft.fillRect(0, 0, SCREEN_W, 50, 0x39C7);  // dark header on white screen
  tft.setTextColor(TFT_WHITE);
  tft.setTextSize(3);
  int hW = 9 * 6 * 3;
  tft.setCursor((SCREEN_W - hW) / 2, 12);
  tft.print("SmartVend");
  tft.drawLine(0, 50, SCREEN_W, 50, TFT_BLACK);

  // Right-side labels
  tft.setTextColor(TFT_BLACK);
  tft.setTextSize(2);
  tft.setCursor(5, 60);
  tft.print("Scan Me");

  tft.setTextSize(1);
  tft.setTextColor(TFT_DARKGREY);
  tft.setCursor(5, 80);
  tft.print(machine_id);
  tft.setCursor(5, 92);
  tft.print(currentSessionToken.substring(0, 8).c_str());

  // Keep full URL payload exactly as provided by backend (no shortening).
  String qrText = String(url ? url : "");
  if (qrText.length() == 0) {
    tft.setTextColor(TFT_RED);
    tft.setTextSize(2);
    tft.setCursor(10, 150);
    tft.print("QR URL Error!");
    return;
  }

  // Generate QR code — force higher QR version for denser code.
  QRCode qrcode;
  uint8_t qrcodeData[qrcode_getBufferSize(QR_VERSION_MAX)];

  int qrResult = -1;
  int version = QR_VERSION_MIN;
  while (version <= QR_VERSION_MAX) {
    qrResult = qrcode_initText(&qrcode, qrcodeData, version, ECC_LOW, qrText.c_str());
    if (qrResult == 0) break;
    version++;
  }

  if (qrResult != 0) {
    tft.setTextColor(TFT_RED);
    tft.setTextSize(2);
    tft.setCursor(10, 150);
    tft.print("QR Error!");
    return;
  }

  // Scale QR to fit a 200×200 area (centered horizontally, y from 55)
  uint8_t maxQRSize = 200;
  uint8_t moduleSize = maxQRSize / qrcode.size;
  if (moduleSize < 1) moduleSize = 1;

  uint8_t qrPixelSize = qrcode.size * moduleSize;
  uint8_t offsetX = (SCREEN_W - qrPixelSize) / 2;
  uint8_t offsetY = 58 + (210 - qrPixelSize) / 2;  // centered in y=58..268

  // Draw white quiet zone behind QR
  int quietZone = moduleSize * 2;
  tft.fillRect(offsetX - quietZone, offsetY - quietZone,
               qrPixelSize + quietZone * 2, qrPixelSize + quietZone * 2,
               TFT_WHITE);

  // Render QR modules: dark (true) = black pixel
  for (uint8_t y = 0; y < qrcode.size; y++) {
    for (uint8_t x = 0; x < qrcode.size; x++) {
      uint16_t color = qrcode_getModule(&qrcode, x, y) ? TFT_BLACK : TFT_WHITE;
      tft.fillRect(offsetX + x * moduleSize,
                   offsetY + y * moduleSize,
                   moduleSize, moduleSize, color);
    }
  }

  // Footer
  drawFooter("SmartVend — Tap to Pay", TFT_DARKGREY);

  displayLine1 = "SmartVend";
  displayLine2 = String("QR: ") + currentSessionToken;
  Serial.printf("[TFT] QR v%d, %dx%d modules, scale=%dpx\n",
                version, qrcode.size, qrcode.size, moduleSize);
}

void displayInUse(const char *userName) {
  tft.fillScreen(C_BG_INUSE);
  drawHeader(C_BG_INUSE);

  // Big "IN USE" text
  tft.setTextColor(C_WHITE);
  tft.setTextSize(4);
  int iuW = 6 * 6 * 4;  // "IN USE"
  tft.setCursor((SCREEN_W - iuW) / 2, 75);
  tft.print("IN USE");

  // Divider
  tft.drawLine(20, 130, SCREEN_W - 20, 130, TFT_WHITE);

  // Icon placeholder (person icon using rectangle)
  tft.fillRoundRect(SCREEN_W/2 - 20, 140, 40, 40, 20, TFT_WHITE);
  tft.fillCircle(SCREEN_W/2, 136, 14, TFT_WHITE);

  // User name
  tft.setTextColor(C_YELLOW);
  tft.setTextSize(2);
  int uW = strlen(userName) * 6 * 2;
  tft.setCursor((SCREEN_W - uW) / 2, 200);
  tft.print(userName);

  // Status
  tft.setTextColor(C_WHITE);
  tft.setTextSize(1);
  const char *status = "Processing payment...";
  int sW = strlen(status) * 6;
  tft.setCursor((SCREEN_W - sW) / 2, 230);
  tft.print(status);

  drawFooter(machine_id, C_BG_INUSE);

  displayLine1 = "SmartVend";
  displayLine2 = String("IN USE - ") + userName;
  Serial.printf("[TFT] In Use - %s\n", userName);
}

void displayDispensing(unsigned long quantity) {
  // Only clear background once per dispense cycle, then update bar
  static bool dispensingInit = false;
  if (!dispensingInit || state != STATE_DISPENSING) {
    dispensingInit = true;
    tft.fillScreen(C_BG_DISPENSE);
    drawHeader(C_BG_DISPENSE);

    tft.setTextColor(C_WHITE);
    tft.setTextSize(3);
    int dW = 10 * 6 * 3;  // "Dispensing"
    tft.setCursor((SCREEN_W - dW) / 2, 75);
    tft.print("Dispensing");

    // Quantity label
    tft.setTextSize(2);
    tft.setTextColor(C_YELLOW);
    char buf[32];
    snprintf(buf, sizeof(buf), "Qty: %lu", quantity);
    int qW = strlen(buf) * 6 * 2;
    tft.setCursor((SCREEN_W - qW) / 2, 125);
    tft.print(buf);

    // Progress bar border
    tft.drawRoundRect(20, 220, SCREEN_W - 40, 30, 6, TFT_WHITE);

    drawFooter(machine_id, C_BG_DISPENSE);
  }

  // Animate progress bar
  unsigned long elapsed = millis() - motorStartTime;
  float progress = motorRunDuration > 0 ? (float)elapsed / (float)motorRunDuration : 0;
  if (progress > 1.0f) progress = 1.0f;

  int barMax = SCREEN_W - 44;
  int barFill = (int)(barMax * progress);
  tft.fillRect(22, 222, barMax, 26, C_BG_DISPENSE);   // clear bar area
  if (barFill > 0) {
    tft.fillRoundRect(22, 222, barFill, 26, 4, C_ACCENT);  // fill
  }

  // Animated dots (update in place)
  static uint8_t dotFrame = 0;
  dotFrame = (dotFrame + 1) % 4;
  tft.fillRect(20, 270, SCREEN_W - 40, 16, C_BG_DISPENSE);
  tft.setTextColor(C_WHITE);
  tft.setTextSize(2);
  // Percentage
  char pct[8];
  snprintf(pct, sizeof(pct), "%d%%", (int)(progress * 100));
  int pW = strlen(pct) * 6 * 2;
  tft.setCursor((SCREEN_W - pW) / 2, 270);
  tft.print(pct);

  displayLine1 = "SmartVend";
  displayLine2 = String("Dispensing Qty: ") + String(quantity);
}

void displayCompleted() {
  tft.fillScreen(C_BG_COMPLETED);
  drawHeader(C_BG_COMPLETED);

  // Big checkmark using lines
  tft.drawLine(70,  175, 110, 215, TFT_WHITE);
  tft.drawLine(71,  175, 111, 215, TFT_WHITE);
  tft.drawLine(72,  175, 112, 215, TFT_WHITE);
  tft.drawLine(110, 215, 175, 145, TFT_WHITE);
  tft.drawLine(111, 215, 176, 145, TFT_WHITE);
  tft.drawLine(112, 215, 177, 145, TFT_WHITE);

  // "Done!" text
  tft.setTextColor(C_WHITE);
  tft.setTextSize(4);
  int dW = 5 * 6 * 4;  // "Done!"
  tft.setCursor((SCREEN_W - dW) / 2, 80);
  tft.print("Done!");

  // Thank you text
  tft.setTextColor(C_YELLOW);
  tft.setTextSize(2);
  int tW = 10 * 6 * 2;  // "Thank you!"
  tft.setCursor((SCREEN_W - tW) / 2, 240);
  tft.print("Thank you!");

  drawFooter("Come again!", C_BG_COMPLETED);

  displayLine1 = "SmartVend";
  displayLine2 = "Done! Thank you!";
  Serial.println("[TFT] Completed");
}

void displayError(const char *errorMsg) {
  tft.fillScreen(C_BG_ERROR);
  drawHeader(C_BG_ERROR);

  // "!" icon
  tft.fillRect(SCREEN_W/2 - 6, 70, 12, 60, TFT_WHITE);
  tft.fillRect(SCREEN_W/2 - 6, 140, 12, 12, TFT_WHITE);

  tft.setTextColor(C_WHITE);
  tft.setTextSize(3);
  int eW = 6 * 6 * 3;  // "ERROR!"
  tft.setCursor((SCREEN_W - eW) / 2, 80);
  tft.print("ERROR!");

  // Error message (smaller)
  tft.setTextColor(C_YELLOW);
  tft.setTextSize(2);
  int mW = strlen(errorMsg) * 6 * 2;
  if (mW > SCREEN_W) { tft.setTextSize(1); mW = strlen(errorMsg) * 6; }
  tft.setCursor((SCREEN_W - mW) / 2, 175);
  tft.print(errorMsg);

  tft.setTextColor(C_WHITE);
  tft.setTextSize(1);
  const char *support = "Contact support";
  int supW = strlen(support) * 6;
  tft.setCursor((SCREEN_W - supW) / 2, 210);
  tft.print(support);

  drawFooter(machine_id, C_BG_ERROR);

  displayLine1 = "SmartVend";
  displayLine2 = String("ERROR: ") + errorMsg;
  Serial.printf("[TFT] Error: %s\n", errorMsg);
}

void displayOffline() {
  tft.fillScreen(C_BG_OFFLINE);
  drawHeader(C_BG_OFFLINE);

  // WiFi icon (3 arcs approximation)
  int cx = SCREEN_W / 2;
  tft.drawCircle(cx, 145, 45, TFT_DARKGREY);
  tft.drawCircle(cx, 145, 30, TFT_DARKGREY);
  tft.drawCircle(cx, 145, 15, TFT_WHITE);
  // Cross through wifi icon
  tft.drawLine(cx - 40, 105, cx + 40, 185, TFT_RED);
  tft.drawLine(cx - 41, 105, cx + 41, 185, TFT_RED);

  tft.setTextColor(C_WHITE);
  tft.setTextSize(2);
  int oW = 7 * 6 * 2;  // "Offline"
  tft.setCursor((SCREEN_W - oW) / 2, 200);
  tft.print("Offline");

  tft.setTextColor(TFT_DARKGREY);
  tft.setTextSize(1);
  const char *rec = "Server unreachable";
  tft.setCursor((SCREEN_W - (int)strlen(rec) * 6) / 2, 228);
  tft.print(rec);

  const char *retry = "Reconnecting...";
  tft.setCursor((SCREEN_W - (int)strlen(retry) * 6) / 2, 244);
  tft.print(retry);

  drawFooter(machine_id, C_BG_OFFLINE);

  displayLine1 = "SmartVend";
  displayLine2 = "Offline - Reconnecting";
  Serial.println("[TFT] Offline");
}

// ══════════════════════════════════════════════
//  MOTOR FUNCTIONS
// ══════════════════════════════════════════════

void motorStop() {
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, LOW);
  analogWrite(ENA, 0);
  digitalWrite(LED_BUILTIN_PIN, LOW);
  Serial.println("[Motor] Stopped");
}

void motorRunForward(unsigned long durationMs) {
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);
  analogWrite(ENA, 200);
  digitalWrite(LED_BUILTIN_PIN, HIGH);

  motorRunning     = true;
  motorStartTime   = millis();
  motorRunDuration = durationMs;

  Serial.printf("[Motor] Running for %lu ms\n", durationMs);
}

// ══════════════════════════════════════════════
//  WEBSOCKET MESSAGING
// ══════════════════════════════════════════════

void sendRegister() {
  StaticJsonDocument<256> doc;
  doc["type"]       = "register";
  doc["machine_id"] = machine_id;
  doc["api_key"]    = machine_api_key;
  String message;
  serializeJson(doc, message);
  webSocket.sendTXT(message);
  Serial.println("[WS] Sent register");
}

void sendPong() {
  StaticJsonDocument<64> doc;
  doc["type"] = "pong";
  String message;
  serializeJson(doc, message);
  webSocket.sendTXT(message);
}

void sendJSON(const char *type, const char *value) {
  StaticJsonDocument<200> doc;
  doc["type"]  = type;
  doc["value"] = value;
  String message;
  serializeJson(doc, message);
  webSocket.sendTXT(message);
}

void sendConfirmation(unsigned long dispensed_qty) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[HTTP] WiFi disconnected, cannot confirm");
    return;
  }
  HTTPClient http;
  secureClient.setInsecure();
  String url = String(serverHttps) + "/api/machine/" + machine_id + "/confirm";
  http.begin(secureClient, url);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", "Bearer " + String(machine_api_key));

  StaticJsonDocument<200> doc;
  doc["transaction_id"] = currentTransactionId;
  doc["dispensed"]      = dispensed_qty;
  String requestBody;
  serializeJson(doc, requestBody);

  int httpCode = http.POST(requestBody);
  if (httpCode > 0) {
    String response = http.getString();
    Serial.printf("[HTTP] Confirm: %d — %s\n", httpCode, response.c_str());
  } else {
    Serial.printf("[HTTP] Confirm error: %d\n", httpCode);
  }
  http.end();
}

// ══════════════════════════════════════════════
//  WEBSOCKET EVENT HANDLER
// ══════════════════════════════════════════════

void webSocketEvent(WStype_t type, uint8_t *payload, size_t length) {
  switch (type) {
    case WStype_DISCONNECTED:
      Serial.println("[WS] Disconnected");
      if (state == STATE_IDLE) {
        displayOffline();
        state = STATE_OFFLINE;
        stateEnteredAt = millis();
      }
      break;

    case WStype_CONNECTED:
      Serial.println("[WS] Connected to server");
      displayBootScreen("Registering...");
      sendRegister();
      break;

    case WStype_TEXT: {
      Serial.printf("[WS] Received: %s\n", payload);
      StaticJsonDocument<512> doc;
      DeserializationError error = deserializeJson(doc, payload);
      if (error) {
        Serial.printf("[WS] JSON parse error: %s\n", error.c_str());
        return;
      }

      const char *msgType = doc["type"];
      if (!msgType) return;

      if (strcmp(msgType, "session") == 0) {
        const char *token = doc["token"];
        const char *url   = doc["url"];
        if (token && url) {
          currentSessionToken = String(token);
          currentSessionUrl   = String(url);
          if (doc.containsKey("expires_at"))
            currentExpiresAt = doc["expires_at"].as<String>();
          state = STATE_IDLE;
          stateEnteredAt = millis();
          claimedByName = "";
          displayQRCode(url);
          Serial.printf("[Session] New session: %s\n", token);
        }
      }

      else if (strcmp(msgType, "claimed") == 0) {
        const char *name = doc.containsKey("claimed_by_name")
          ? doc["claimed_by_name"].as<const char*>()
          : "User";
        claimedByName = String(name);
        state = STATE_IN_USE;
        stateEnteredAt = millis();
        displayInUse(name);
        Serial.printf("[Session] Claimed by: %s\n", name);
      }

      else if (strcmp(msgType, "new_session") == 0) {
        const char *token = doc["token"];
        const char *url   = doc["url"];
        if (token && url) {
          currentSessionToken = String(token);
          currentSessionUrl   = String(url);
          if (doc.containsKey("expires_at"))
            currentExpiresAt = doc["expires_at"].as<String>();
          state = STATE_IDLE;
          stateEnteredAt = millis();
          claimedByName = "";
          displayQRCode(url);
          Serial.printf("[Session] Renewed: %s\n", token);
        }
      }

      else if (strcmp(msgType, "command") == 0) {
        const char *action = doc["action"];
        if (action && strcmp(action, "dispense") == 0 &&
            (state == STATE_IN_USE || state == STATE_IDLE)) {
          currentTransactionId = doc["transaction_id"].as<String>();
          dispenseQuantity     = doc["duration"].as<unsigned long>();
          unsigned long duration = 0;
          if (doc.containsKey("duration_sec"))
            duration = doc["duration_sec"].as<unsigned long>() * 1000UL;
          else if (doc.containsKey("duration"))
            duration = doc["duration"].as<unsigned long>() * BASE_RUN_TIME;
          else
            duration = BASE_RUN_TIME;

          state = STATE_DISPENSING;
          stateEnteredAt = millis();
          displayDispensing(dispenseQuantity);
          motorRunForward(duration);
          Serial.printf("[Dispense] qty=%lu, duration=%lums, tx=%s\n",
                        dispenseQuantity, duration, currentTransactionId.c_str());
        }
      }

      else if (strcmp(msgType, "ping") == 0) {
        sendPong();
      }

      else if (strcmp(msgType, "stock_update") == 0) {
        int stock = doc["stock"] | -1;
        Serial.printf("[Stock] Updated to: %d\n", stock);
      }

      else if (strcmp(msgType, "error") == 0) {
        const char *errMsg = doc["error"] | "unknown";
        Serial.printf("[WS] Server error: %s\n", errMsg);
        if (state == STATE_BOOTING || state == STATE_IDLE) {
          displayError(errMsg);
          state = STATE_ERROR;
          stateEnteredAt = millis();
        }
      }

      else if (strcmp(msgType, "display_code") == 0 ||
               strcmp(msgType, "lock") == 0 ||
               strcmp(msgType, "unlock") == 0) {
        Serial.printf("[WS] Ignoring legacy message: %s\n", msgType);
      }

      else {
        Serial.printf("[WS] Unknown message type: %s\n", msgType);
      }
      break;
    }

    default:
      break;
  }
}

// ══════════════════════════════════════════════
//  WIFI
// ══════════════════════════════════════════════

void connectToBestWiFi() {
  WiFi.mode(WIFI_STA);
  int n = WiFi.scanNetworks();
  int bestNetwork = -1;
  int bestRSSI = -999;

  for (int i = 0; i < n; i++) {
    String foundSSID = WiFi.SSID(i);
    for (int j = 0; j < networkCount; j++) {
      if (foundSSID == networks[j].ssid) {
        int rssi = WiFi.RSSI(i);
        if (rssi > bestRSSI) {
          bestRSSI = rssi;
          bestNetwork = j;
        }
      }
    }
  }

  if (bestNetwork >= 0) {
    Serial.printf("[WiFi] Connecting to: %s (RSSI: %d)\n",
                  networks[bestNetwork].ssid, bestRSSI);
    WiFi.begin(networks[bestNetwork].ssid, networks[bestNetwork].password);
    unsigned long wifiStart = millis();
    while (WiFi.status() != WL_CONNECTED) {
      esp_task_wdt_reset();
      delay(500);
      Serial.print(".");
      if (millis() - wifiStart > 15000) {
        Serial.println("\n[WiFi] Connection timed out");
        return;
      }
    }
    Serial.printf("\n[WiFi] Connected! IP: %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("[WiFi] No known network found");
  }
}

bool waitForHealth() {
  for (int attempt = 0; attempt < 5; attempt++) {
    HTTPClient http;
    secureClient.setInsecure();
    String url = String(serverHttps) + "/health";
    if (http.begin(secureClient, url)) {
      int code = http.GET();
      http.end();
      if (code == 200) {
        Serial.println("[Health] Backend OK");
        return true;
      }
    }
    unsigned long backoff = 500 * (attempt + 1);
    Serial.printf("[Health] Retry %d in %lums\n", attempt + 1, backoff);
    char msg[32];
    snprintf(msg, sizeof(msg), "Retry %d/5...", attempt + 1);
    displayBootScreen(msg);
    delay(backoff);
    esp_task_wdt_reset();
  }
  return false;
}

// ══════════════════════════════════════════════
//  WEB CONTROL PANEL
// ══════════════════════════════════════════════

void handleRoot() {
  String html = R"rawliteral(
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SmartVend v3.1 Control</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',sans-serif;background:linear-gradient(135deg,#667eea,#764ba2);
min-height:100vh;padding:20px;display:flex;justify-content:center;align-items:center}
.c{background:#fff;border-radius:20px;box-shadow:0 20px 60px rgba(0,0,0,.3);padding:30px;max-width:600px;width:100%}
h1{color:#333;margin-bottom:20px;text-align:center;font-size:24px}
.s{background:#f5f5f5;border-radius:15px;padding:15px;margin-bottom:20px;border:2px solid #e0e0e0}
.st{font-size:16px;font-weight:bold;color:#555;margin-bottom:10px;text-align:center}
.tft{background:#001f3f;color:#00d4ff;font-family:'Courier New',monospace;padding:15px;
border-radius:10px;text-align:center;margin-bottom:10px;box-shadow:inset 0 2px 10px rgba(0,0,0,.5);min-height:80px}
.ol{font-size:16px;margin:4px 0;min-height:20px}
.si{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}
.si div{background:#fff;padding:8px;border-radius:8px;text-align:center}
.sl{font-size:11px;color:#888;margin-bottom:3px}
.sv{font-size:16px;font-weight:bold}
.sv.idle{color:#27ae60}.sv.in_use{color:#e67e22}.sv.dispensing{color:#3498db}
.sv.error{color:#e74c3c}.sv.offline{color:#95a5a6}
.bg{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:15px}
button{padding:12px;border:none;border-radius:10px;font-size:14px;font-weight:bold;cursor:pointer;
transition:all .3s;text-transform:uppercase;letter-spacing:1px}
button:hover{transform:translateY(-2px);box-shadow:0 5px 15px rgba(0,0,0,.2)}
.bs{background:linear-gradient(135deg,#27ae60,#2ecc71);color:#fff}
.bp{background:linear-gradient(135deg,#e74c3c,#c0392b);color:#fff}
</style></head><body><div class="c"><h1>SmartVend v3.1</h1>
<div class="s"><div class="st">TFT Display (2.4" ILI9341)</div>
<div class="tft"><div class="ol" id="l1">----</div><div class="ol" id="l2">----</div></div>
<div class="si">
<div><div class="sl">State</div><div class="sv" id="st">BOOTING</div></div>
<div><div class="sl">Motor</div><div class="sv" id="mt">STOPPED</div></div>
<div><div class="sl">Session</div><div class="sv" id="tk">----</div></div>
<div><div class="sl">Speed</div><div class="sv" id="sp">200</div></div>
</div></div>
<div class="s"><div class="st">Motor Control</div>
<div class="bg">
<button class="bs" onclick="fetch('/motor/start?speed=200',{method:'POST'})">Start Motor</button>
<button class="bp" onclick="fetch('/motor/stop',{method:'POST'})">Stop Motor</button>
</div></div></div>
<script>
function u(){fetch('/status').then(r=>r.json()).then(d=>{
document.getElementById('l1').textContent=d.line1||'----';
document.getElementById('l2').textContent=d.line2||'----';
const s=document.getElementById('st');s.textContent=d.state||'?';
s.className='sv '+(d.state||'').toLowerCase();
const m=document.getElementById('mt');m.textContent=d.motor?'RUNNING':'STOPPED';
m.className='sv '+(d.motor?'dispensing':'idle');
document.getElementById('tk').textContent=d.token||'----';
document.getElementById('sp').textContent=d.speed||'0';
}).catch(e=>console.error(e))}
setInterval(u,1000);u();
</script></body></html>
)rawliteral";
  server.send(200, "text/html", html);
}

void handleStatus() {
  StaticJsonDocument<300> doc;
  doc["line1"]     = displayLine1;
  doc["line2"]     = displayLine2;
  doc["motor"]     = motorRunning;
  doc["speed"]     = manualMotorSpeed;
  doc["token"]     = currentSessionToken;
  doc["machineId"] = machine_id;
  switch (state) {
    case STATE_BOOTING:    doc["state"] = "BOOTING";    break;
    case STATE_IDLE:       doc["state"] = "IDLE";       break;
    case STATE_IN_USE:     doc["state"] = "IN_USE";     break;
    case STATE_DISPENSING: doc["state"] = "DISPENSING"; break;
    case STATE_COMPLETED:  doc["state"] = "COMPLETED";  break;
    case STATE_ERROR:      doc["state"] = "ERROR";      break;
    case STATE_OFFLINE:    doc["state"] = "OFFLINE";    break;
  }
  String response;
  serializeJson(doc, response);
  server.send(200, "application/json", response);
}

void handleMotorStart() {
  if (server.hasArg("speed"))
    manualMotorSpeed = constrain(server.arg("speed").toInt(), 0, 255);
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);
  analogWrite(ENA, manualMotorSpeed);
  digitalWrite(LED_BUILTIN_PIN, HIGH);
  motorRunning = true;
  motorStartTime = millis();
  motorRunDuration = 0;
  manualMotorControl = true;
  Serial.printf("[Web] Motor start at speed %d\n", manualMotorSpeed);
  server.send(200, "application/json", "{\"status\":\"started\"}");
}

void handleMotorStop() {
  motorStop();
  motorRunning = false;
  manualMotorControl = false;
  Serial.println("[Web] Motor stop");
  server.send(200, "application/json", "{\"status\":\"stopped\"}");
}

// ══════════════════════════════════════════════
//  HTTP FALLBACK COMMAND POLLING
// ══════════════════════════════════════════════

void pollHttpCommands() {
  if (WiFi.status() != WL_CONNECTED || webSocket.isConnected()) return;
  HTTPClient http;
  secureClient.setInsecure();
  String url = String(serverHttps) + "/device/commands/" + machine_id;
  if (!http.begin(secureClient, url)) return;

  int httpCode = http.GET();
  if (httpCode == 200) {
    String payload = http.getString();
    StaticJsonDocument<1024> doc;
    if (deserializeJson(doc, payload) == DeserializationError::Ok) {
      JsonArray cmds = doc["commands"].as<JsonArray>();
      for (JsonObject cmd : cmds) {
        const char *type = cmd["type"] | "";
        if (strcmp(type, "session") == 0 || strcmp(type, "new_session") == 0) {
          const char *token  = cmd["token"];
          const char *cmdUrl = cmd["url"];
          if (token && cmdUrl) {
            currentSessionToken = String(token);
            currentSessionUrl   = String(cmdUrl);
            state = STATE_IDLE;
            stateEnteredAt = millis();
            displayQRCode(cmdUrl);
          }
        }
        else if (strcmp(type, "claimed") == 0) {
          const char *name = cmd["claimed_by_name"] | "User";
          claimedByName = String(name);
          state = STATE_IN_USE;
          stateEnteredAt = millis();
          displayInUse(name);
        }
        else if (strcmp(type, "command") == 0) {
          const char *action = cmd["action"] | "";
          if (strcmp(action, "dispense") == 0 &&
              (state == STATE_IN_USE || state == STATE_IDLE)) {
            currentTransactionId = cmd["transaction_id"].as<String>();
            dispenseQuantity = cmd["duration"] | 1;
            unsigned long duration = cmd.containsKey("duration_sec")
              ? cmd["duration_sec"].as<unsigned long>() * 1000UL
              : dispenseQuantity * BASE_RUN_TIME;
            state = STATE_DISPENSING;
            stateEnteredAt = millis();
            displayDispensing(dispenseQuantity);
            motorRunForward(duration);
          }
        }
      }
    }
  }
  http.end();
}

// ══════════════════════════════════════════════
//  SETUP
// ══════════════════════════════════════════════

void setup() {
  Serial.begin(115200);
  Serial.println("\n\n=============================");
  Serial.println(" SmartVend ESP32 v3.1 Boot");
  Serial.println("=============================");

  // Watchdog
  Serial.println("[WDT] Configuring watchdog...");
  esp_task_wdt_config_t wdt_config = {
    .timeout_ms   = 10000,
    .idle_core_mask = (1 << portNUM_PROCESSORS) - 1,
    .trigger_panic  = true
  };
  esp_task_wdt_reconfigure(&wdt_config);
  esp_task_wdt_add(NULL);

  randomSeed(esp_random());

  // Motor pins
  pinMode(ENA, OUTPUT);
  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  pinMode(LED_BUILTIN_PIN, OUTPUT);
  digitalWrite(LED_BUILTIN_PIN, LOW);
  motorStop();

  // TFT Display init
  tft.init();
  tft.setRotation(0);   // Portrait (240×320)
  tft.fillScreen(TFT_BLACK);
  Serial.println("[TFT] ILI9341 initialized (240x320)");

  // Boot screen
  displayBootScreen("Connecting WiFi...");

  // WiFi
  connectToBestWiFi();
  if (WiFi.status() == WL_CONNECTED) {
    displayBootScreen("WiFi Connected!");
    delay(500);
  } else {
    displayBootScreen("WiFi Failed!");
    delay(1000);
  }

  // Health check
  displayBootScreen("Checking server...");
  bool healthy = waitForHealth();
  if (!healthy) {
    displayOffline();
    state = STATE_OFFLINE;
    stateEnteredAt = millis();
  }

  // HTTPS client
  secureClient.setInsecure();

  // WebSocket
  webSocket.beginSSL(serverHost, serverPort, serverPath);
  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(5000);

  // Web server
  server.on("/", handleRoot);
  server.on("/status", handleStatus);
  server.on("/motor/start", HTTP_POST, handleMotorStart);
  server.on("/motor/stop",  HTTP_POST, handleMotorStop);
  server.begin();

  Serial.printf("[Web] Control panel: http://%s\n", WiFi.localIP().toString().c_str());
  Serial.println("[Boot] Setup complete — entering main loop");
}

// ══════════════════════════════════════════════
//  MAIN LOOP
// ══════════════════════════════════════════════

void loop() {
  esp_task_wdt_reset();
  webSocket.loop();
  server.handleClient();

  unsigned long now = millis();

  // ── WiFi auto-reconnect ──
  if (now - lastWiFiCheck > WIFI_CHECK_INTERVAL) {
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("[WiFi] Disconnected! Reconnecting...");
      if (state == STATE_IDLE) displayBootScreen("Reconnecting WiFi");
      connectToBestWiFi();
    }
    lastWiFiCheck = now;
  }

  // ── Heartbeat (every 30s, only when idle) ──
  if (state == STATE_IDLE && now - lastHeartbeat > HEARTBEAT_INTERVAL) {
    if (webSocket.isConnected()) sendPong();
    lastHeartbeat = now;
  }

  // ── HTTP fallback polling (when WS is down) ──
  if (!webSocket.isConnected() && now - lastCommandPoll > COMMAND_POLL_INTERVAL) {
    pollHttpCommands();
    lastCommandPoll = now;
  }

  // ── State: IN_USE — local timeout failsafe ──
  if (state == STATE_IN_USE) {
    if (now - stateEnteredAt > LOCK_TIMEOUT) {
      Serial.println("[Timeout] IN_USE timeout — returning to IDLE");
      state = STATE_IDLE;
      stateEnteredAt = now;
      claimedByName = "";
      if (currentSessionUrl.length() > 0)
        displayQRCode(currentSessionUrl.c_str());
      else
        displayBootScreen("Waiting for session");
      sendJSON("status", "timeout");
    }
  }

  // ── State: DISPENSING — motor running ──
  if (motorRunning) {
    if (state == STATE_DISPENSING && !manualMotorControl)
      displayDispensing(dispenseQuantity);

    // Jam detection
    int currentLevel = analogRead(JAM_SENSOR_PIN);
    if (currentLevel > JAM_CURRENT_THRESHOLD) {
      if (jamStartTime == 0) jamStartTime = now;
      if (now - jamStartTime > JAM_DURATION_THRESHOLD) {
        Serial.printf("[JAM] Motor jammed! (Level: %d) Emergency stop!\n", currentLevel);
        motorStop();
        motorRunning = false;
        jamStartTime = 0;
        state = STATE_ERROR;
        stateEnteredAt = now;
        displayError("Motor Jam!");
        sendJSON("error", "motor_jam");
        return;
      }
    } else {
      jamStartTime = 0;
    }

    // Auto-stop when duration reached
    if (!manualMotorControl && (now - motorStartTime > motorRunDuration)) {
      motorStop();
      motorRunning = false;
      sendConfirmation(dispenseQuantity);
      state = STATE_COMPLETED;
      stateEnteredAt = now;
      completedFlashStart = now;
      displayCompleted();
    }
  }

  // ── State: COMPLETED — brief flash, wait for new_session ──
  if (state == STATE_COMPLETED) {
    if (now - completedFlashStart > COMPLETED_FLASH_MS) {
      if (currentSessionUrl.length() > 0 && state == STATE_COMPLETED)
        displayBootScreen("Next customer...");
    }
  }

  // ── State: OFFLINE — periodic display refresh ──
  if (state == STATE_OFFLINE) {
    if (now - stateEnteredAt > 10000) {
      displayOffline();
      stateEnteredAt = now;
    }
  }

  // ── State: ERROR — auto-recovery after 60s ──
  if (state == STATE_ERROR) {
    if (now - stateEnteredAt > 60000) {
      Serial.println("[Error] Auto-recovery — requesting new session");
      state = STATE_BOOTING;
      stateEnteredAt = now;
      displayBootScreen("Recovering...");
      sendRegister();
    }
  }
}
