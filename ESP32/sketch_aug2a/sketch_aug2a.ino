#include <WiFi.h>
#include <WiFiClientSecure.h>

#include <WebSocketsClient.h>

#include <ArduinoJson.h>

#include <LiquidCrystal_I2C.h>

#include <HTTPClient.h>

#include <WebServer.h>
#include <esp_task_wdt.h>

// ===== WiFi & Server =====

struct WiFiNetwork {
  const char *ssid;
  const char *password;
};

WiFiNetwork networks[] = {{"Goutham's Galaxy", "23456789"},
                          {"VNRVJIET_WIFI", "vnrvjiet@123"},
                          {"VNRVJIET_E", "vnrvjiet@123"}};

const int networkCount = sizeof(networks) / sizeof(networks[0]);

// Render deployment host and HTTPS/WebSocket settings
const char *serverHost = "smartvend.onrender.com"; // Render host
const char *serverHttps =
    "https://smartvend.onrender.com"; // HTTPS API endpoint
const int serverPort = 443;
const char *serverPath = "/ws";

// Unique identifier for this machine (set to your machine's ID)

const char *machine_id = "M001";

// API key if your server expects one; set to "none" if not used

const char *machine_api_key = "sv_001mmsg";

WebSocketsClient webSocket;

// Web server for local control interface
WebServer server(80);

// ===== LCD Setup =====

LiquidCrystal_I2C
    lcd(0x27, 16, 2); // Adjust I2C address if needed (try 0x3F if 0x27 fails)

// ===== Motor Driver Pins =====

const int ENA = 25; // PWM

const int IN1 = 26;

const int IN2 = 27;

// Built-in LED pin (GPIO 2 for most ESP32 boards)
const int LED_BUILTIN_PIN = 2;

// Jam Detection
const int JAM_SENSOR_PIN = 34; // GPIO 34 (Analog)
const int JAM_CURRENT_THRESHOLD =
    800; // Adjust based on your sensor calibration
unsigned long jamStartTime = 0;
const int JAM_DURATION_THRESHOLD = 200; // ms

// ===== State Machine =====

enum DeviceState { UNLOCKED, LOCKED };

DeviceState state = UNLOCKED;

bool motorRunning = false;

unsigned long motorStartTime = 0;

unsigned long motorRunDuration = 0; // dynamically set by server

// timing constants

const unsigned long POST_INTERVAL = 1000; // 1 second

const unsigned long FETCH_INTERVAL = 300000; // 5 minutes

const unsigned long LOCK_DURATION = 600000; // 10 minutes

const unsigned long BASE_RUN_TIME =
    2000; // 2 seconds per unit (adjust to your motor)

unsigned long lastPost = 0;
unsigned long lastFetch = 0;
unsigned long lastCommandPoll = 0;
unsigned long lockStartTime = 0;
unsigned long lastWiFiCheck = 0;
const unsigned long WIFI_CHECK_INTERVAL = 30000; // 30 seconds

String currentDisplayCode = "----"; // default blank code
String currentTransactionId = "";   // to hold transaction ID during dispense
unsigned long dispenseQuantity = 0; // to hold quantity for confirmation

// LCD display lines for web interface
String lcdLine1 = "";
String lcdLine2 = "";

// Manual motor control variables
int manualMotorSpeed = 255;      // Default speed (0-255)
bool manualMotorControl = false; // Flag to indicate manual control

// networking clients
WiFiClientSecure secureClient;

// ===== Helper Functions =====

void updateLCD(const char *line2 = "") {

  lcd.clear();

  lcd.setCursor(0, 0);
  lcd.print("SmartVend");

  lcd.setCursor(0, 1);
  lcd.print(line2);

  // Store for web interface
  lcdLine1 = "SmartVend";
  lcdLine2 = String(line2);

  // Mirror to Serial Monitor
  Serial.println("========== LCD ==========");
  Serial.println("SmartVend");
  Serial.println(line2);
  Serial.println("=========================");
}

void motorStop() {

  digitalWrite(IN1, LOW);

  digitalWrite(IN2, LOW);

  analogWrite(ENA, 0);

  digitalWrite(LED_BUILTIN_PIN, LOW); // Turn off LED when motor stops

  Serial.println("Motor stopped");
}

void motorRunForward(unsigned long durationMs) {

  digitalWrite(IN1, HIGH);

  digitalWrite(IN2, LOW);

  analogWrite(ENA, 200); // Adjust speed (0–255)

  digitalWrite(LED_BUILTIN_PIN, HIGH); // Turn on LED when motor runs

  motorRunning = true;

  motorStartTime = millis();

  motorRunDuration = durationMs;

  Serial.printf("Motor running for %lu ms\n", durationMs);

  updateLCD("Dispensing...");
}

void sendJSON(const char *type, const char *value) {

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

    String url =
        String(serverHttps) + "/api/machine/" + machine_id + "/confirm";

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

// ===== Web Server Functions =====

void handleRoot() {
  String html =
      "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\"><meta "
      "name=\"viewport\" content=\"width=device-width, "
      "initial-scale=1.0\"><title>SmartVend Control "
      "Panel</"
      "title><style>*{margin:0;padding:0;box-sizing:border-box;}body{font-"
      "family:'Segoe "
      "UI',Tahoma,Geneva,Verdana,sans-serif;background:linear-gradient(135deg,#"
      "667eea 0%,#764ba2 "
      "100%);min-height:100vh;padding:20px;display:flex;justify-content:center;"
      "align-items:center;}.container{background:white;border-radius:20px;box-"
      "shadow:0 20px 60px "
      "rgba(0,0,0,0.3);padding:30px;max-width:600px;width:100%;}h1{color:#333;"
      "margin-bottom:30px;text-align:center;font-size:28px;}.status-section{"
      "background:#f5f5f5;border-radius:15px;padding:20px;margin-bottom:30px;"
      "border:2px solid "
      "#e0e0e0;}.status-title{font-size:18px;font-weight:bold;color:#555;"
      "margin-bottom:15px;text-align:center;}.lcd-display{background:#1a1a1a;"
      "color:#00ff00;font-family:'Courier "
      "New',monospace;padding:20px;border-radius:10px;text-align:center;margin-"
      "bottom:15px;box-shadow:inset 0 2px 10px "
      "rgba(0,0,0,0.5);}.lcd-line{font-size:20px;margin:8px "
      "0;min-height:28px;display:flex;align-items:center;justify-content:"
      "center;}.status-info{display:grid;grid-template-columns:1fr "
      "1fr;gap:10px;margin-top:15px;}.status-item{background:white;padding:"
      "10px;border-radius:8px;text-align:center;}.status-label{font-size:12px;"
      "color:#888;margin-bottom:5px;}.status-value{font-size:18px;font-weight:"
      "bold;color:#333;}.status-value.locked{color:#e74c3c;}.status-value."
      "unlocked{color:#27ae60;}.status-value.running{color:#3498db;}.status-"
      "value.stopped{color:#95a5a6;}.control-section{margin-top:30px;}.control-"
      "title{font-size:18px;font-weight:bold;color:#555;margin-bottom:20px;"
      "text-align:center;}.control-group{margin-bottom:25px;}label{display:"
      "block;margin-bottom:8px;color:#555;font-weight:500;}.speed-control{"
      "display:flex;align-items:center;gap:15px;}input[type=\"range\"]{flex:1;"
      "height:8px;border-radius:5px;background:#ddd;outline:none;-webkit-"
      "appearance:none;}input[type=\"range\"]::-webkit-slider-thumb{-webkit-"
      "appearance:none;appearance:none;width:20px;height:20px;border-radius:50%"
      ";background:#667eea;cursor:pointer;}input[type=\"range\"]::-moz-range-"
      "thumb{width:20px;height:20px;border-radius:50%;background:#667eea;"
      "cursor:pointer;border:none;}.speed-value{font-size:18px;font-weight:"
      "bold;color:#667eea;min-width:50px;text-align:center;}.button-group{"
      "display:grid;grid-template-columns:1fr "
      "1fr;gap:15px;margin-top:20px;}button{padding:15px "
      "30px;border:none;border-radius:10px;font-size:16px;font-weight:bold;"
      "cursor:pointer;transition:all "
      "0.3s;text-transform:uppercase;letter-spacing:1px;}button:hover{"
      "transform:translateY(-2px);box-shadow:0 5px 15px "
      "rgba(0,0,0,0.2);}button:active{transform:translateY(0);}.btn-start{"
      "background:linear-gradient(135deg,#27ae60,#2ecc71);color:white;}.btn-"
      "stop{background:linear-gradient(135deg,#e74c3c,#c0392b);color:white;}."
      "auto-refresh{text-align:center;margin-top:20px;color:#888;font-size:"
      "12px;}</style></head><body><div class=\"container\"><h1>SmartVend "
      "Control Panel</h1><div class=\"status-section\"><div "
      "class=\"status-title\">LCD Display</div><div class=\"lcd-display\"><div "
      "class=\"lcd-line\" id=\"lcdLine1\">----</div><div class=\"lcd-line\" "
      "id=\"lcdLine2\">----</div></div><div class=\"status-info\"><div "
      "class=\"status-item\"><div class=\"status-label\">Machine "
      "State</div><div class=\"status-value\" "
      "id=\"machineState\">UNLOCKED</div></div><div class=\"status-item\"><div "
      "class=\"status-label\">Motor Status</div><div class=\"status-value\" "
      "id=\"motorStatus\">STOPPED</div></div><div class=\"status-item\"><div "
      "class=\"status-label\">Display Code</div><div class=\"status-value\" "
      "id=\"displayCode\">----</div></div><div class=\"status-item\"><div "
      "class=\"status-label\">Motor Speed</div><div class=\"status-value\" "
      "id=\"currentSpeed\">200</div></div></div></div><div "
      "class=\"control-section\"><div class=\"control-title\">Motor "
      "Control</div><div class=\"control-group\"><label>Motor Speed: <span "
      "class=\"speed-value\" id=\"speedDisplay\">200</span> / 255</label><div "
      "class=\"speed-control\"><input type=\"range\" id=\"speedSlider\" "
      "min=\"0\" max=\"255\" value=\"200\" "
      "oninput=\"updateSpeed(this.value)\"><span class=\"speed-value\" "
      "id=\"speedValue\">200</span></div></div><div "
      "class=\"button-group\"><button class=\"btn-start\" "
      "onclick=\"startMotor()\">Start Motor</button><button class=\"btn-stop\" "
      "onclick=\"stopMotor()\">Stop Motor</button></div></div><div "
      "class=\"auto-refresh\">Status updates every 1 "
      "second</div></div><script>let currentSpeed=200;function "
      "updateSpeed(value){currentSpeed=parseInt(value);document.getElementById("
      "'speedDisplay').textContent=currentSpeed;document.getElementById('"
      "speedValue').textContent=currentSpeed;}function "
      "startMotor(){fetch('/motor/"
      "start?speed='+currentSpeed,{method:'POST'}).then(r=>r.json()).then(data="
      ">{console.log('Motor "
      "started:',data);}).catch(e=>console.error('Error:',e));}function "
      "stopMotor(){fetch('/motor/"
      "stop',{method:'POST'}).then(r=>r.json()).then(data=>{console.log('Motor "
      "stopped:',data);}).catch(e=>console.error('Error:',e));}function "
      "updateStatus(){fetch('/"
      "status').then(r=>r.json()).then(data=>{document.getElementById('"
      "lcdLine1').textContent=data.lcdLine1||'----';document.getElementById('"
      "lcdLine2').textContent=data.lcdLine2||'----';const "
      "stateEl=document.getElementById('machineState');stateEl.textContent="
      "data.state||'UNKNOWN';stateEl.className='status-value "
      "'+(data.state==='LOCKED'?'locked':'unlocked');const "
      "motorEl=document.getElementById('motorStatus');motorEl.textContent=data."
      "motorRunning?'RUNNING':'STOPPED';motorEl.className='status-value "
      "'+(data.motorRunning?'running':'stopped');document.getElementById('"
      "displayCode').textContent=data.displayCode||'----';document."
      "getElementById('currentSpeed').textContent=data.motorSpeed||'0';})."
      "catch(e=>console.error('Error fetching "
      "status:',e));}setInterval(updateStatus,1000);updateStatus();</script></"
      "body></html>";
  server.send(200, "text/html", html);
}

void handleStatus() {
  StaticJsonDocument<300> doc;
  doc["lcdLine1"] = lcdLine1;
  doc["lcdLine2"] = lcdLine2;
  doc["state"] = (state == LOCKED) ? "LOCKED" : "UNLOCKED";
  doc["motorRunning"] = motorRunning;
  doc["displayCode"] = currentDisplayCode;
  doc["motorSpeed"] = manualMotorSpeed;
  doc["machineId"] = machine_id;

  String response;
  serializeJson(doc, response);
  server.send(200, "application/json", response);
}

void handleMotorStart() {
  if (server.hasArg("speed")) {
    manualMotorSpeed = server.arg("speed").toInt();
    manualMotorSpeed = constrain(manualMotorSpeed, 0, 255);
  }

  // Start motor manually
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);
  analogWrite(ENA, manualMotorSpeed);
  digitalWrite(LED_BUILTIN_PIN, HIGH); // Turn on LED when motor runs
  motorRunning = true;
  motorStartTime = millis();
  motorRunDuration = 0; // Set to 0 for continuous run (until stopped)
  manualMotorControl = true;

  Serial.printf("Manual motor start at speed %d\n", manualMotorSpeed);

  StaticJsonDocument<100> doc;
  doc["status"] = "started";
  doc["speed"] = manualMotorSpeed;
  String response;
  serializeJson(doc, response);
  server.send(200, "application/json", response);
}

void handleMotorStop() {
  motorStop();
  motorRunning = false;
  manualMotorControl = false;

  Serial.println("Manual motor stop");

  StaticJsonDocument<100> doc;
  doc["status"] = "stopped";
  String response;
  serializeJson(doc, response);
  server.send(200, "application/json", response);
}

// ===== WebSocket Event Handler =====

void webSocketEvent(WStype_t type, uint8_t *payload, size_t length) {

  switch (type) {

  case WStype_DISCONNECTED:

    Serial.println("WebSocket disconnected");

    updateLCD("Disconnected");

    break;

  case WStype_CONNECTED:

    Serial.println("Connected to server");

    updateLCD("Connected");

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

    if (error)
      return;

    const char *msgType = doc["type"];

    if (strcmp(msgType, "lock") == 0 && state == UNLOCKED) {

      state = LOCKED;

      lockStartTime = millis();

      updateLCD("Locked");

      Serial.println("State changed: LOCKED");

    } else if (strcmp(msgType, "unlock") == 0) {

      state = UNLOCKED;

      Serial.println("State changed: UNLOCKED");

      // Don't update LCD here - wait for display_code message
      // The server sends display_code immediately after unlock
      fetchDisplayCode();

    }

    else if (strcmp(msgType, "command") == 0) {

      const char *action = doc["action"];

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

      const char *code = doc["value"];

      currentDisplayCode = String(code);

      Serial.printf("Display code received: %s\n", code);

      // Always update LCD immediately when display code is received
      if (state == UNLOCKED) {

        updateLCD(("Code: " + currentDisplayCode).c_str());
      }
    }

  }

  break;
  }
}

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
    Serial.println("Connecting to: " + String(networks[bestNetwork].ssid));
    WiFi.begin(networks[bestNetwork].ssid, networks[bestNetwork].password);
    while (WiFi.status() != WL_CONNECTED) {
      delay(500);
      Serial.print(".");
    }
    Serial.println("\nWiFi connected");
  } else {
    Serial.println("No known WiFi found");
  }
}

// ===== Setup =====

void setup() {

  Serial.begin(115200);

  // Hardware Watchdog setup (10 second timeout)
  Serial.println("Configuring Watchdog...");
  esp_task_wdt_init(10, true);
  esp_task_wdt_add(NULL); // Add current thread to WDT watch

  randomSeed(esp_random());
  // Motor setup

  pinMode(ENA, OUTPUT);

  pinMode(IN1, OUTPUT);

  pinMode(IN2, OUTPUT);

  // Built-in LED setup
  pinMode(LED_BUILTIN_PIN, OUTPUT);
  digitalWrite(LED_BUILTIN_PIN, LOW); // Start with LED off

  motorStop();

  // LCD setup

  lcd.init();

  lcd.backlight();

  updateLCD("Connecting WiFi");

  // Wi-Fi

  connectToBestWiFi();

  updateLCD("WiFi Connected");

  // Cold start guard
  waitForHealth();

  // HTTPS client
  secureClient.setInsecure(); // TODO: pin CA for production

  // WebSocket setup over TLS (wss)
  webSocket.beginSSL(serverHost, serverPort, serverPath);

  webSocket.onEvent(webSocketEvent);

  webSocket.setReconnectInterval(5000);

  // Web server setup for local control interface
  server.on("/", handleRoot);
  server.on("/status", handleStatus);
  server.on("/motor/start", HTTP_POST, handleMotorStart);
  server.on("/motor/stop", HTTP_POST, handleMotorStop);

  server.begin();
  Serial.println("Web server started");
  Serial.print("Access control panel at: http://");
  Serial.println(WiFi.localIP());
}

// ===== Main Loop =====

void loop() {
  esp_task_wdt_reset(); // Reset watchdog timer

  webSocket.loop();

  // Handle web server requests
  server.handleClient();

  unsigned long now = millis();

  // Auto-Reconnect Logic
  if (now - lastWiFiCheck > WIFI_CHECK_INTERVAL) {
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("WiFi Disconnected! Attempting to reconnect...");
      updateLCD("WiFi Lost", "Reconnecting...");
      connectToBestWiFi();
    }
    lastWiFiCheck = now;
  }

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
              const char *type = cmd["type"] | "";
              if (strcmp(type, "lock") == 0 && state == UNLOCKED) {
                state = LOCKED;
                lockStartTime = millis();
                updateLCD("Locked");
              } else if (strcmp(type, "unlock") == 0) {
                state = UNLOCKED;
                updateLCD(("Code: " + currentDisplayCode).c_str());
                fetchDisplayCode();
              } else if (strcmp(type, "command") == 0) {
                const char *action = cmd["action"] | "";
                if (strcmp(action, "dispense") == 0 && state == LOCKED) {
                  currentTransactionId = cmd["transaction_id"].as<String>();
                  dispenseQuantity = cmd["duration"] | 1;
                  unsigned long duration =
                      (cmd.containsKey("duration_sec")
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

      updateLCD(("Code: " + currentDisplayCode).c_str());
    }
  }

  // Motor control timing
  // Only auto-stop if not under manual control
  if (motorRunning) {
    // Jam Detection
    int currentLevel = analogRead(JAM_SENSOR_PIN);
    if (currentLevel > JAM_CURRENT_THRESHOLD) {
      if (jamStartTime == 0)
        jamStartTime = now;
      if (now - jamStartTime > JAM_DURATION_THRESHOLD) {
        Serial.printf("MOTOR JAMMED! (Level: %d) Stopping...\n", currentLevel);
        motorStop();
        motorRunning = false;
        jamStartTime = 0;
        state = UNLOCKED;
        sendJSON("error", "motor_jam");
        updateLCD("Motor Jam!", "Manual Fix Req");
        return;
      }
    } else {
      jamStartTime = 0;
    }

    if (!manualMotorControl && (now - motorStartTime > motorRunDuration)) {
      motorStop();
      motorRunning = false;
      sendConfirmation(dispenseQuantity);
      updateLCD("Locked");
    }
  }
}
