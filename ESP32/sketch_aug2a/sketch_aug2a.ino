#include <WiFi.h>
#include <WiFiClientSecure.h>

#include <WebSocketsClient.h>

#include <ArduinoJson.h>

#include <LiquidCrystal_I2C.h>

#include <HTTPClient.h>



// ===== WiFi & Server =====

const char* ssid = "Goutham's Galaxy";
const char* password = "23456789";

// Render deployment host and HTTPS/WebSocket settings
const char* serverHost = "smartvend.onrender.com";  // Render host
const char* serverHttps = "https://smartvend.onrender.com";  // HTTPS API endpoint
const int serverPort = 443;
const char* serverPath = "/ws";

// Unique identifier for this machine (set to your machine's ID)

const char* machine_id = "M001";

// API key if your server expects one; set to "none" if not used

const char* machine_api_key = "sv_001mmsg";



WebSocketsClient webSocket;



// ===== LCD Setup =====

LiquidCrystal_I2C lcd(0x27, 16, 2);  // Adjust I2C address if needed (try 0x3F if 0x27 fails)



// ===== Motor Driver Pins =====

const int ENA = 25;   // PWM

const int IN1 = 26;

const int IN2 = 27;



// ===== State Machine =====

Enum DeviceState { UNLOCKED, LOCKED };

DeviceState state = UNLOCKED;



bool motorRunning = false;

unsigned long motorStartTime = 0;

unsigned long motorRunDuration = 0;  // dynamically set by server



// timing constants

const unsigned long POST_INTERVAL = 1000;    // 1 second

const unsigned long FETCH_INTERVAL = 300000; // 5 minutes

const unsigned long LOCK_DURATION = 600000;  // 10 minutes

const unsigned long BASE_RUN_TIME = 2000;   // 2 seconds per unit (adjust to your motor)



unsigned long lastPost = 0;
unsigned long lastFetch = 0;
unsigned long lastCommandPoll = 0;
unsigned long lockStartTime = 0;

String currentDisplayCode = "----"; // default blank code
String currentTransactionId = ""; // to hold transaction ID during dispense
unsigned long dispenseQuantity = 0; // to hold quantity for confirmation

// networking clients
WiFiClientSecure secureClient;



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



void sendConfirmation(unsigned long dispensed_qty) {

  if (WiFi.status() == WL_CONNECTED) {

    HTTPClient http;
    secureClient.setInsecure(); // TODO: pin CA for production

    String url = String(serverHttps) + "/api/machine/" + machine_id + "/confirm";

    http.begin(secureClient, url);

    http.addHeader("Content-Type", "application/json");

    http.addHeader("Authorization", "Bearer " + String(machine_api_key));



    StaticJsonDocument<200> doc;

    doc["transaction_id"] = currentTransactionId;

    doc["dispensed"] = dispensed_qty;



    String requestBody;

    serializeJson(doc, requestBody);



    int httpResponseCode = http.POST(requestBody);



    if (httpResponseCode > 0) {

      String response = http.getString();

      Serial.println(httpResponseCode);

      Serial.println(response);

    } else {

      Serial.print("Error on sending POST: ");

      Serial.println(httpResponseCode);

    }



    http.end();

  } else {

    Serial.println("WiFi Disconnected");

  }

}


bool waitForHealth() {
  // Render free tier may cold start; poll /health with simple backoff
  for (int attempt = 0; attempt < 5; attempt++) {
    HTTPClient http;
    secureClient.setInsecure(); // TODO: pin CA for production
    String url = String(serverHttps) + "/health";
    if (http.begin(secureClient, url)) {
      int code = http.GET();
      http.end();
      if (code == 200) {
        Serial.println("Backend health OK");
        return true;
      }
    }
    unsigned long backoff = 500 * (attempt + 1);
    Serial.printf("Health check retry in %lums\n", backoff);
    delay(backoff);
  }
  return false;
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



        if (strcmp(msgType, "lock") == 0 && state == UNLOCKED) {

          state = LOCKED;

          lockStartTime = millis();

          updateLCD("Locked", "Waiting...");

          Serial.println("State changed: LOCKED");

        } else if (strcmp(msgType, "unlock") == 0) {

          state = UNLOCKED;

          Serial.println("State changed: UNLOCKED");

          updateLCD("Unlocked", ("Code: " + currentDisplayCode).c_str());

          fetchDisplayCode();

        }



        else if (strcmp(msgType, "command") == 0) {

          const char* action = doc["action"];

          if (strcmp(action, "dispense") == 0 && state == LOCKED) {

            currentTransactionId = doc["transaction_id"].as<String>();

            dispenseQuantity = doc["duration"].as<unsigned long>();

            unsigned long quantity = doc["duration"].as<unsigned long>();



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

  // Cold start guard
  waitForHealth();



  // HTTPS client
  secureClient.setInsecure(); // TODO: pin CA for production

  // WebSocket setup over TLS (wss)
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

      sendJSON("status", "active");

      lastPost = now;

    }

    // HTTP command polling fallback when WS is unavailable
    if ((now - lastCommandPoll > 15000) && webSocket.isConnected() == false) {
      HTTPClient http;
      secureClient.setInsecure(); // TODO: pin CA for production
      String url = String(serverHttps) + "/device/commands/" + machine_id;
      if (http.begin(secureClient, url)) {
        int httpCode = http.GET();
        if (httpCode == 200) {
          String payload = http.getString();
          StaticJsonDocument<512> doc;
          if (deserializeJson(doc, payload) == DeserializationError::Ok) {
            JsonArray cmds = doc["commands"].as<JsonArray>();
            for (JsonObject cmd : cmds) {
              const char* type = cmd["type"] | "";
              if (strcmp(type, "lock") == 0 && state == UNLOCKED) {
                state = LOCKED;
                lockStartTime = millis();
                updateLCD("Locked", "Waiting...");
              } else if (strcmp(type, "unlock") == 0) {
                state = UNLOCKED;
                updateLCD("Unlocked", ("Code: " + currentDisplayCode).c_str());
                fetchDisplayCode();
              } else if (strcmp(type, "command") == 0) {
                const char* action = cmd["action"] | "";
                if (strcmp(action, "dispense") == 0 && state == LOCKED) {
                  currentTransactionId = cmd["transaction_id"].as<String>();
                  dispenseQuantity = cmd["duration"] | 1;
                  unsigned long duration = (cmd.containsKey("duration_sec")
                                                ? cmd["duration_sec"].as<unsigned long>() * 1000UL
                                                : dispenseQuantity * BASE_RUN_TIME);
                  motorRunForward(duration);
                }
              }
            }
          }
        }
        http.end();
      }
      lastCommandPoll = now;
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

    sendConfirmation(dispenseQuantity);

    updateLCD("Locked", "Waiting...");

  }

}