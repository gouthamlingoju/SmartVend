# SmartVend v3.1 — Hardware Connections (Current)

## ESP32 <-> TFT (ILI9341, 8-bit parallel)

```
ESP32 DevKit V1         TFT 2.4" ILI9341
══════════════          ═════════════════
5V (VIN/5V)   ────────► 5V
GND           ────────► GND
GPIO27        ────────► LCD_CS
GPIO14        ────────► LCD_RS (DC)
GPIO26        ────────► LCD_RST
GPIO12        ────────► LCD_WR
GPIO13        ────────► LCD_RD
GPIO16        ────────► LCD_D0
GPIO4         ────────► LCD_D1
GPIO23        ────────► LCD_D2
GPIO22        ────────► LCD_D3
GPIO21        ────────► LCD_D4
GPIO19        ────────► LCD_D5
GPIO18        ────────► LCD_D6
GPIO17        ────────► LCD_D7
```

---

## ESP32 <-> L298N

```
ESP32 DevKit V1         L298N
══════════════          ═════
GPIO25        ────────► ENA
GPIO32        ────────► IN1
GPIO33        ────────► IN2
GND           ────────► GND
```

---

## Full Pin Usage Map

```
GPIO2   → Built-in LED
GPIO4   → TFT LCD_D1
GPIO12  → TFT LCD_WR
GPIO13  → TFT LCD_RD
GPIO14  → TFT LCD_RS / DC
GPIO16  → TFT LCD_D0
GPIO17  → TFT LCD_D7
GPIO18  → TFT LCD_D6
GPIO19  → TFT LCD_D5
GPIO21  → TFT LCD_D4
GPIO22  → TFT LCD_D3
GPIO23  → TFT LCD_D2
GPIO25  → L298N ENA
GPIO26  → TFT LCD_RST
GPIO27  → TFT LCD_CS
GPIO32  → L298N IN1
GPIO33  → L298N IN2
GPIO34  → ACS712 OUT (jam sensing, analog input only)
```

---

## Power (Brownout Prevention)

1. Power motor side separately: dedicated supply to L298N `12V/VIN` (match motor rating).
2. Power ESP32 from stable USB 5V.
3. Keep **common ground** across ESP32, TFT, L298N, and motor supply ground.

---

## TFT_eSPI User_Setup.h Mapping

```cpp
#define ILI9341_DRIVER
#define TFT_PARALLEL_8_BIT
#define TFT_CS   27
#define TFT_DC   14
#define TFT_RST  26
#define TFT_WR   12
#define TFT_RD   13
#define TFT_D0   16
#define TFT_D1    4
#define TFT_D2   23
#define TFT_D3   22
#define TFT_D4   21
#define TFT_D5   19
#define TFT_D6   18
#define TFT_D7   17
#define TFT_WIDTH  240
#define TFT_HEIGHT 320
```

---

## Important Constraint

- Do **not** use `GPIO26` or `GPIO27` for motor control. They are reserved for TFT `RST` and `CS`.
