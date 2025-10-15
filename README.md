# SmartVend

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Repo: SmartVend](https://img.shields.io/badge/repo-SmartVend-brightgreen.svg)](https://github.com/gouthamlingoju/SmartVend)

SmartVend is a smart vending machine platform that integrates embedded firmware, edge logic, and web/mobile interfaces to provide remote monitoring, inventory management, and automated vending. This repository contains the code for the hardware firmware (C++), backend/edge services (Python and/or Node.js), and web UI (JavaScript).

Table of Contents
- Overview
- Key Features
- Architecture
- Tech Stack
- Hardware Components
- Quick Start
  - Prerequisites
  - Local development
  - Building and flashing firmware
  - Running services
- Configuration
- Usage
  - Operator / Admin
  - Customer
- Testing
- Contributing
- License
- Contact

Overview
--------
SmartVend aims to modernize vending operations by providing:
- Remote inventory and telemetry monitoring
- Secure cashless payments and transaction logging
- Product selection and dispensing control
- Alerts for low stock, faults, or tampering
- Simple web dashboard for operators

Key Features
------------
- Inventory tracking per compartment
- Telemetry: temperature, door status, uptime, error logs
- Transaction history with receipts
- Remote firmware update support (OTA) — if supported by hardware
- Role-based admin dashboard
- Modular architecture for supporting multiple hardware controllers

Architecture
------------
- Firmware (C++): Runs on microcontroller (e.g., ESP32, Arduino-compatible) to control motors, sensors, and actuators; communicates over MQTT/HTTP/Serial.
- Edge / Backend (Python / Node.js): Receives telemetry, manages inventory, communicates with payment processors, provides REST/Socket API for frontend and devices.
- Frontend (JavaScript): Single Page App (React/Vue) or lightweight admin UI for operators; public-facing purchase UI for customers (if applicable).
- Data Storage: Lightweight DB (SQLite / PostgreSQL / Firebase) for transactions and inventory.
- Messaging: MQTT, WebSocket, or HTTP for device and server communication.

Tech Stack
----------
- JavaScript (frontend, some backend) — ~83.6% of repo
- Python (backend or scripts) — ~9.8% of repo
- C++ (firmware) — ~5.4% of repo
- Other: configs, docs, scripts

Hardware Components (example)
-----------------------------
- Microcontroller: ESP32 / Arduino Nano 33 / STM32
- Motor drivers: stepper/servo drivers for dispensers
- Sensors: reed switch (door), load cells or IR sensors (stock sensing), temperature sensor (DS18B20)
- Power supply, enclosure, keypad / touchscreen (optional)
- Network: Wi-Fi or Ethernet module

Quick Start
-----------

Prerequisites
- Node.js >= 16 (if web/backend uses Node)
- Python 3.8+ (if backend/services use Python)
- PlatformIO or Arduino CLI (for firmware/C++)
- Git
- A DB (SQLite recommended for quick start)

Local development (Web / API)
1. Clone the repo
   ```bash
   git clone https://github.com/gouthamlingoju/SmartVend.git
   cd SmartVend
   ```
2. Install web dependencies (example)
   ```bash
   cd web
   npm install
   npm run dev
   ```
3. Start backend (Node.js example)
   ```bash
   cd server
   npm install
   npm run start:dev
   ```
   Or Python backend:
   ```bash
   cd server
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   python app.py
   ```

Building and flashing firmware (C++)
1. Open the firmware folder (e.g., `firmware/`).
2. Using PlatformIO:
   ```bash
   cd firmware
   pio run -e <env> --target upload
   ```
3. Or using Arduino IDE / Arduino CLI:
   - Open `firmware/SmartVendController.ino` and flash to target board.

Running services
- Ensure environment variables configured (see Configuration).
- Start broker (if using MQTT), DB, backend, and frontend in this order:
  1. MQTT broker (mosquitto) or other messaging service
  2. Database
  3. Backend / Edge server
  4. Frontend dashboard

Configuration
-------------
Copy and fill environment configuration values:
- .env (example)
  ```
  PORT=3000
  DATABASE_URL=sqlite:///data/smartvend.db
  MQTT_BROKER=mqtt://localhost:1883
  MQTT_TOPIC_PREFIX=smartvend
  PAYMENT_PROVIDER_API_KEY=your_key_here
  ```
- Firmware config:
  - WIFI_SSID, WIFI_PASSWORD
  - SERVER_HOST, SERVER_PORT or MQTT settings
  - Device ID or location tag

Usage
-----
Operator / Admin:
- Log into the admin dashboard
- Add vending locations and device IDs
- View inventory and telemetry
- Configure alerts and thresholds
- Trigger remote restock or maintenance modes

Customer:
- Use the provided purchase UI (touchscreen or web)
- Select product, pay via supported payment methods, receive confirmation and dispense

Testing
-------
- Unit tests (if present) for backend:
  ```bash
  cd server
  npm test
  ```
- Firmware hardware-in-the-loop testing for motor and sensor behavior
- Integration tests for MQTT messaging and DB persistence

Contributing
------------
Contributions are welcome. Please:
1. Fork the repo
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Commit your changes and open a Pull Request
4. Add tests for significant features and update docs

When contributing firmware changes, document hardware revisions and pinouts in `docs/hardware.md`.

License
-------
This project is provided under the MIT License. See LICENSE for details.

Contact
-------
Maintainer: gouthamlingoju
Repository: https://github.com/gouthamlingoju/SmartVend

Acknowledgements
----------------
Thanks to contributors and open-source projects used in this stack. If you want, I can:
- customize the README to reflect exact folders/files in your repo (firmware path, server language)
- add badges (build, coverage) and a TODO roadmap
- create a docs/ directory with hardware diagrams and a quick wiring guide
