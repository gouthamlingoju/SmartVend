/*
 * SmartVend ESP32 Firmware v3.0 — QR-Based Session System
 * ========================================================
 * 
 * Hardware:
 *   - ESP32 DevKit V1
 *   - 0.96" OLED SSD1306 (128×64px) via I2C (replaces 16×2 LCD)
 *   - L298N Motor Driver (ENA=25, IN1=26, IN2=27)
 *   - Current sensor on GPIO34 for jam detection
 *   - Built-in LED on GPIO2
 *
 * v3.0 Changes from v2.0:
 *   - OLED replaces LCD (128×64 px vs 16×2 chars)
 *   - QR code rendered on-device from session URL
 *   - New WS message types: "session", "claimed", "new_session"
 *   - States: IDLE → IN_USE → DISPENSING → COMPLETED (replaces UNLOCKED/LOCKED)
 *   - No more display_code / fetch_display / lock / unlock messages
 *
 * Libraries required (install via Arduino Library Manager):
 *   1. Adafruit SSD1306  (+ Adafruit GFX)
 *   2. QRCode by ricmoo  (https://github.com/ricmoo/QRCode)
 *   3. WebSocketsClient
 *   4. ArduinoJson
 *   5. WebServer (built-in)
 *   6. esp_task_wdt (built-in)
 */

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WebServer.h>
#include <esp_task_wdt.h>

// OLED Display
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// QR Code generation
#include "qrcode.h"

// ══════════════════════════════════════════════
//  CONFIGURATION
// ══════════════════════════════════════════════

// WiFi Networks (ordered by preference)
struct WiFiNetwork {
  const char *ssid;
  const char *password;
};

WiFiNetwork networks[] = {
  {"Goutham's Galaxy", "23456789"},
  {"VNRVJIET_WIFI", "vnrvjiet@123"},
  {"VNRVJIET_E", "vnrvjiet@123"}
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
const int ENA = 25;  // PWM speed
const int IN1 = 26;  // Direction
const int IN2 = 27;  // Direction

// LED
const int LED_BUILTIN_PIN = 2;

// Jam Detection (analog current sensor)
const int JAM_SENSOR_PIN       = 34;
const int JAM_CURRENT_THRESHOLD = 800;  // Calibrate per motor
const int JAM_DURATION_THRESHOLD = 200; // ms sustained

// OLED Display (SSD1306 128×64)
#define SCREEN_WIDTH  128
#define SCREEN_HEIGHT 64
#define OLED_RESET    -1  // No reset pin (share ESP32 reset)
#define OLED_I2C_ADDR 0x3C  // Common SSD1306 address (try 0x3D if needed)

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// ══════════════════════════════════════════════
//  STATE MACHINE (v3.0)
// ══════════════════════════════════════════════

enum DeviceState {
  STATE_BOOTING,      // Startup sequence
  STATE_IDLE,         // Showing QR code, waiting for scan
  STATE_IN_USE,       // Session claimed, user paying
  STATE_DISPENSING,   // Motor running
  STATE_COMPLETED,    // Dispense done, brief "Done!" flash
  STATE_ERROR,        // Jam or hardware error
  STATE_OFFLINE       // Backend unreachable
};

DeviceState state = STATE_BOOTING;

// ══════════════════════════════════════════════
//  GLOBAL VARIABLES
// ══════════════════════════════════════════════

// Networking
WebSocketsClient webSocket;
WebServer server(80);
WiFiClientSecure secureClient;

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
const unsigned long BASE_RUN_TIME       = 4000;   // ms per unit
const unsigned long LOCK_TIMEOUT        = 600000;  // 10 min local failsafe
const unsigned long WIFI_CHECK_INTERVAL = 30000;   // 30 sec
const unsigned long HEARTBEAT_INTERVAL  = 30000;   // 30 sec (reduced from 1s)
const unsigned long COMMAND_POLL_INTERVAL = 15000;  // 15 sec HTTP fallback
const unsigned long COMPLETED_FLASH_MS  = 2000;    // 2 sec "Done!" flash

// Timing trackers
unsigned long lastHeartbeat    = 0;
unsigned long lastCommandPoll  = 0;
unsigned long lastWiFiCheck    = 0;
unsigned long stateEnteredAt   = 0;  // When current state was entered
unsigned long completedFlashStart = 0;

// Manual motor control (web panel)
int  manualMotorSpeed   = 200;
bool manualMotorControl = false;

// Display state cache (for web panel)
String displayLine1 = "";
String displayLine2 = "";

// QR Code bitmap cache (avoid regenerating every frame)
bool qrBitmapValid = false;
uint8_t qrBitmapData[64 * 64 / 8];  // 64×64 monochrome bitmap

// ══════════════════════════════════════════════
//  OLED DISPLAY FUNCTIONS
// ══════════════════════════════════════════════

// Reusable header — always shows "SmartVend" + divider at top (14px)
void drawHeader() {
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(28, 2);
  display.print("SmartVend");
  display.drawLine(0, 12, 127, 12, SSD1306_WHITE);
}

void displayBootScreen(const char* statusText) {
  display.clearDisplay();
  drawHeader();
  
  // Status text centered below header
  display.setTextSize(1);
  int16_t x1, y1;
  uint16_t w, h;
  display.getTextBounds(statusText, 0, 0, &x1, &y1, &w, &h);
  display.setCursor((SCREEN_WIDTH - w) / 2, 34);
  display.print(statusText);
  
  display.display();
  
  // Cache for web panel
  displayLine1 = "SmartVend";
  displayLine2 = String(statusText);
  
  Serial.printf("[OLED] Boot: %s\n", statusText);
}

void displayQRCode(const char* url) {
  display.clearDisplay();
  // Fill entire screen with WHITE to act as glowing background
  display.fillRect(0, 0, 128, 64, SSD1306_WHITE);

  // Reduce contrast to fix intense blue camera glare
  display.ssd1306_command(SSD1306_SETCONTRAST);
  display.ssd1306_command(0x3F); // 25% brightness

  // Strip https:// to shorten payload
  const char* qrText = url;
  if (strncmp(qrText, "https://", 8) == 0) qrText += 8;
  else if (strncmp(qrText, "http://", 7) == 0) qrText += 7;

  // ── KEY CHANGE 1: Use ECC_LOW to get smallest possible QR ──
  // Clean OLED display doesn't need high redundancy
  QRCode qrcode;
  uint8_t qrcodeData[qrcode_getBufferSize(10)];

  int qrResult = -1;
  int version = 1;
  while (version <= 10) {
    qrResult = qrcode_initText(&qrcode, qrcodeData, version, ECC_LOW, qrText);
    if (qrResult == 0) break;
    version++;
  }

  if (qrResult != 0) {
    display.setCursor(0, 30);
    display.print("QR Error");
    display.display();
    return;
  }

  // ── KEY CHANGE 2: Use full 64px for QR, scale as large as possible ──
  uint8_t moduleSize = 64 / qrcode.size;
  if (moduleSize < 1) moduleSize = 1;
  uint8_t qrPixelSize = qrcode.size * moduleSize;

  // ── KEY CHANGE: Center QR horizontally and vertically ──
  // The OLED is 128px wide by 64px tall. Since the QR code is a square, 
  // its maximum size is bounded by the 64px height.
  uint8_t offsetX = (128 - qrPixelSize) / 2;  // CENTER horizontally
  uint8_t offsetY = (64  - qrPixelSize) / 2;  // CENTER vertically

  // ── KEY CHANGE 5: Draw BLACK modules on WHITE background ──
  // Black-on-white is the standard QR orientation. The screen is already white.
  for (uint8_t y = 0; y < qrcode.size; y++) {
    for (uint8_t x = 0; x < qrcode.size; x++) {
      if (qrcode_getModule(&qrcode, x, y)) {  // Corrected: true = dark module
        display.fillRect(
          offsetX + x * moduleSize,
          offsetY + y * moduleSize,
          moduleSize,
          moduleSize,
          SSD1306_BLACK
        );
      }
    }
  }

  // Draw tiny ID in bottom-left corner to avoid overlapping the centered QR code
  display.setTextSize(1);
  display.setTextColor(SSD1306_BLACK); // Dark text on bright background
  display.setCursor(0, 56); 
  display.print(machine_id);

  // You can also put the 4-char code in the top-left corner
  display.setCursor(0, 0); 
  display.print(currentSessionToken);

  display.display();

  // Cache for web panel
  displayLine1 = "SmartVend";
  displayLine2 = String("QR: ") + currentSessionToken;

  Serial.printf("[OLED] QR v%d, %dx%d modules, scale=%dpx\n", 
                version, qrcode.size, qrcode.size, moduleSize);
}

void displayInUse(const char* userName) {
  display.clearDisplay();
  drawHeader();
  
  // "IN USE" below header
  display.setTextSize(2);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(18, 16);
  display.print("IN USE");
  
  // User name
  display.setTextSize(1);
  display.setCursor(10, 38);
  display.print("User: ");
  display.print(userName);
  
  // Status
  display.setCursor(10, 52);
  display.print("Processing payment...");
  
  display.display();
  
  displayLine1 = "SmartVend";
  displayLine2 = String("IN USE - ") + userName;
  
  Serial.printf("[OLED] In Use - %s\n", userName);
}

void displayDispensing(unsigned long quantity) {
  display.clearDisplay();
  drawHeader();
  
  // "Dispensing" text below header
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(20, 16);
  display.print("Dispensing");
  
  // Animated dots effect
  static uint8_t dotFrame = 0;
  dotFrame = (dotFrame + 1) % 4;
  for (int i = 0; i < dotFrame; i++) display.print(".");
  
  // Quantity
  display.setCursor(20, 28);
  display.printf("Qty: %lu", quantity);
  
  // Progress bar area
  display.drawRect(10, 42, 108, 12, SSD1306_WHITE);
  
  // Calculate progress
  unsigned long elapsed = millis() - motorStartTime;
  float progress = (float)elapsed / (float)motorRunDuration;
  if (progress > 1.0) progress = 1.0;
  display.fillRect(12, 44, (int)(104 * progress), 8, SSD1306_WHITE);
  
  display.display();
  
  displayLine1 = "SmartVend";
  displayLine2 = String("Dispensing Qty: ") + String(quantity);
}

void displayCompleted() {
  display.clearDisplay();
  drawHeader();
  
  // "Done!" below header
  display.setTextSize(2);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(24, 16);
  display.print("Done!");
  
  // Draw a checkmark
  display.drawLine(45, 38, 55, 48, SSD1306_WHITE);
  display.drawLine(55, 48, 75, 28, SSD1306_WHITE);
  display.drawLine(46, 38, 56, 48, SSD1306_WHITE);
  display.drawLine(56, 48, 76, 28, SSD1306_WHITE);
  
  display.setTextSize(1);
  display.setCursor(22, 55);
  display.print("Thank you!");
  
  display.display();
  
  displayLine1 = "SmartVend";
  displayLine2 = "Done! Thank you!";
  
  Serial.println("[OLED] Completed");
}

void displayError(const char* errorMsg) {
  display.clearDisplay();
  drawHeader();
  
  // "ERROR!" below header
  display.setTextSize(2);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(18, 16);
  display.print("ERROR!");
  
  display.setTextSize(1);
  display.setCursor(5, 38);
  display.print(errorMsg);
  
  display.setCursor(5, 52);
  display.print("Contact support");
  
  display.display();
  
  displayLine1 = "SmartVend";
  displayLine2 = String("ERROR: ") + errorMsg;
  
  Serial.printf("[OLED] Error: %s\n", errorMsg);
}

void displayOffline() {
  display.clearDisplay();
  drawHeader();
  
  // "Offline" below header
  display.setTextSize(2);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(16, 18);
  display.print("Offline");
  
  display.setTextSize(1);
  display.setCursor(10, 42);
  display.print("Server unreachable");
  
  display.setCursor(10, 55);
  display.print("Reconnecting...");
  
  display.display();
  
  displayLine1 = "SmartVend";
  displayLine2 = "Offline - Reconnecting";
  
  Serial.println("[OLED] Offline");
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
  analogWrite(ENA, 200);  // Adjust speed 0–255
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
  secureClient.setInsecure();  // TODO: pin CA for production

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
    
    // Parse response for new session token
    StaticJsonDocument<512> respDoc;
    if (deserializeJson(respDoc, response) == DeserializationError::Ok) {
      if (respDoc.containsKey("new_session_token")) {
        // Server already sent new_session via WS, but this is a fallback
        Serial.println("[HTTP] Got new session token via confirm response");
      }
    }
  } else {
    Serial.printf("[HTTP] Confirm error: %d\n", httpCode);
  }
  http.end();
}

// ══════════════════════════════════════════════
//  WEBSOCKET EVENT HANDLER (v3.0)
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

      // ── SESSION: New active session (on register or after QR rotation) ──
      if (strcmp(msgType, "session") == 0) {
        const char *token = doc["token"];
        const char *url   = doc["url"];
        
        if (token && url) {
          currentSessionToken = String(token);
          currentSessionUrl   = String(url);
          if (doc.containsKey("expires_at")) {
            currentExpiresAt = doc["expires_at"].as<String>();
          }
          
          state = STATE_IDLE;
          stateEnteredAt = millis();
          claimedByName = "";
          
          // Render QR code on OLED
          displayQRCode(url);
          
          Serial.printf("[Session] New session: %s\n", token);
        }
      }

      // ── CLAIMED: User scanned QR → session is IN_PROGRESS ──
      else if (strcmp(msgType, "claimed") == 0) {
        const char *name = doc.containsKey("claimed_by_name") 
          ? doc["claimed_by_name"].as<const char*>() 
          : "User";
        
        claimedByName = String(name);
        state = STATE_IN_USE;
        stateEnteredAt = millis();
        
        // Switch OLED from QR to "In Use" display
        displayInUse(name);
        
        Serial.printf("[Session] Claimed by: %s\n", name);
      }

      // ── NEW_SESSION: After completion/expiry, render new QR ──
      else if (strcmp(msgType, "new_session") == 0) {
        const char *token = doc["token"];
        const char *url   = doc["url"];
        
        if (token && url) {
          currentSessionToken = String(token);
          currentSessionUrl   = String(url);
          if (doc.containsKey("expires_at")) {
            currentExpiresAt = doc["expires_at"].as<String>();
          }
          
          state = STATE_IDLE;
          stateEnteredAt = millis();
          claimedByName = "";
          
          displayQRCode(url);
          
          Serial.printf("[Session] Renewed: %s\n", token);
        }
      }

      // ── COMMAND: Dispense ──
      else if (strcmp(msgType, "command") == 0) {
        const char *action = doc["action"];
        
        if (action && strcmp(action, "dispense") == 0 && 
            (state == STATE_IN_USE || state == STATE_IDLE)) {
          
          currentTransactionId = doc["transaction_id"].as<String>();
          dispenseQuantity     = doc["duration"].as<unsigned long>();
          
          unsigned long duration = 0;
          if (doc.containsKey("duration_sec")) {
            duration = doc["duration_sec"].as<unsigned long>() * 1000UL;
          } else if (doc.containsKey("duration")) {
            duration = doc["duration"].as<unsigned long>() * BASE_RUN_TIME;
          } else {
            duration = BASE_RUN_TIME;
          }
          
          state = STATE_DISPENSING;
          stateEnteredAt = millis();
          
          displayDispensing(dispenseQuantity);
          motorRunForward(duration);
          
          Serial.printf("[Dispense] qty=%lu, duration=%lums, tx=%s\n",
                        dispenseQuantity, duration, currentTransactionId.c_str());
        }
      }

      // ── PING: Server keepalive → respond with pong ──
      else if (strcmp(msgType, "ping") == 0) {
        sendPong();
      }

      // ── STOCK_UPDATE: Informational ──
      else if (strcmp(msgType, "stock_update") == 0) {
        int stock = doc["stock"] | -1;
        Serial.printf("[Stock] Updated to: %d\n", stock);
      }

      // ── ERROR: Server-side error ──
      else if (strcmp(msgType, "error") == 0) {
        const char *errMsg = doc["error"] | "unknown";
        Serial.printf("[WS] Server error: %s\n", errMsg);
        if (state == STATE_BOOTING || state == STATE_IDLE) {
          displayError(errMsg);
          state = STATE_ERROR;
          stateEnteredAt = millis();
        }
      }

      // ── LEGACY: display_code (backward compat, ignore in v3.0) ──
      else if (strcmp(msgType, "display_code") == 0) {
        Serial.println("[WS] Ignoring legacy display_code message");
      }

      // ── LEGACY: lock/unlock (backward compat, ignore in v3.0) ──
      else if (strcmp(msgType, "lock") == 0 || strcmp(msgType, "unlock") == 0) {
        Serial.printf("[WS] Ignoring legacy %s message\n", msgType);
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
    
    // Show retry on OLED
    char msg[32];
    snprintf(msg, sizeof(msg), "Retry %d/5...", attempt + 1);
    displayBootScreen(msg);
    
    delay(backoff);
    esp_task_wdt_reset();
  }
  return false;
}

// ══════════════════════════════════════════════
//  WEB CONTROL PANEL (updated for v3.0)
// ══════════════════════════════════════════════

void handleRoot() {
  String html = R"rawliteral(
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SmartVend v3.0 Control</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',sans-serif;background:linear-gradient(135deg,#667eea,#764ba2);
min-height:100vh;padding:20px;display:flex;justify-content:center;align-items:center}
.c{background:#fff;border-radius:20px;box-shadow:0 20px 60px rgba(0,0,0,.3);padding:30px;max-width:600px;width:100%}
h1{color:#333;margin-bottom:20px;text-align:center;font-size:24px}
.s{background:#f5f5f5;border-radius:15px;padding:15px;margin-bottom:20px;border:2px solid #e0e0e0}
.st{font-size:16px;font-weight:bold;color:#555;margin-bottom:10px;text-align:center}
.oled{background:#000;color:#0f0;font-family:'Courier New',monospace;padding:15px;border-radius:10px;
text-align:center;margin-bottom:10px;box-shadow:inset 0 2px 10px rgba(0,0,0,.5);min-height:80px}
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
</style></head><body><div class="c"><h1>SmartVend v3.0</h1>
<div class="s"><div class="st">OLED Display</div>
<div class="oled"><div class="ol" id="l1">----</div><div class="ol" id="l2">----</div></div>
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
  doc["line1"]  = displayLine1;
  doc["line2"]  = displayLine2;
  doc["motor"]  = motorRunning;
  doc["speed"]  = manualMotorSpeed;
  doc["token"]  = currentSessionToken;
  doc["machineId"] = machine_id;
  
  // State name
  switch (state) {
    case STATE_BOOTING:   doc["state"] = "BOOTING"; break;
    case STATE_IDLE:      doc["state"] = "IDLE"; break;
    case STATE_IN_USE:    doc["state"] = "IN_USE"; break;
    case STATE_DISPENSING: doc["state"] = "DISPENSING"; break;
    case STATE_COMPLETED: doc["state"] = "COMPLETED"; break;
    case STATE_ERROR:     doc["state"] = "ERROR"; break;
    case STATE_OFFLINE:   doc["state"] = "OFFLINE"; break;
  }
  
  String response;
  serializeJson(doc, response);
  server.send(200, "application/json", response);
}

void handleMotorStart() {
  if (server.hasArg("speed")) {
    manualMotorSpeed = constrain(server.arg("speed").toInt(), 0, 255);
  }
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);
  analogWrite(ENA, manualMotorSpeed);
  digitalWrite(LED_BUILTIN_PIN, HIGH);
  motorRunning = true;
  motorStartTime = millis();
  motorRunDuration = 0;  // Continuous until stopped
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
        
        // Handle session messages via HTTP fallback
        if (strcmp(type, "session") == 0 || strcmp(type, "new_session") == 0) {
          const char *token = cmd["token"];
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
            unsigned long duration = (cmd.containsKey("duration_sec")
              ? cmd["duration_sec"].as<unsigned long>() * 1000UL
              : dispenseQuantity * BASE_RUN_TIME);
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
  Serial.println(" SmartVend ESP32 v3.0 Boot");
  Serial.println("=============================");

  // Watchdog (10 second timeout)
  Serial.println("[WDT] Configuring watchdog...");
  esp_task_wdt_config_t wdt_config = {
    .timeout_ms = 10000,
    .idle_core_mask = (1 << portNUM_PROCESSORS) - 1,
    .trigger_panic = true
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

  // OLED Display
  Wire.begin();  // SDA=21, SCL=22 (default ESP32)
  
  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_I2C_ADDR)) {
    Serial.println("[OLED] SSD1306 init FAILED!");
  } else {
    Serial.println("[OLED] SSD1306 initialized");
    
    // I2C DATA FIX: Drop to 100kHz for stable data wires
    Wire.setClock(100000); 
    
    // (Contrast logic handled in displayQRCode method now)
  }
  
  display.clearDisplay();
  display.display();

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
    // Continue anyway — WS will auto-reconnect
  }

  // HTTPS client
  secureClient.setInsecure();  // TODO: pin CA for production

  // WebSocket (wss://)
  webSocket.beginSSL(serverHost, serverPort, serverPath);
  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(5000);

  // Web server (local control panel)
  server.on("/", handleRoot);
  server.on("/status", handleStatus);
  server.on("/motor/start", HTTP_POST, handleMotorStart);
  server.on("/motor/stop", HTTP_POST, handleMotorStop);
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
      if (state == STATE_IDLE) {
        displayBootScreen("Reconnecting WiFi");
      }
      connectToBestWiFi();
    }
    lastWiFiCheck = now;
  }

  // ── Heartbeat (every 30s, only when idle) ──
  if (state == STATE_IDLE && now - lastHeartbeat > HEARTBEAT_INTERVAL) {
    if (webSocket.isConnected()) {
      sendPong();  // Keepalive
    }
    lastHeartbeat = now;
  }

  // ── HTTP fallback polling (when WS is down) ──
  if (!webSocket.isConnected() && now - lastCommandPoll > COMMAND_POLL_INTERVAL) {
    pollHttpCommands();
    lastCommandPoll = now;
  }

  // ── State: IDLE — QR is displayed, no action needed ──
  // (QR rotation is handled by server sending new_session via WS/sweeper)

  // ── State: IN_USE — waiting for dispense command ──
  if (state == STATE_IN_USE) {
    // Local timeout failsafe (10 min)
    if (now - stateEnteredAt > LOCK_TIMEOUT) {
      Serial.println("[Timeout] IN_USE timeout — returning to IDLE");
      state = STATE_IDLE;
      stateEnteredAt = now;
      claimedByName = "";
      // Re-display QR if we have a valid session
      if (currentSessionUrl.length() > 0) {
        displayQRCode(currentSessionUrl.c_str());
      } else {
        displayBootScreen("Waiting for session");
      }
      // Tell server
      sendJSON("status", "timeout");
    }
  }

  // ── State: DISPENSING — motor is running ──
  if (motorRunning) {
    // Update dispensing animation
    if (state == STATE_DISPENSING && !manualMotorControl) {
      displayDispensing(dispenseQuantity);
    }
    
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
        
        // Report to server
        sendJSON("error", "motor_jam");
        return;
      }
    } else {
      jamStartTime = 0;
    }

    // Auto-stop when duration reached (not manual control)
    if (!manualMotorControl && (now - motorStartTime > motorRunDuration)) {
      motorStop();
      motorRunning = false;
      
      // Send confirmation to server
      sendConfirmation(dispenseQuantity);
      
      // Show "Done!" briefly
      state = STATE_COMPLETED;
      stateEnteredAt = now;
      completedFlashStart = now;
      displayCompleted();
    }
  }

  // ── State: COMPLETED — brief flash, then wait for new_session from server ──
  if (state == STATE_COMPLETED) {
    if (now - completedFlashStart > COMPLETED_FLASH_MS) {
      // If server hasn't sent new_session yet, show waiting screen
      if (currentSessionUrl.length() > 0 && state == STATE_COMPLETED) {
        // Server should have sent new_session by now (via confirm response or WS)
        // If not, we'll get it soon from the sweeper
        displayBootScreen("Next customer...");
      }
      // Don't change state here — wait for server's "new_session" message
    }
  }

  // ── State: OFFLINE — periodic retry ──
  if (state == STATE_OFFLINE) {
    // Auto-recover when WS reconnects (handled by webSocketEvent)
    // Display update every 10 seconds
    if (now - stateEnteredAt > 10000) {
      displayOffline();
      stateEnteredAt = now;
    }
  }

  // ── State: ERROR — wait for manual resolution or timeout ──
  if (state == STATE_ERROR) {
    // Auto-recover after 60 seconds (try to get new session)
    if (now - stateEnteredAt > 60000) {
      Serial.println("[Error] Auto-recovery — requesting new session");
      state = STATE_BOOTING;
      stateEnteredAt = now;
      displayBootScreen("Recovering...");
      sendRegister();
    }
  }
}
