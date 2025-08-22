#include <WiFi.h>
#include <WebServer.h>

// Replace with your WiFi credentials
const char* ssid = "Goutham's Galaxy";
const char* password = "23456789";

// Motor control pins
#define IN1 26
#define IN2 27
#define ENA 14 // PWM-capable pin for speed

WebServer server(80);

void setup() {
  Serial.begin(115200);

  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  pinMode(ENA, OUTPUT);

  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("\nConnected. IP address: ");
  Serial.println(WiFi.localIP());

  server.on("/", handleRoot);
  server.on("/forward", handleForward);
  server.on("/backward", handleBackward);
  server.on("/stop", handleStop);

  server.begin();
  Serial.println("HTTP server started");
}

void loop() {
  server.handleClient();
}

void handleRoot() {
  server.send(200, "text/html", R"rawliteral(
    <!DOCTYPE html>
    <html>
    <head>
      <title>Motor Control</title>
      <style>
        button { width: 100px; height: 50px; margin: 10px; font-size: 16px; }
      </style>
    </head>
    <body>
      <h1>ESP32 Motor Control</h1>
      <button onclick="location.href='/forward'">Forward</button>
      <button onclick="location.href='/backward'">Backward</button>
      <button onclick="location.href='/stop'">Stop</button>
    </body>
    </html>
  )rawliteral");
}

void handleForward() {
  if (server.hasArg("n")) {
    int duration = server.arg("n").toInt();
    if (duration <= 0 || duration > 10) { // optional safety limit
      server.send(400, "text/plain", "Invalid duration");
      return;
    }

    digitalWrite(IN1, HIGH);
    digitalWrite(IN2, LOW);
    analogWrite(ENA, 200); // Adjust speed as needed
    delay(duration * 1000); // Run motor for n seconds

    // Stop the motor after delay
    digitalWrite(IN1, LOW);
    digitalWrite(IN2, LOW);
    analogWrite(ENA, 0);

    server.send(200, "text/plain", "Motor ran forward for " + String(duration) + " seconds");
  } else {
    server.send(400, "text/plain", "Missing 'n' parameter");
  }
}


void handleBackward() {
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, HIGH);
  analogWrite(ENA, 200); // speed: 0-255
  server.sendHeader("Location", "/");
  server.send(303);
}

void handleStop() {
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, LOW);
  analogWrite(ENA, 0);
  server.sendHeader("Location", "/");
  server.send(303);
}
