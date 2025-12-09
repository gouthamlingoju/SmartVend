SmartVend
=========

Connected vending machine platform with:
- FastAPI backend (WebSocket + REST, Supabase/Postgres data store)
- React (Vite) frontend for users and admins
- ESP32 firmware for the dispenser (WebSocket control + HTTP confirmations)


## Architecture

- Backend: `backend/` FastAPI app exposing REST and a `/ws` WebSocket for ESP32s. Stores state in Supabase/Postgres. Optional Redis for cross‑worker WS fanout.
- Frontend: `frontend/` React (Vite) app with Supabase client for listing machines and an admin dashboard.
- Device: `ESP32/sketch_aug2a/sketch_aug2a.ino` connects to backend via WebSocket and receives commands.

Repo layout
- backend: API, DB access, WebSocket server
- frontend: React UI (user flow + admin)
- ESP32: Arduino sketch for hardware
- migrations: example SQL for DB schema (see notes below)


## Backend (FastAPI)

Main entry: `backend/main.py`

Features
- JWT admin login (`/api/admin/login`, 1‑hour tokens)
- Machine lifecycle: register, status, lock/unlock, trigger dispense
- Display code rotation with TTL
- WebSocket device connections at `/ws`
- Optional Redis pub/sub for multi‑process WS delivery
- Razorpay order creation and verification hooks
- Low‑stock email alert endpoint

Key environment variables (read in `backend/config.py`)
- SUPABASE_URL, SUPABASE_KEY
- RAZORPAY_KEY_ID, RAZORPAY_SECRET_KEY
- ADMIN_PASSWORD
- SMTP_SERVER, SMTP_PORT, SENDER_EMAIL, SENDER_PASSWORD, RECEIVER_EMAIL
- DISPLAY_CODE_TTL_MINUTES (used for display code TTL and lock TTL)
- FRONTEND_URL (CORS allow‑origin)
- REDIS_URL (optional, e.g. redis://localhost:6379)

Example .env
```
SUPABASE_URL=... 
SUPABASE_KEY=...
FRONTEND_URL=http://localhost:5173
ADMIN_PASSWORD=change-me
DISPLAY_CODE_TTL_MINUTES=10
RAZORPAY_KEY_ID=...
RAZORPAY_SECRET_KEY=...
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SENDER_EMAIL=you@example.com
SENDER_PASSWORD=app-password
RECEIVER_EMAIL=ops@example.com
# Optional
# REDIS_URL=redis://localhost:6379
```

Run (Windows PowerShell)
```
# from backend/
python -m venv venv
./venv/Scripts/Activate.ps1
pip install fastapi uvicorn[standard] python-dotenv supabase razorpay redis email-validator
python main.py
```
The server listens on http://0.0.0.0:8002 and exposes WebSocket at ws://localhost:8002/ws.

REST endpoints (summary)
- POST /api/admin/login
- GET  /api/admin/verify
- POST /api/machine/register
- GET  /api/machine/{machine_id}/status    (ESP32, requires Authorization: Bearer <api_key>)
- GET  /api/machine/{machine_id}/public-status?client_id=...  (frontend)
- POST /api/machine/{machine_id}/unlock    (frontend, client_id body)
- POST /api/machine/{machine_id}/confirm   (ESP32)
- POST /api/machine/{machine_id}/report-error
- POST /api/machine/{machine_id}/trigger-dispense  (frontend → server validated)
- POST /api/machine/{machine_id}/update-stock      (admin, JWT)
- POST /api/lock-by-code            (frontend)
- POST /create-order                (Razorpay)
- POST /verify-payment              (Razorpay)
- POST /low-stock-alert             (email)

WebSocket `/ws` (ESP32)
- Client → Server messages
	- `{ "type":"register", "machine_id":"M001", "api_key":"..." }`
	- `{ "type":"status", "value":"active|locked|unlocked" }`
	- `{ "type":"fetch_display" }`
- Server → Client messages
	- `{ "type":"display_code", "value":"123456" }`
	- `{ "type":"command", "action":"dispense", "duration": <quantity> }`
	- `{ "type":"stock_update", "stock": <int> }`

Note: Current backend does not emit explicit `lock`/`unlock` messages when a user locks via code. See “Known gaps” below.


## Database (Supabase/Postgres)

The backend code expects the following columns:
- machines: machine_id (text, unique), api_key, current_stock, status, display_code, display_code_expires_at, last_seen_at
- locks: machine_id (text, PK), locked_by, access_code_hash, locked_at, expires_at, status
- transactions: id (uuid, PK), machine_id, client_id, access_code, amount, quantity, payment_status, created_at, completed_at, dispensed

The example SQL in `migrations/001_create_tables.sql` uses `id` as the primary key for machines, while the code queries by `machine_id`. Align your schema one of these ways:
1) Add a `machine_id` column and mark it unique, and update foreign keys to reference it; or
2) Change the code to consistently use `id` (not recommended unless you refactor all queries).

Locks and codes
- Lock TTL and display code TTL reuse `DISPLAY_CODE_TTL_MINUTES`.
- On successful dispense confirmation, the lock is cleared, stock decremented, and a new display code is rotated.


## Frontend (React + Vite)

Location: `frontend/`

Environment variables
- VITE_BACKEND_URL (e.g. http://localhost:8002)
- VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY

Run (PowerShell)
```
# from frontend/
npm install
npm run dev
```
Open http://localhost:5173.

User flow
- Enter the code shown on the device to “lock” a machine (`POST /api/lock-by-code`)
- Pay via Razorpay -> server verifies -> triggers dispense (`POST /api/machine/{id}/trigger-dispense`)
- UI shows progress and optional feedback form

Admin
- Login `/api/admin/login` (JWT)
- Update stock per machine `/api/machine/{id}/update-stock`


## ESP32 Firmware

File: `ESP32/sketch_aug2a/sketch_aug2a.ino`

What to configure
- `ssid`, `password`
- `serverHost`, `serverPort`, `serverPath` (should match backend: ws://<host>:8002/ws)
- `serverHttps` (HTTP base for REST calls, e.g. http://<host>:8002)
- `machine_id`, `machine_api_key`

Build and upload
1) Install libraries: WiFi, WebSocketsClient, ArduinoJson, LiquidCrystal_I2C
2) Select your ESP32 board; compile and upload the sketch

Behavior
- Connects to Wi‑Fi -> WebSocket -> registers with server
- Periodically sends status while unlocked and fetches display code every 5 minutes
- Receives `{type:"command", action:"dispense"}` and runs the motor, then confirms over HTTP `/confirm`

Important: The current sketch listens for `lock`/`unlock` messages to change state locally, but the backend does not emit these today. Device state (LOCKED/UNLOCKED) is not authoritative for frontend locking; the database `locks` table is.


## Troubleshooting

“Lock falls back to unlocked quickly” (frontend)
- Ensure DISPLAY_CODE_TTL_MINUTES isn’t set too low (e.g., 0 or 1). The lock TTL uses the same value.
- Make sure the same `client_id` is used across requests. The UI stores it in `localStorage` as `sv_client_id`.
- There’s no continuous polling of public status in `VendingMachine.jsx`. If you added one, leave a 3–5s “grace” after locking (there is a `lockGraceRef` hook for this) to avoid reading a stale unlocked state from eventual consistency.
- Schema alignment: If your DB uses `id` for machines while the code expects `machine_id`, status/lock reads can fail silently and appear unlocked. Align schema (see Database section).

WebSocket connectivity
- Device must use `webSocket.begin(serverHost, 8002, "/ws")` (plain WS) if backend runs locally without TLS. Don’t use `beginSSL` unless you terminate TLS (wss://).
- Backend emits `display_code` and `command` messages; it does NOT notify `lock`/`unlock` yet.

CORS and FRONTEND_URL
- Set `FRONTEND_URL=http://localhost:5173` (or your deployed URL) so the backend allows the browser to call it.

Razorpay warnings
- `pkg_resources` is deprecated in recent Setuptools; it’s only a warning. Doesn’t affect WS or locks.


## Known gaps (short‑term roadmap)

- Emit WS notifications on lock/unlock so devices can reflect user lock state:
	- on `/api/lock-by-code` success → publish `{type:"lock"}` to the machine’s WS
	- on `/api/machine/{id}/unlock` → publish `{type:"unlock"}`
- Optional: add a lightweight polling in frontend (every 2–5s) for `/public-status`, honoring `lockGraceRef`.
- Provide a canonical `requirements.txt` and `.env.example` files.
- Migrate FastAPI startup/shutdown to Lifespan events (deprecation notice).


## Quick test checklist

Backend
- Start FastAPI (see run section). Verify “DB pool initialized” on startup.
- Smoke test endpoints with PowerShell:
```
Invoke-RestMethod -Method Get http://localhost:8002/api/machine/M001/public-status
```

Frontend
- `npm run dev` then open http://localhost:5173
- Select a machine -> enter code shown on device -> Lock -> proceed to payment (test mode)

ESP32
- Watch Serial Monitor; you should see: Wi‑Fi connected → WS connected → register/status → `display_code` received.


## License

Proprietary – internal project (update if you intend to open‑source).

