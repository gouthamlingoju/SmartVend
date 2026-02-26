# **SmartVend ESP32 Device Firmware Specification**

## **1\. Device Overview**

The ESP32 acts as the **embedded controller of the SmartVend machine**.  
Its responsibilities are:

1. Connect to WiFi  
2. Connect to the SmartVend backend server  
3. Display vending codes to users  
4. Receive commands from the server  
5. Control the motor driver to dispense napkins  
6. Send status updates  
7. Confirm completed transactions  
8. Provide a local diagnostic interface  
9. Maintain machine lock/unlock state
10. Hardware Watchdog protection against hangs
11. Motor Jam Detection based on current sensing
12. Multi-WiFi auto-scanned failover reconnection

---

# **2\. Hardware Components Controlled by ESP32**

| Component | Function |
| ----- | ----- |
| ESP32 DevKit V1 | Main controller |
| 16x2 LCD (I2C) | Displays machine status and code |
| L298N Motor Driver | Controls dispensing motor |
| DC Gear Motor | Rotates dispensing coil |
| Buck Converter | Converts 12V → 5V |
| Power Supply | 12V adapter |
| Push buttons (optional) | Maintenance |
| Web control panel | Local testing |

---

# **3\. Pin Mapping**

| ESP32 Pin | Component | Purpose |
| ----- | ----- | ----- |
| GPIO25 | ENA | Motor speed PWM |
| GPIO26 | IN1 | Motor direction |
| GPIO27 | IN2 | Motor direction |
| GPIO21 | SDA | LCD I2C |
| GPIO22 | SCL | LCD I2C |
| GPIO2 | LED | Motor activity indicator |
| GPIO34 | Current Sensor| Motor jam detection (Analog) |

---

# **4\. Device States**

The machine operates in **two main states**.

## **UNLOCKED**

Machine is available for purchase.  
Actions:  
• Shows code on LCD  
• Sends heartbeat to server  
• Waits for purchase  
SmartVend  
Code: 3854

---

## **LOCKED**

Machine is processing a purchase.  
Actions:  
• Wait for dispense command  
• Dispense napkin  
• Confirm transaction  
SmartVend  
Locked

---

# **5\. Boot Sequence**

When ESP32 powers on:

### **Step 1**

Initialize serial  
Serial.begin(115200)

### **Step 2**

Initialize motor pins  
pinMode(ENA, OUTPUT)  
pinMode(IN1, OUTPUT)  
pinMode(IN2, OUTPUT)

Motor stopped.  
---

### **Step 3**

Initialize LCD  
lcd.init()  
lcd.backlight()

Display:  
Connecting WiFi

---

### **Step 4**

Connect to WiFi (Best Network)  
The ESP32 scans for known networks and connects to the one with the strongest signal (best RSSI).

List of known networks:
1. Goutham's Galaxy
2. SmartVendLab
3. HomeWiFi

Wait until connected.  
Display:  
SmartVend
WiFi Connected

---

### **Step 5**

Check server health  
Endpoint  
GET /health

URL  
https://smartvend.onrender.com/health

Retry up to **5 times**.  
---

### **Step 6**

Open WebSocket  
wss://smartvend.onrender.com/ws

Port  
443

---

# **6\. Device Registration**

After WebSocket connects.  
ESP32 sends:

### **Message**

{  
"type":"register",  
"machine\_id":"M001",  
"api\_key":"sv\_001mmsg"  
}

Purpose:  
• Authenticate device  
• Link machine with backend  
---

# **7\. Status Heartbeat**

While **UNLOCKED**, device sends status every:  
1 second

Message:  
{  
"type":"status",  
"value":"active"  
}

Purpose:  
• Server knows machine is alive.  
---

# **8\. Display Code Fetch**

Every **5 minutes** ESP32 asks server for display code.  
Message:  
{  
"type":"fetch\_display"  
}

**Code is strictly generated and rotated on the server** to ensure integrity between DB, Backend, and Machine.

Server responds:  
{  
"type":"display\_code",  
"value":"3854"  
}

ESP32 displays:  
SmartVend  
Code: 3854

---

# **9\. Purchase Flow**

## **Step 1**

User scans QR and pays.  
Backend locks machine.  
Server sends:  
{  
"type":"lock"  
}

ESP32 changes state.  
Display:  
SmartVend
Locked

---

## **Step 2**

Backend confirms payment.  
Server sends:  
{  
"type":"command",  
"action":"dispense",  
"transaction\_id":"TX\_23842",  
"duration":1  
}

---

# **10\. Dispensing Operation**

ESP32 receives dispense command.  
Motor logic:  
IN1 \= HIGH  
IN2 \= LOW  
ENA \= PWM 255

Motor runs.  
Run duration:  
duration \* BASE\_RUN\_TIME

Example  
BASE\_RUN\_TIME \= 2000 ms  
duration \= 1  
motor run \= 2 seconds

---

Display during dispense:  
SmartVend
Dispensing...

LED indicator ON.  
---

# **11\. Dispense Completion**

After motor stops.  
ESP32 sends confirmation.  
Endpoint:  
POST /api/machine/{machine\_id}/confirm

Example:  
POST /api/machine/M001/confirm

Headers:  
Content-Type: application/json  
Authorization: Bearer sv\_001mmsg

Payload:  
{  
"transaction\_id":"TX\_23842",  
"dispensed":1  
}

---

# **12\. Unlock After Completion**

Server sends:  
{  
"type":"unlock"  
}

ESP32 returns to UNLOCKED.  
Display:  
SmartVend  
Code: 4219

---

# **13\. Lock Timeout**

If dispense not triggered within:  
10 minutes

ESP32 automatically unlocks.  
---

# **14\. WebSocket Reconnect**

If connection lost.  
Reconnect every:  
Reconnect every:  
5 seconds (WS) / 30 seconds (WiFi Health Check)

---

# **15\. HTTP Fallback Command Polling**

If WebSocket fails.  
ESP32 polls:  
GET /device/commands/{machine\_id}

Example  
GET /device/commands/M001

Interval:  
15 seconds

---

# **16\. Local Web Control Panel**

ESP32 hosts local server.  
Port  
80

Access  
http://ESP32\_IP

Features:  
• LCD display preview  
• Motor start  
• Motor stop  
• Speed control  
Endpoints:  
GET /  
GET /status  
POST /motor/start  
POST /motor/stop

---

# **17\. Motor Safety**

Motor automatically stops when:  
current\_time \> motor\_start \+ duration

Prevents continuous spinning.  
---

# **18\. Error Handling**

| Error | Action |
| ----- | ----- |
| WiFi lost | reconnect (Best WiFi Scan) |
| WebSocket lost | reconnect |
| Server unreachable | HTTP fallback |
| Motor stuck | Jam Detection Stop -> Report ERROR |
| Software Hang | Hardware Watchdog Reset (10s) |

---

# **19\. Timing Summary**

| Task | Interval |
| ----- | ----- |
| Heartbeat (WS) | 1 sec |
| WiFi Health Check | 30 sec |
| Fetch display code | 5 min |
| HTTP fallback polling | 15 sec |
| Lock timeout | 10 min |
| WebSocket reconnect | 5 sec |
| Hardware Watchdog | 10 sec |

---

# **20\. Security**

Machine authentication uses:  
machine\_id  
api\_key

Example  
M001  
sv\_001mmsg

Used in:  
• register message  
• confirmation API  
---

# **21\. Network Architecture**

User → Web App → Backend → ESP32

Communication types:

| Type | Protocol |
| ----- | ----- |
| Realtime commands | WebSocket |
| Transaction confirmation | HTTPS |
| Fallback polling | HTTPS |

---

# **22\. Power Architecture**

12V Adapter  
   │  
   ├── Motor Driver  
   │  
   └── Buck Converter  
         │  
         ├── ESP32  
         └── LCD

Ground: **Common bus ground**  
---

# **23\. Capacitor Protection**

Added to prevent:  
• motor noise  
• voltage spikes  
• ESP32 reset  
Capacitor placements:

| Location | Purpose |
| ----- | ----- |
| 12V rail | smooth input |
| Buck input | suppress spikes |
| Buck output | stabilize 5V |
| ESP32 supply | noise filtering |
| Motor terminals | EMI suppression |

---

# **24\. Expected Machine Behavior**

Normal cycle:  
Idle → Show code  
User pays  
Machine locks  
Dispense command  
Motor rotates  
Confirm transaction  
Unlock  
Show new code

---

# **25\. Reliability Strategy**

• Heartbeat monitoring  
• Automatic reconnect (Best Signal Scan)  
• Fallback HTTP polling  
• Motor Jam Detection (Current Sensing)
• Hardware Watchdog (10s Task WDT)
• Motor timeout protection  
• Capacitor filtering

### **Production Hardware Logic (GPIO 34)**
The jam detection uses analog samples from GPIO 34. If the reading exceeds **800** for more than **200ms**, the motor is emergency stopped. This state is reported to the backend via WebSocket/HTTP as `motor_jam`.


