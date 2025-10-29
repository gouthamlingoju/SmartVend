#include <WiFi.h>
#include <WebSocketsClient.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <LiquidCrystal_I2C.h>

// ===== WiFi & Server =====
const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";
const char* serverHost = "my-fastapi-app.onrender.com";  // your Render WebSocket host
const char* serverHttps = "https://my-fastapi-app.onrender.com";  // HTTP API endpoint
const int serverPort = 443;
const char* serverPath = "/ws";
// Unique identifier for this machine (set to your machine's ID)
const char* machine_id = "MACHINE_123";
// API key if your server expects one; set to "none" if not used
const char* machine_api_key = "none";

WebSocketsClient webSocket;

// ===== LCD Setup =====
LiquidCrystal_I2C lcd(0x27, 16, 2);  // Adjust I2C address if needed (try 0x3F if 0x27 fails)

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
int currentStock = 50;  // Track current stock level
String currentTransactionId = "";  // Track current transaction for confirmation

// timing constants
const unsigned long POST_INTERVAL = 1000;    // 1 second
const unsigned long FETCH_INTERVAL = 300000; // 5 minutes
const unsigned long LOCK_DURATION = 600000;  // 10 minutes
const unsigned long BASE_RUN_TIME = 20000;   // 20 seconds per unit (adjust to your motor)

unsigned long lastPost = 0;
unsigned long lastFetch = 0;
unsigned long lockStartTime = 0;

String currentDisplayCode = "----"; // default blank code

// ===== Helper Functions =====
void updateLCD(const char* line1, const char* line2 = "") {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print(line1);
  lcd.setCursor(0, 1);
  lcd.print(line2);

  // Mirror to Serial Monitor
  Serial.println("========== LCD ==========");
  Serial.println(line1);
  Serial.println(line2);
  Serial.println("=========================");
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
  updateLCD("Dispensing...", "");
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

void checkLowStock() {
  if (currentStock <= 10) {  // Alert threshold
    HTTPClient http;
    String url = String(serverHttps) + "/low-stock-alert";
    http.begin(url);
    http.addHeader("Content-Type", "application/json");

    StaticJsonDocument<200> doc;
    doc["machineID"] = machine_id;
    doc["Remaining"] = currentStock;
    
    String requestBody;
    serializeJson(doc, requestBody);
    
    http.POST(requestBody);
    http.end();
  }
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

// ===== WebSocket Event Handler =====
void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
  switch (type) {
    case WStype_DISCONNECTED:
      Serial.println("WebSocket disconnected");
      updateLCD("Disconnected", "");
      break;

    case WStype_CONNECTED:
      Serial.println("Connected to server");
      updateLCD("Connected", "Unlocked");
      // Register this device with the server, then send status and fetch code
      sendRegister();
      sendJSON("status", "unlocked");
      fetchDisplayCode(); // Fetch display code immediately
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

        else if (strcmp(msgType, "command") == 0) {
          const char* action = doc["action"];
          if (strcmp(action, "dispense") == 0 && state == LOCKED) {
            // Store transaction ID for confirmation
            if (doc.containsKey("transaction_id")) {
              currentTransactionId = doc["transaction_id"].as<String>();
            }

            // Check stock
            int requestedQuantity = doc.containsKey("quantity") ? doc["quantity"].as<int>() : 1;
            if (currentStock < requestedQuantity) {
              reportError("insufficient_stock");
              return;
            }

            unsigned long duration = 0;

            // Option 1: direct seconds from server
            if (doc.containsKey("duration_sec")) {
              duration = doc["duration_sec"].as<unsigned long>() * 1000UL;
            }
            // Option 2: multiplier units
            else if (doc.containsKey("duration")) {
              duration = doc["duration"].as<unsigned long>() * BASE_RUN_TIME;
            }
            // fallback default
            else {
              duration = BASE_RUN_TIME;
            }

            motorRunForward(duration);
            
            // Update stock after successful dispense start
            currentStock -= requestedQuantity;
            checkLowStock();
          }
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

  // Motor setup
  pinMode(ENA, OUTPUT);
  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  motorStop();

  // LCD setup
  lcd.init();
  lcd.backlight();
  updateLCD("Connecting WiFi", "...");

  // Wi-Fi
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected");
  updateLCD("WiFi Connected", "");

  // WebSocket setup
  webSocket.beginSSL(serverHost, serverPort, serverPath);
  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(5000);
}

// ===== Main Loop =====
void loop() {
  webSocket.loop();
  unsigned long now = millis();

  // Unlocked behavior
  if (state == UNLOCKED) {
    if (now - lastPost > POST_INTERVAL) {
      // Send richer status including stock level
      StaticJsonDocument<200> doc;
      doc["type"] = "status";
      doc["value"] = "active";
      doc["stock"] = currentStock;
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

  // Locked timeout
  if (state == LOCKED) {
    if (now - lockStartTime > LOCK_DURATION) {
      Serial.println("Lock timeout expired — returning to UNLOCKED");
      state = UNLOCKED;
      sendJSON("status", "unlocked");
      updateLCD("Unlocked", ("Code: " + currentDisplayCode).c_str());
    }
  }

  // Motor control timing
  if (motorRunning && (now - motorStartTime > motorRunDuration)) {
    motorStop();
    motorRunning = false;
    updateLCD("Locked", "Waiting...");
    
    // Confirm successful dispense with backend
    if (currentTransactionId.length() > 0) {
      sendConfirmDispense(1);  // Confirm 1 successful dispense
      currentTransactionId = "";  // Clear transaction
    }
  }
}
