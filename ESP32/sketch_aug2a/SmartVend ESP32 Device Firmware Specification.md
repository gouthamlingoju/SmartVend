# SmartVend ESP32 Device Firmware Specification — v3.0

## 1. Device Overview

The ESP32 acts as the **embedded controller of the SmartVend machine**.  
v3.0 uses an **OLED display** to render **QR codes** for session-based vending.

### Responsibilities

1. Connect to WiFi (multi-network auto-scan)
2. Connect to SmartVend backend via WebSocket
3. **Generate and display QR codes on OLED** ← NEW in v3.0
4. Receive session lifecycle messages from server
5. Control the motor driver to dispense napkins
6. Confirm completed transactions via HTTPS
7. Provide a local web-based diagnostic interface
8. Hardware Watchdog protection (10s)
9. Motor Jam Detection (current sensing GPIO 34)
10. HTTP fallback command polling

---

## 2. Hardware Components

| Component | Function |
| --- | --- |
| ESP32 DevKit V1 | Main controller |
| **0.96" OLED SSD1306 (128×64px)** | **QR code + status display** ← NEW |
| L298N Motor Driver | Controls dispensing motor |
| DC Gear Motor | Rotates dispensing coil |
| Buck Converter | 12V → 5V |
| 12V Power Adapter | Primary power |
| Current Sensor (GPIO 34) | Motor jam detection |

### Removed from v2.0
- ~~16×2 I2C LCD~~ → Replaced by 0.96" OLED

---

## 3. Pin Mapping

| ESP32 Pin | Component | Purpose |
| --- | --- | --- |
| GPIO25 | ENA | Motor speed PWM |
| GPIO26 | IN1 | Motor direction |
| GPIO27 | IN2 | Motor direction |
| GPIO21 | SDA | OLED I2C data |
| GPIO22 | SCL | OLED I2C clock |
| GPIO2 | LED | Motor activity indicator |
| GPIO34 | Current Sensor | Motor jam detection (Analog) |

### OLED I2C Address
- Default: `0x3C` (common for SSD1306)
- Alternate: `0x3D` (if `0x3C` fails)

---

## 4. Device States (v3.0)

v3.0 replaces the simple LOCKED/UNLOCKED model with a full state machine:

```
BOOTING → IDLE ←→ OFFLINE
            ↓
         IN_USE
            ↓
        DISPENSING
            ↓
        COMPLETED → IDLE (new session)
            |
          ERROR → IDLE (auto-recovery 60s)
```

| State | OLED Display | Description |
| --- | --- | --- |
| **BOOTING** | \"SmartVend\" header + status text | Startup, WiFi connect, health check |
| **IDLE** | \"SmartVend\" header + **QR Code** + \"Scan Me\" | Ready for customer — QR shows session URL |
| **IN_USE** | \"SmartVend\" header + \"IN USE\" + user name | Session claimed, waiting for payment/dispense |
| **DISPENSING** | \"SmartVend\" header + \"Dispensing\" + progress bar | Motor running, animated progress |
| **COMPLETED** | \"SmartVend\" header + \"Done!\" + checkmark | 2-second flash after dispense |
| **ERROR** | \"SmartVend\" header + \"ERROR!\" + message | Jam or hardware failure |
| **OFFLINE** | \"SmartVend\" header + \"Offline\" + \"Reconnecting...\" | Backend unreachable |

---

## 5. Boot Sequence

1. `Serial.begin(115200)`
2. Configure Watchdog (10s timeout)
3. Initialize motor + LED pins → motor stopped
4. **Initialize OLED** (`SSD1306_SWITCHCAPVCC`, address `0x3C`)
5. Display: "Connecting WiFi..."
6. Connect to best WiFi (RSSI scan)
7. Display: "WiFi Connected!"
8. Health check (`GET /health`) — retry 5× with backoff
9. Open WebSocket (`wss://smartvend.onrender.com/ws`)
10. Start local web server (port 80)

---

## 6. WebSocket Protocol (v3.0)

### ESP32 → Server

| Message | When | Purpose |
| --- | --- | --- |
| `{"type":"register","machine_id":"M001","api_key":"sv_001mmsg"}` | On WS connect | Authenticate + create session |
| `{"type":"pong"}` | Response to ping | Keepalive |
| `{"type":"status","value":"timeout"}` | IN_USE timeout | Report local timeout |
| `{"type":"error","value":"motor_jam"}` | Jam detected | Report hardware error |

### Server → ESP32

| Message | When | OLED Action |
| --- | --- | --- |
| `{"type":"session","token":"xK9mBq2P","url":"https://...","expires_at":"..."}` | After register / QR rotation | **Render QR code** |
| `{"type":"claimed","claimed_by_name":"Goutham"}` | User scans QR | Switch to "IN USE" display |
| `{"type":"new_session","token":"pR7nWm4K","url":"https://...","expires_at":"..."}` | After completion / session expiry | **Render new QR code** |
| `{"type":"command","action":"dispense","duration":2,"transaction_id":"..."}` | Payment confirmed | Start motor + show progress |
| `{"type":"ping"}` | Every 30s | ESP32 replies pong |
| `{"type":"stock_update","stock":15}` | Admin refill | Log only (informational) |
| `{"type":"error","error":"..."}` | Server error | Show error screen |

### Removed from v2.0
- ~~`{"type":"lock"}`~~ → Replaced by `{"type":"claimed"}`
- ~~`{"type":"unlock"}`~~ → Replaced by `{"type":"new_session"}`
- ~~`{"type":"display_code","value":"3854"}`~~ → Replaced by `{"type":"session"}`
- ~~`{"type":"fetch_display"}`~~ → No longer needed (server pushes sessions)

---

## 7. QR Code Generation

The ESP32 generates QR codes **on-device** from the session URL.

### URL Format
```
https://smartvend.onrender.com/vend/{machine_id}/{session_token}
```
Example: `https://smartvend.onrender.com/vend/M001/xK9mBq2P`

### QR Parameters
- **Version**: 4 (33×33 modules) — fits ~78 alphanumeric chars
- **Error Correction**: LOW (maximizes data capacity)
- **Scale**: 1-2 pixels per module → fits 64×64 OLED area
- **Library**: [QRCode by ricmoo](https://github.com/ricmoo/QRCode)

### OLED Layout (128×64px)
```
┌─────────────────────────────┐
│  ┌─────────┐   Scan Me     │
│  │         │   M001        │
│  │   QR    │               │
│  │  Code   │   <-- QR      │
│  │         │               │
│  └─────────┘   v3.0        │
└─────────────────────────────┘
   Left 64px      Right 64px
```

---

## 8. Purchase Flow (v3.0)

### Step 1: QR Displayed (STATE_IDLE)  
OLED shows QR code for current session URL.

### Step 2: User Scans QR  
Server sends: `{"type":"claimed","claimed_by_name":"Goutham"}`  
ESP32 switches to "IN USE" display (no more QR visible).

### Step 3: User Pays  
Backend verifies payment, sends dispense command:  
```json
{"type":"command","action":"dispense","duration":2,"transaction_id":"TX_23842"}
```

### Step 4: Dispensing (STATE_DISPENSING)  
Motor runs for `duration × BASE_RUN_TIME (4000ms)`.  
OLED shows progress bar animation.

### Step 5: Confirmation  
Motor stops → ESP32 sends `POST /api/machine/M001/confirm`  
```json
{"transaction_id":"TX_23842","dispensed":2}
```

### Step 6: New Session (STATE_IDLE)  
Server sends `{"type":"new_session","token":"...","url":"..."}` via WS or in confirm response.  
ESP32 renders **new QR code** → ready for next customer.

---

## 9. Dispense Confirmation

**Endpoint**: `POST /api/machine/{machine_id}/confirm`

**Headers**:
```
Content-Type: application/json
Authorization: Bearer sv_001mmsg
```

**Payload**:
```json
{"transaction_id":"TX_23842","dispensed":2}
```

**Flow**: After motor stops → immediate HTTP confirmation.

---

## 10. Timing Summary (v3.0)

| Task | Interval |
| --- | --- |
| **Heartbeat (WS pong)** | **30 sec** ← changed from 1s |
| WiFi health check | 30 sec |
| HTTP fallback polling | 15 sec (only when WS is down) |
| IN_USE local timeout | 10 min |
| WebSocket reconnect | 5 sec |
| Hardware Watchdog | 10 sec |
| "Done!" flash | 2 sec |
| Error auto-recovery | 60 sec |

---

## 11. Required Libraries

Install via Arduino Library Manager:

| Library | Version | Purpose |
| --- | --- | --- |
| **Adafruit SSD1306** | ≥2.5 | OLED driver |
| **Adafruit GFX** | ≥1.11 | Graphics primitives |
| **QRCode** (ricmoo) | ≥0.0.1 | QR bitmap generation |
| **WebSocketsClient** | ≥2.4 | WebSocket over TLS |
| **ArduinoJson** | ≥6.0 | JSON parse/serialize |

Built-in (no install needed):
- `WiFi.h`, `WiFiClientSecure.h`, `HTTPClient.h`, `WebServer.h`, `Wire.h`, `esp_task_wdt.h`

---

## 12. Error Handling

| Error | Action |
| --- | --- |
| WiFi lost | Auto-reconnect (best WiFi scan) |
| WebSocket lost | Auto-reconnect (5s interval) |
| Server unreachable | HTTP fallback polling |
| Motor stuck (jam) | Emergency stop → report → ERROR state |
| Software hang | Hardware Watchdog reset (10s) |
| OLED init fail | Continue without display (motor still works) |
| QR generation fail | Display "QR Error!" text |
| IN_USE timeout | Return to IDLE + re-display QR (10 min) |
| ERROR state | Auto-recovery after 60s (re-register) |

---

## 13. Security

- Machine authentication: `machine_id` + `api_key` in register message
- API key in `Authorization: Bearer` header for HTTP confirm endpoint
- TLS (port 443) for all HTTPS and WSS connections
- `secureClient.setInsecure()` — TODO: pin CA certificate for production

---

## 14. Power Architecture

```
12V Adapter
   │
   ├── Motor Driver (L298N)
   │
   └── Buck Converter (12V → 5V)
         │
         ├── ESP32
         └── OLED (3.3V via ESP32)
```

**Ground**: Common bus ground  
**Capacitors**: On 12V rail, buck I/O, ESP32 supply, motor terminals

---

## 15. Local Web Control Panel

**Access**: `http://<ESP32_IP>/`

**Endpoints**:
| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | Web control panel HTML |
| GET | `/status` | JSON status (state, motor, session, speed) |
| POST | `/motor/start?speed=200` | Manual motor start |
| POST | `/motor/stop` | Manual motor stop |

**Updated in v3.0**: Shows current state (IDLE/IN_USE/DISPENSING/etc.), session token, and OLED line content instead of LCD lines and display code.
