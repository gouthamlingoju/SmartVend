#include <WiFi.h>
#include <WebSocketsClient.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// ===== WiFi & Server =====
const char* ssid = "Goutham's Galaxy";
const char* password = "23456789";
const char* serverHost = "10.21.175.195";  // Backend host (LAN IP of FastAPI)
const char* serverHttps = "http://10.21.175.195:8002";  // HTTP API endpoint
const int serverPort = 8002;  // FastAPI port (plain WS)
const char* serverPath = "/ws";

// Unique identifier for this machine
const char* machine_id = "M001";
const char* machine_api_key = "sv_001mmsg";

WebSocketsClient webSocket;
unsigned long lastReconnectAttempt = 0;
const unsigned long RECONNECT_INTERVAL = 5000; // Try to reconnect every 5 seconds
bool wsConnected = false;

// ===== Motor Driver Pins =====
const int ENA = 25;   // PWM
const int IN1 = 26;
const int IN2 = 27;

// ===== State Machine =====
enum DeviceState { UNLOCKED, LOCKED };
DeviceState state = UNLOCKED;

bool motorRunning = false;
unsigned long motorStartTime = 0;
unsigned long motorRunDuration = 0;  // dynamically set by server
String currentTransactionId = "";  // Track current transaction for confirmation

// timing constants
const unsigned long POST_INTERVAL = 1000;    // 1 second
const unsigned long FETCH_INTERVAL = 300000; // 5 minutes
const unsigned long LOCK_DURATION = 600000;  // 10 minutes
const unsigned long BASE_RUN_TIME = 2000;   // 2 seconds per unit

unsigned long lastPost = 0;
unsigned long lastFetch = 0;
unsigned long lockStartTime = 0;

String currentDisplayCode = "----"; // default blank code

// ===== I2C LCD Display =====
// Initialize the LCD: (I2C address, columns, rows)
// Common addresses: 0x27 or 0x3F (use I2C scanner to find yours)
LiquidCrystal_I2C lcd(0x27, 16, 2);  // Change 0x27 to your LCD's I2C address if different

// ===== Helper Functions =====
void updateLCD(const char* line1, const char* line2 = "") {
  // Update physical LCD display
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print(line1);
  if (strlen(line2) > 0) {
    lcd.setCursor(0, 1);
    lcd.print(line2);
  }
  
  // Also print to Serial for debugging
  Serial.println("========== DISPLAY ==========");
  Serial.println(line1);
  Serial.println(line2);
  Serial.println("=============================");
}

void motorStop() {
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, LOW);
  analogWrite(ENA, 0);
  Serial.println("Motor stopped");
}

void motorRunForward(unsigned long durationMs) {
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);
  analogWrite(ENA, 200); // Adjust speed (0–255)
  motorRunning = true;
  motorStartTime = millis();
  motorRunDuration = durationMs;

  Serial.printf("Motor running for %lu ms\n", durationMs);
  updateLCD("Dispensing...");
}

void sendJSON(const char* type, const char* value) {
  StaticJsonDocument<200> doc;
  doc["type"] = type;
  doc["value"] = value;
  String message;
  serializeJson(doc, message);
  webSocket.sendTXT(message);
}

// HTTP helpers for API calls
void sendConfirmDispense(int dispensed) {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  String url = String(serverHttps) + "/api/machine/" + machine_id + "/confirm";
  http.begin(url);
  
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", String("Bearer ") + machine_api_key);

  StaticJsonDocument<200> doc;
  doc["dispensed"] = dispensed;
  doc["transaction_id"] = currentTransactionId;
  
  String requestBody;
  serializeJson(doc, requestBody);
  
  int httpCode = http.POST(requestBody);
  if (httpCode > 0) {
    String payload = http.getString();
    Serial.printf("Confirm response: %d - %s\n", httpCode, payload.c_str());
    
    if (httpCode == 200) {
      StaticJsonDocument<200> response;
      deserializeJson(response, payload);
      const char* newCode = response["new_display_code"];
      if (newCode) {
        currentDisplayCode = String(newCode);
        if (state == UNLOCKED) {
          updateLCD("Unlocked", ("Code: " + currentDisplayCode).c_str());
        }
      }
    }
  }
  http.end();
}

void reportError(const char* error) {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  String url = String(serverHttps) + "/api/machine/" + machine_id + "/report-error";
  http.begin(url);
  
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", String("Bearer ") + machine_api_key);

  StaticJsonDocument<200> doc;
  doc["error"] = error;
  if (currentTransactionId.length() > 0) {
    doc["transaction_id"] = currentTransactionId;
  }
  
  String requestBody;
  serializeJson(doc, requestBody);
  
  http.POST(requestBody);
  http.end();
}

void sendRegister() {
  StaticJsonDocument<256> doc;
  doc["type"] = "register";
  doc["machine_id"] = machine_id;
  doc["api_key"] = machine_api_key;
  String message;
  serializeJson(doc, message);
  webSocket.sendTXT(message);
  Serial.println("Sent register message over WS");
}

void fetchDisplayCode() {
  StaticJsonDocument<200> doc;
  doc["type"] = "fetch_display";
  String message;
  serializeJson(doc, message);
  webSocket.sendTXT(message);
  Serial.println("Fetching display code...");
}

void fetchMachineStatus() {
  if (WiFi.status() != WL_CONNECTED) return;
  HTTPClient http;
  String url = String(serverHttps) + "/api/machine/" + machine_id + "/status";
  http.begin(url);
  http.addHeader("Authorization", String("Bearer ") + machine_api_key);
  int httpCode = http.GET();
  if (httpCode == 200) {
    String payload = http.getString();
    StaticJsonDocument<512> resp;
    DeserializationError err = deserializeJson(resp, payload);
    if (!err) {
      if (resp.containsKey("current_stock")) {
        int stock = resp["current_stock"].as<int>();
        updateLCD((String("Stock: ") + stock).c_str(), ("Code: " + currentDisplayCode).c_str());
      }
    }
  } else {
    Serial.printf("Failed to fetch status: %d\n", httpCode);
  }
  http.end();
}

// ===== WebSocket Event Handler =====
void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
  switch (type) {
    case WStype_DISCONNECTED:
      Serial.println("WebSocket disconnected");
      updateLCD("Disconnected");
      wsConnected = false;
      break;

    case WStype_CONNECTED:
      Serial.println("Connected to server");
      updateLCD("Connected", "Unlocked");
      wsConnected = true;
      sendRegister();
      sendJSON("status", "unlocked");
      fetchDisplayCode();
      fetchMachineStatus();
      break;

    case WStype_TEXT:
      {
        Serial.printf("Received: %s\n", payload);
        StaticJsonDocument<256> doc;
        DeserializationError error = deserializeJson(doc, payload);
        if (error) return;

        const char* msgType = doc["type"];

        if (strcmp(msgType, "status") == 0) {
          const char* newStatus = doc["value"];
          if (strcmp(newStatus, "locked") == 0 && state == UNLOCKED) {
            state = LOCKED;
            lockStartTime = millis();
            updateLCD("Locked", "Waiting...");
            Serial.println("State changed: LOCKED");
          } else if (strcmp(newStatus, "unlocked") == 0) {
            state = UNLOCKED;
            Serial.println("State changed: UNLOCKED");
            updateLCD("Unlocked", ("Code: " + currentDisplayCode).c_str());
            fetchDisplayCode();
          }
        }

        else if (strcmp(msgType, "lock") == 0) {
          if (state == UNLOCKED) {
            state = LOCKED;
            lockStartTime = millis();
            updateLCD("Locked", "Waiting...");
            Serial.println("State changed: LOCKED (server)");
          }
        }

        else if (strcmp(msgType, "unlock") == 0) {
          if (state != UNLOCKED) {
            state = UNLOCKED;
            Serial.println("State changed: UNLOCKED (server)");
            updateLCD("Unlocked", ("Code: " + currentDisplayCode).c_str());
          }
          fetchDisplayCode();
        }

        else if (strcmp(msgType, "command") == 0) {
          const char* action = doc["action"];
          if (strcmp(action, "dispense") == 0 && state == LOCKED) {
            if (doc.containsKey("transaction_id")) {
              currentTransactionId = doc["transaction_id"].as<String>();
            }

            unsigned long duration = 0;
            if (doc.containsKey("duration_sec")) {
              duration = doc["duration_sec"].as<unsigned long>() * 1000UL;
            } else if (doc.containsKey("duration")) {
              duration = doc["duration"].as<unsigned long>() * BASE_RUN_TIME;
            } else {
              duration = BASE_RUN_TIME;
            }

            motorRunForward(duration);
          }
        }

        else if (strcmp(msgType, "stock_update") == 0) {
          int stock = doc["stock"].as<int>();
          Serial.printf("Stock update received: %d\n", stock);
          updateLCD((String("Stock: ") + stock).c_str(), ("Code: " + currentDisplayCode).c_str());
        }

        else if (strcmp(msgType, "display_code") == 0) {
          const char* code = doc["value"];
          currentDisplayCode = String(code);
          Serial.printf("Display code received: %s\n", code);
          if (state == UNLOCKED) {
            updateLCD("Unlocked", ("Code: " + currentDisplayCode).c_str());
          }
        }
      }
      break;
  }
}

// ===== Setup =====
void setup() {
  Serial.begin(115200);

  // Initialize I2C and LCD
  Wire.begin();  // Initialize I2C (default pins: SDA=21, SCL=22 on ESP32)
  lcd.init();    // Initialize the LCD
  lcd.backlight(); // Turn on the backlight
  lcd.clear();   // Clear the display
  lcd.setCursor(0, 0);
  lcd.print("SmartVend");
  delay(1000);

  // Motor setup
  pinMode(ENA, OUTPUT);
  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  motorStop();

  updateLCD("Connecting WiFi", "...");

  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected");
  updateLCD("WiFi Connected");

  // Connect over plain WebSocket to FastAPI (no SSL)
  webSocket.begin(serverHost, serverPort, serverPath);
  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(5000);
  // Respond to server heartbeats and keep connection stable
  webSocket.enableHeartbeat(15000, 3000, 2);
}

// ===== Main Loop =====
void loop() {
  webSocket.loop();
  unsigned long now = millis();

  if (state == UNLOCKED) {
    if (now - lastPost > POST_INTERVAL) {
      StaticJsonDocument<200> doc;
      doc["type"] = "status";
      doc["value"] = "active";
      String message;
      serializeJson(doc, message);
      webSocket.sendTXT(message);
      lastPost = now;
    }

    if (now - lastFetch > FETCH_INTERVAL) {
      fetchDisplayCode();
      lastFetch = now;
    }
  }

  if (state == LOCKED) {
    if (now - lockStartTime > LOCK_DURATION) {
      Serial.println("Lock timeout expired — returning to UNLOCKED");
      state = UNLOCKED;
      sendJSON("status", "unlocked");
      updateLCD("Unlocked", ("Code: " + currentDisplayCode).c_str());
    }
  }

  if (motorRunning && (now - motorStartTime > motorRunDuration)) {
    motorStop();
    motorRunning = false;
    updateLCD("Locked", "Waiting...");

    if (currentTransactionId.length() > 0) {
      sendConfirmDispense(motorRunDuration);
      currentTransactionId = "";
    }
  }
}
