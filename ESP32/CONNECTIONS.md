# SmartVend v3.0 — Hardware Connections Guide

## Wiring Diagram

![SmartVend v3.0 Wiring Diagram](/Users/gouthamlingoju/Projects/SmartVend/ESP32/wiring_diagram.png)

---

## Components Required

| # | Component | Specification | Qty |
|---|-----------|--------------|-----|
| 1 | ESP32 DevKit V1 | 30-pin or 38-pin | 1 |
| 2 | OLED Display | 0.96" SSD1306 128×64 I2C | 1 |
| 3 | L298N Motor Driver | Dual H-Bridge | 1 |
| 4 | DC Motor | 12V Gear Motor | 1 |
| 5 | ACS712 Current Sensor | 5A or 20A module | 1 |
| 6 | 12V Power Supply | 2A+ (for motor) | 1 |
| 7 | USB Cable | USB-C to Micro-USB (data) | 1 |
| 8 | Jumper Wires | Male-to-Female, Male-to-Male | ~15 |
| 9 | Breadboard (optional) | Half-size or full | 1 |

---

## Pin-by-Pin Wiring

### 1. OLED Display (SSD1306 — I2C)

| OLED Pin | → | ESP32 Pin | Wire Color | Notes |
|----------|---|-----------|------------|-------|
| **VCC** | → | **3.3V** | 🔴 Red | Do NOT use 5V — SSD1306 runs at 3.3V |
| **GND** | → | **GND** | ⚫ Black | Any GND pin |
| **SDA** | → | **GPIO 21** | 🔵 Blue | Default I2C data |
| **SCL** | → | **GPIO 22** | 🟢 Green | Default I2C clock |

> **I2C Address:** `0x3C` (most common). If display doesn't work, try `0x3D` — change `OLED_I2C_ADDR` in sketch.

---

### 2. L298N Motor Driver

| L298N Pin | → | ESP32 Pin | Wire Color | Notes |
|-----------|---|-----------|------------|-------|
| **ENA** | → | **GPIO 25** | 🟣 Purple | PWM speed control (0–255) |
| **IN1** | → | **GPIO 26** | 🟠 Orange | Direction control |
| **IN2** | → | **GPIO 27** | 🟡 Yellow | Direction control |
| **GND** | → | **ESP32 GND** | ⚫ Black | Common ground (CRITICAL!) |

| L298N Pin | → | Power Supply | Notes |
|-----------|---|-------------|-------|
| **12V / VCC** | → | **12V DC (+)** | Motor power input |
| **GND** | → | **12V DC (−)** | Power ground |
| **5V (output)** | → | *Optional* | Can power ESP32 via VIN (remove USB if using) |

| L298N Pin | → | Motor | Notes |
|-----------|---|-------|-------|
| **OUT1** | → | **Motor (+)** | To DC motor terminal 1 |
| **OUT2** | → | **Motor (−)** | To DC motor terminal 2 |

> **Important:** Remove the **ENA jumper cap** on the L298N board — we're controlling speed via PWM from GPIO 25.

---

### 3. Current Sensor (ACS712 — Jam Detection)

| ACS712 Pin | → | Connection | Wire Color | Notes |
|------------|---|-----------|------------|-------|
| **VCC** | → | **ESP32 5V / VIN** | 🔴 Red | Needs 5V to operate |
| **GND** | → | **ESP32 GND** | ⚫ Black | Common ground |
| **OUT** | → | **GPIO 34** | 🟤 Brown | Analog input (ADC) |

> **Wiring the sensor inline:** The ACS712 has two screw terminals — wire it **in series** between L298N OUT1 and the motor. Current flows through the sensor to measure draw.

| ACS712 Screw Terminal | Connection |
|----------------------|------------|
| Terminal 1 | L298N OUT1 |
| Terminal 2 | Motor (+) terminal |

---

### 4. Built-in LED

| LED | ESP32 Pin | Notes |
|-----|-----------|-------|
| Built-in LED | **GPIO 2** | Already on the DevKit board — no wiring needed! |

Lights up during dispensing to indicate motor is active.

---

## Complete ESP32 Pin Summary

```
ESP32 DevKit V1 — Pin Usage Map
═══════════════════════════════

 GPIO  2  →  Built-in LED (on-board, no wiring)
 GPIO 21  →  OLED SDA (I2C Data)
 GPIO 22  →  OLED SCL (I2C Clock)
 GPIO 25  →  L298N ENA (Motor PWM Speed)
 GPIO 26  →  L298N IN1 (Motor Direction)
 GPIO 27  →  L298N IN2 (Motor Direction)
 GPIO 34  →  ACS712 OUT (Current Sensor - Analog)
  3.3V    →  OLED VCC
   GND    →  Common ground (OLED + L298N + ACS712)
```

---

## Power Wiring Diagram

```
┌─────────────┐     USB-C Cable      ┌──────────────┐
│   MacBook   │ ──────────────────── │   ESP32      │
│   (Upload)  │    (5V + Data)       │   DevKit V1  │
└─────────────┘                      └──────┬───────┘
                                            │ GND (shared)
┌─────────────┐     12V DC           ┌──────┴───────┐
│  12V Power  │ ──────────────────── │    L298N     │
│  Adapter    │    (+) → 12V         │  Motor Driver│
│   (2A+)     │    (−) → GND         └──────┬───────┘
└─────────────┘                             │ OUT1/OUT2
                                     ┌──────┴───────┐
                                     │  ACS712      │
                                     │  (in series) │
                                     └──────┬───────┘
                                            │
                                     ┌──────┴───────┐
                                     │   DC Motor   │
                                     │   (12V)      │
                                     └──────────────┘
```

---

## ⚠️ Important Notes

1. **Common Ground** — ESP32, L298N, and ACS712 MUST share the same GND. Without this, signals won't work.

2. **Remove ENA Jumper** — The L298N comes with a jumper on ENA that runs the motor at full speed. Remove it since we control speed via PWM.

3. **Motor Direction** — If motor spins the wrong way, swap `IN1`/`IN2` wires (or swap in code: `digitalWrite(IN1, LOW); digitalWrite(IN2, HIGH);`).

4. **12V ≠ ESP32** — Never connect 12V directly to ESP32 pins! The L298N isolates this for you.

5. **GPIO 34 is input-only** — This is correct for the analog current sensor (ADC1 channel).

6. **USB Cable** — Use a **data-capable** USB cable. Charge-only cables won't communicate with Arduino IDE.

7. **Calibrate Jam Threshold** — The `JAM_CURRENT_THRESHOLD = 800` value in the sketch needs calibration per your specific motor. Monitor `analogRead(34)` via Serial Monitor under normal load, then set the threshold ~20% above that value.
