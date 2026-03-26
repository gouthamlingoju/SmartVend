# SmartVend

Connected vending machine platform with QR code-based session management.

- **Backend**: FastAPI (WebSocket + REST, Supabase/Postgres, Redis)
- **Frontend**: React (Vite + Tailwind) for users and admins
- **Device**: ESP32 with 2.4" ILI9341 TFT display (8-bit parallel) for QR code generation and motor control

---

## Architecture

```text
┌─────────────┐         ┌────────────────┐         ┌──────────────────┐
│  ESP32 +    │◄──WS──►│  FastAPI        │◄──API──►│  React Frontend  │
│  TFT        │         │  Backend       │         │  (Vite)          │
│  (QR Code)  │──HTTP──►│                │         │                  │
└─────────────┘         │  Supabase DB   │         │  Razorpay SDK    │
                        │  Redis Pub/Sub │         └──────────────────┘
                        │  Razorpay API  │
                        └────────────────┘
```

### How It Works (v3.0 — QR Flow)

1. **ESP32 boots** → connects WiFi → WebSocket → registers with backend
2. **Backend creates session** → sends session URL to ESP32
3. **ESP32 generates QR code** on TFT display (240×320 px)
4. **User scans QR** with phone camera → browser opens session URL
5. **Frontend auto-claims session** → user selects quantity → pays via Razorpay
6. **Backend triggers dispense** → ESP32 runs motor → confirms → new QR appears

### Repo Layout

| Directory | Contents |
|---|---|
| `backend/` | FastAPI app: REST + WebSocket, session management, Razorpay |
| `frontend/` | React UI: user vending flow + admin dashboard |
| `ESP32/` | Arduino sketch for hardware (TFT + motor + QR) |

---

## Backend (FastAPI)

**Entry point**: `backend/main.py`

### Key Features

- **Session management** — create, claim, cancel, dispense, expire sessions
- **Atomic operations** — stock reservation, session claiming (race-safe)
- **WebSocket** — real-time ESP32 communication at `/ws`
- **Redis pub/sub** — cross-worker WebSocket fanout
- **Razorpay** — order creation, signature verification, webhook reconciliation
- **JWT admin auth** — 1-hour tokens, stock management, dashboard
- **Audit logging** — all state changes logged to events table

### Environment Variables (`backend/.env`)

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key
FRONTEND_URL=http://localhost:5173
ADMIN_PASSWORD=change-me
RAZORPAY_KEY_ID=rzp_test_xxx
RAZORPAY_SECRET_KEY=xxx
RAZORPAY_WEBHOOK_SECRET=xxx
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SENDER_EMAIL=you@example.com
SENDER_PASSWORD=app-password
RECEIVER_EMAIL=ops@example.com
REDIS_URL=redis://localhost:6379
# Session Config (optional, has defaults)
SESSION_TTL_SECONDS=60
CLAIM_TTL_SECONDS=300
MOTOR_TIMEOUT_SECONDS=120
```

### Run

```bash
cd backend
python -m venv venv
source venv/bin/activate  # or ./venv/Scripts/Activate.ps1 on Windows
pip install -r requirements.txt
uvicorn main:app --reload
```

Server: `http://localhost:8000` • WebSocket: `ws://localhost:8000/ws`

### REST Endpoints

#### Session Management (v3.0)

| Method | Endpoint | Caller | Purpose |
|---|---|---|---|
| `POST` | `/api/session/claim` | Frontend | Claim session after QR scan |
| `GET` | `/api/session/status` | Frontend | Check session state (resume on reload) |
| `POST` | `/api/session/cancel` | Frontend | Cancel session, release stock |
| `POST` | `/api/session/trigger-dispense` | Frontend | Trigger dispense after payment |

#### Machine & Payment

| Method | Endpoint | Caller | Purpose |
|---|---|---|---|
| `POST` | `/api/machine/register` | ESP32 | Machine registration |
| `POST` | `/api/machine/{id}/confirm` | ESP32 | Dispense confirmation |
| `POST` | `/api/machine/{id}/update-stock` | Admin | Stock update (JWT) |
| `POST` | `/api/machine/{id}/report-error` | ESP32 | Error reporting |
| `GET` | `/api/machines` | Frontend | List all machines |
| `POST` | `/create-order` | Frontend | Razorpay order creation |
| `POST` | `/verify-payment` | Frontend | Razorpay signature verification |
| `POST` | `/api/razorpay-webhook` | Razorpay | Webhook reconciliation |
| `GET` | `/health` | Any | Health check (returns `{ status: "ok", version: "3.0" }`) |

#### Admin

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/admin/login` | Admin login (returns JWT) |
| `GET` | `/api/admin/verify` | Verify admin token |

#### Deprecated (return 410 Gone)

| Endpoint | Replacement |
|---|---|
| `POST /api/lock-by-code` | `POST /api/session/claim` |
| `POST /api/machine/{id}/unlock` | `POST /api/session/cancel` / session expiry |
| `POST /api/machine/{id}/dispense` | `POST /api/session/trigger-dispense` |
| `POST /api/machine/{id}/trigger-dispense` | `POST /api/session/trigger-dispense` |

### WebSocket Protocol (`/ws`)

#### ESP32 → Server

| Message | When |
|---|---|
| `{ "type":"register", "machine_id":"M001", "api_key":"..." }` | On connect |
| `{ "type":"pong" }` | Response to server ping |
| `{ "type":"status", "value":"timeout" }` | Local IN_USE timeout |
| `{ "type":"error", "value":"motor_jam" }` | Hardware error |

#### Server → ESP32

| Message | When |
|---|---|
| `{ "type":"session", "token":"xK9mBq2P", "url":"..." }` | After register / QR rotation |
| `{ "type":"claimed", "claimed_by_name":"Goutham" }` | User scans QR |
| `{ "type":"new_session", "token":"pR7nWm4K", "url":"..." }` | After completion / expiry |
| `{ "type":"command", "action":"dispense", "duration":2, "transaction_id":"..." }` | Payment confirmed |
| `{ "type":"ping" }` | Keep-alive |
| `{ "type":"stock_update", "stock":15 }` | Admin refill |

---

## Database (Supabase / Postgres)

### Tables

| Table | Purpose |
|---|---|
| `machines` | Machine registry (id, stock, status, api_key) |
| `sessions` | Session lifecycle (token, status, claimed_by, expires_at) — replaces `locks` + `display_code` |
| `orders` | Maps Razorpay `order_id` → `session_id` for webhook reconciliation |
| `transactions` | Payment records (amount, quantity, dispensed) |
| `events` | Audit log (event_type, session_id, payload) |
| `feedback` | User feedback (rating, comment) |
| `locks` | ⚠️ Legacy — kept for backward compat, no longer used |

### Key Schema Features

- **Partial unique index** on `sessions(machine_id)` WHERE status IN ('active', 'in_progress', 'dispensing') — enforces 1 active session per machine
- **Sweeper index** on `sessions(expires_at)` WHERE status IN ('active', 'in_progress') — efficient expiry queries
- **Machine status** values: `idle`, `in_use`, `dispensing`, `error`, `offline`, `Unavailable`

---

## Frontend (React + Vite + Tailwind)

**Location**: `frontend/`

### Environment Variables (`frontend/.env`)

```env
VITE_BACKEND_URL=http://localhost:8000
VITE_RAZORPAY_KEY_ID=rzp_test_xxx
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=your-anon-key
VITE_PRICE_PER_UNIT=1
```

### Run

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

### Routes

| Route | Component | Purpose |
|---|---|---|
| `/` | `MachineList` | Browse available machines |
| `/machine/:machineId` | `VendingMachine` | Legacy code-entry flow (still works) |
| `/vend/:machineId/:sessionToken` | `VendingSession` | **v3.0 QR scan entry point** |
| `/admin` | `AdminDashboard` | Stock management, machine monitoring |
| `/admin-login` | `AdminLogin` | Admin authentication |

### v3.0 User Flow (QR Scan)

1. User scans QR → browser opens `/vend/M001/xK9mBq2P`
2. First-time → enter name; returning → auto-claim with saved name
3. Select quantity → Pay via Razorpay → Dispense animation
4. Success popup → Feedback form → Redirect home
5. Page reload → auto-resumes from current phase

---

## ESP32 Firmware

**File**: `ESP32/sketch_aug2a/sketch_aug2a.ino`

### Hardware

| Component | Purpose |
|---|---|
| ESP32 DevKit V1 | Main controller |
| 2.4" ILI9341 TFT (240×320px, 8-bit parallel) | QR code + status display |
| L298N Motor Driver | Motor control |
| Current Sensor (GPIO 34) | Jam detection |

### Required Libraries (Arduino IDE)

| Library | Purpose |
|---|---|
| **TFT_eSPI** | ILI9341 TFT driver |
| **QRCode** (by ricmoo) | QR bitmap generation |
| **WebSocketsClient** | WebSocket over TLS |
| **ArduinoJson** | JSON parsing |

### Configuration

```cpp
const char *serverHost      = "smartvend.onrender.com";
const char *machine_id      = "M001";
const char *machine_api_key = "sv_001mmsg";
```

### Device States

```text
BOOTING → IDLE → IN_USE → DISPENSING → COMPLETED → IDLE
                                          |
                                        ERROR → IDLE (auto-recovery 60s)
```

### TFT Displays

| State | Display |
|---|---|
| IDLE | "SmartVend" header + QR code + "Scan Me" |
| IN_USE | "SmartVend" + "IN USE" + user name |
| DISPENSING | "SmartVend" + "Dispensing..." + progress bar |
| COMPLETED | "SmartVend" + "Done!" + checkmark |
| ERROR | "SmartVend" + "ERROR!" + message |
| OFFLINE | "SmartVend" + "Offline" + "Reconnecting..." |

### Safety Features

- Hardware Watchdog (10s timeout)
- Motor Jam Detection (current sensing, GPIO 34)
- Multi-WiFi auto-scan (best RSSI)
- HTTP fallback command polling
- Local IN_USE timeout (10 min failsafe)

---

## Quick Test Checklist

### Backend
```bash
# Start the server
cd backend && uvicorn main:app --reload

# Health check
curl http://localhost:8000/health
# → {"status":"ok","version":"3.0"}

# List machines
curl http://localhost:8000/api/machines
```

### Frontend
```bash
cd frontend && npm run dev
# Open http://localhost:5173

# Test QR flow (with a valid session token):
# Open http://localhost:5173/vend/M001/{valid_session_token}
```

### ESP32
- Serial Monitor: WiFi connected → WS connected → register → session token → QR rendered
- TFT: Shows "SmartVend" header + QR code

---

## Troubleshooting

**QR Code Expired quickly?**
- `SESSION_TTL_SECONDS` controls QR rotation (default 60s). This is by design — short TTL = more secure.

**Session claim returns 409?**
- Someone already scanned this QR. Wait for a new QR on the machine.

**CORS errors?**
- Set `FRONTEND_URL` in backend `.env` to match your frontend URL.

**ESP32 shows "Offline"?**
- Backend may be cold-starting (Render free tier). ESP32 auto-retries.

**Razorpay `pkg_resources` warning?**
- Cosmetic only. Does not affect functionality.

**WebSocket won't connect?**
- Use `beginSSL()` for production (wss://). Use `begin()` for local (ws://).

---

## License

Proprietary — internal project.
