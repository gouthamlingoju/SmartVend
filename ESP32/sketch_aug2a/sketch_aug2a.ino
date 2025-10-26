/* SmartVend - ESP32 vending controller (cloud online version)
   - Connects to Wi-Fi and hosted FastAPI backend via HTTPS
   - Polls /api/machine/<id>/status
   - Unlocks, dispenses, confirms dispensed items
   - Token-based authentication for security

   Libraries required:
   - LiquidCrystal_I2C
   - ArduinoJson (v6)
   - ESP32Servo
*/

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <ESP32Servo.h>

// ===== CONFIG =====
const char* WIFI_SSID = "Goutham's Galaxy";       // <- change
const char* WIFI_PASSWORD = "23456789";           // <- change

const char* BACKEND_URL = "https://smartvend-api.onrender.com";  // Your hosted backend
const char* MACHINE_ID = "M1";                    // Unique machine ID
const char* MACHINE_API_KEY = "sv_m1_3h5k9d";    // Secure API key for auth

// Intervals (ms)
const unsigned long CODE_FETCH_INTERVAL = 30000UL;     // fetch new code when idle
const unsigned long STATUS_POLL_INTERVAL = 2000UL;     // poll status when waiting
const unsigned long UNLOCK_TIMEOUT_MS = 120000UL;      // 2 minutes allowed after unlock
const unsigned long NETWORK_RETRY_INTERVAL = 5000UL;

// Hardware pins
const int SDA_PIN = 21;
const int SCL_PIN = 22;
const int MOTOR_PIN = 26;
const int SERVO_PIN = 25;
const int BUZZER_PIN = 27;
const int LED_PIN = 2;

// Motor / dispensing parameters
const unsigned long MOTOR_ON_MS_PER_ITEM = 1000UL;
const unsigned long MOTOR_PAUSE_MS = 400UL;

// ===== Globals =====
LiquidCrystal_I2C lcd(0x27, 16, 2);
Servo lockServo;

String currentCode = "";
String displayedCode = "";
bool isUnlocked = false;
unsigned long unlockTimestamp = 0;

unsigned long lastCodeFetch = 0;
unsigned long lastStatusPoll = 0;
unsigned long lastNetworkAttempt = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  pinMode(MOTOR_PIN, OUTPUT);
  digitalWrite(MOTOR_PIN, LOW);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  Wire.begin(SDA_PIN, SCL_PIN);
  lcd.init();
  lcd.backlight();
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("SmartVend Booting");
  lcd.setCursor(0, 1);
  lcd.print("Connecting WiFi");

  lockServo.attach(SERVO_PIN);
  lock(); // start locked

  connectWiFi();
  lcd.clear();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    digitalWrite(LED_PIN, LOW);
    unsigned long now = millis();
    if (now - lastNetworkAttempt > NETWORK_RETRY_INTERVAL) {
      lastNetworkAttempt = now;
      connectWiFi();
    }
    delay(100);
    return;
  } else {
    digitalWrite(LED_PIN, HIGH);
  }

  unsigned long now = millis();

  if (isUnlocked) {
    if (now - lastStatusPoll > STATUS_POLL_INTERVAL) {
      lastStatusPoll = now;
      checkStatusAndAct();
    }

    if (now - unlockTimestamp > UNLOCK_TIMEOUT_MS) {
      Serial.println("Unlock timeout reached -> relocking");
      sendTimeoutReport();
      lock();
      isUnlocked = false;
      displayedCode = "";
    }

  } else {
    if (now - lastCodeFetch > CODE_FETCH_INTERVAL) {
      lastCodeFetch = now;
      fetchCode();
    }
    if (now - lastStatusPoll > STATUS_POLL_INTERVAL) {
      lastStatusPoll = now;
      checkStatusAndAct();
    }
  }

  delay(10);
}

// ===== WiFi =====
void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("Connecting to WiFi %s\n", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long start = millis();
  const unsigned long WIFI_TIMEOUT = 15000UL;
  while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_TIMEOUT) {
    delay(200);
    Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected");
    Serial.print("IP: ");
    Serial.println(WiFi.localIP());
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("WiFi Connected");
    lcd.setCursor(0, 1);
    lcd.print(WiFi.localIP().toString().c_str());
    delay(1200);
  } else {
    Serial.println("\nWiFi connect FAILED");
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("WiFi Failed");
  }
}

// ===== Backend comms =====
String backendGet(const String& path) {
  WiFiClientSecure client;
  client.setInsecure(); // skip cert validation for simplicity
  HTTPClient https;

  String url = String(BACKEND_URL) + path;
  https.begin(client, url);
  https.addHeader("Authorization", String("Bearer ") + MACHINE_API_KEY);
  https.setTimeout(5000);

  int code = https.GET();
  String payload = "";
  if (code > 0) {
    payload = https.getString();
    Serial.printf("HTTP GET %s -> %d\n", url.c_str(), code);
  } else {
    Serial.printf("HTTP GET failed: %s -> %d\n", url.c_str(), code);
  }
  https.end();
  return payload;
}

bool backendPostJson(const String& path, const String& jsonBody) {
  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient https;

  String url = String(BACKEND_URL) + path;
  https.begin(client, url);
  https.addHeader("Content-Type", "application/json");
  https.addHeader("Authorization", String("Bearer ") + MACHINE_API_KEY);
  https.setTimeout(5000);

  int code = https.POST(jsonBody);
  if (code > 0) {
    String resp = https.getString();
    Serial.printf("POST %s -> %d\n", url.c_str(), code);
    https.end();
    return (code >= 200 && code < 300);
  } else {
    Serial.printf("POST failed: %s -> %d\n", url.c_str(), code);
    https.end();
    return false;
  }
}

// ===== High-level flows =====
void fetchCode() {
  String resp = backendGet("/api/machine/" + String(MACHINE_ID) + "/status");
  if (resp.length() == 0) return;

  StaticJsonDocument<256> doc;
  DeserializationError err = deserializeJson(doc, resp);
  if (err) { Serial.println("JSON parse error"); return; }

  const char* code = doc["code"];
  if (code) {
    currentCode = String(code);
    displayedCode = currentCode;
    showCodeOnLCD(currentCode);
    Serial.printf("Received code: %s\n", currentCode.c_str());
  }
}

void checkStatusAndAct() {
  String resp = backendGet("/api/machine/" + String(MACHINE_ID) + "/status");
  if (resp.length() == 0) return;

  StaticJsonDocument<512> doc;
  DeserializationError err = deserializeJson(doc, resp);
  if (err) { Serial.println("Status JSON parse error"); return; }

  String sStatus = doc["status"] | "idle";
  String sCode = doc["code"] | "";

  int quantity = doc["quantity"] | 0;

  if (sStatus == "unlock" && sCode == displayedCode && !isUnlocked) {
    unlock();
    isUnlocked = true;
    unlockTimestamp = millis();
    lcd.clear();
    lcd.setCursor(0,0);
    lcd.print("UNLOCKED");
    lcd.setCursor(0,1);
    lcd.print("Please take item");
    beep(2);
    return;
  }

  if (sStatus == "dispense" && sCode == displayedCode) {
    if (!isUnlocked) { unlock(); isUnlocked = true; unlockTimestamp = millis(); delay(400); }
    performDispense(quantity);
    return;
  }

  if (sStatus == "idle" && isUnlocked) {
    lock();
    isUnlocked = false;
    displayedCode = "";
    lcd.clear();
  }
}

void performDispense(int qty) {
  if (qty <= 0) qty = 1;
  lcd.clear(); lcd.setCursor(0,0); lcd.print("Dispensing...");

  int dispensed = 0;
  for (int i = 0; i < qty; i++) {
    digitalWrite(MOTOR_PIN, HIGH); delay(MOTOR_ON_MS_PER_ITEM);
    digitalWrite(MOTOR_PIN, LOW);
    dispensed++;
    delay(MOTOR_PAUSE_MS);
  }

  StaticJsonDocument<256> doc;
  doc["machine_id"] = MACHINE_ID;
  doc["code"] = displayedCode;
  doc["dispensed"] = dispensed;
  doc["status"] = "success";

  String out; serializeJson(doc, out);
  backendPostJson("/api/machine/" + String(MACHINE_ID) + "/confirm", out);

  lcd.clear(); lcd.setCursor(0,0); lcd.print("Take your item");
  lcd.setCursor(0,1); lcd.print("Thank you!");
  beep(2);
  delay(3000);

  lock();
  isUnlocked = false;
  displayedCode = "";
}

void sendTimeoutReport() {
  StaticJsonDocument<256> doc;
  doc["machine_id"] = MACHINE_ID;
  doc["code"] = displayedCode;
  doc["error"] = "unlock_timeout";
  String out; serializeJson(doc, out);
  backendPostJson("/api/machine/" + String(MACHINE_ID) + "/report-error", out);
}

// ===== lock/unlock hardware =====
void lock() { lockServo.write(0); Serial.println("Locked"); }
void unlock() { lockServo.write(90); Serial.println("Unlocked"); }

// ===== UI helpers =====
void showCodeOnLCD(const String& code) {
  lcd.clear();
  lcd.setCursor(0,0); lcd.print("Machine: "); lcd.print(MACHINE_ID);
  lcd.setCursor(0,1); lcd.print("Code: "); lcd.print(code.length()>11 ? code.substring(0,11) : code);
}

void beep(int times) {
  for (int i=0;i<times;i++) {
    digitalWrite(BUZZER_PIN,HIGH); delay(120);
    digitalWrite(BUZZER_PIN,LOW); delay(80);
  }
}
