# SmartVend UML Diagrams (v3.0 — QR-Based)

## 1. Use Case Diagram

```mermaid
graph TB
    subgraph Actors
        User["👤 User"]
        Admin["🔧 Admin"]
        ESP32["⚙️ ESP32 + TFT"]
        Razorpay["💳 Razorpay"]
    end

    subgraph SmartVend System
        UC1["View Machine List"]
        UC2["Scan QR Code"]
        UC3["Claim Session"]
        UC4["Select Quantity"]
        UC5["Make Payment"]
        UC6["Receive Dispensed Item"]
        UC7["Cancel Session"]
        UC8["Submit Feedback"]
        UC9["Admin Login"]
        UC10["View Dashboard"]
        UC11["Update Stock"]
        UC12["View Feedback"]
        UC13["Register Machine via WS"]
        UC14["Render QR on TFT"]
        UC15["Receive Dispense Command"]
        UC16["Confirm Dispensing"]
        UC17["Report Error / Jam"]
        UC18["Process Payment"]
        UC19["Verify Signature"]
        UC20["Send Webhook Events"]
    end

    User --> UC1
    User --> UC2
    User --> UC3
    User --> UC4
    User --> UC5
    User --> UC6
    User --> UC7
    User --> UC8

    Admin --> UC9
    Admin --> UC10
    Admin --> UC11
    Admin --> UC12

    ESP32 --> UC13
    ESP32 --> UC14
    ESP32 --> UC15
    ESP32 --> UC16
    ESP32 --> UC17

    Razorpay --> UC18
    Razorpay --> UC19
    Razorpay --> UC20

    UC2 -.->|"triggers"| UC3
    UC5 -.->|"includes"| UC18
    UC5 -.->|"includes"| UC19
    UC6 -.->|"includes"| UC15
    UC6 -.->|"includes"| UC16
```

---

## 2. Class Diagram

```mermaid
classDiagram
    class Machine {
        +String machine_id
        +String name
        +String location
        +String api_key
        +int current_stock
        +String status
        +DateTime last_seen_at
        +DateTime last_refill_at
    }

    class Session {
        +UUID id
        +String session_token
        +String machine_id
        +String status
        +String claimed_by
        +DateTime claimed_at
        +DateTime expires_at
        +DateTime created_at
        +DateTime completed_at
    }

    class Order {
        +String order_id
        +UUID session_id
        +String machine_id
        +String client_id
        +int quantity
        +int amount
        +boolean reserved_stock
        +DateTime created_at
    }

    class Transaction {
        +UUID id
        +String machine_id
        +String client_id
        +int amount
        +int quantity
        +String payment_status
        +DateTime created_at
        +DateTime completed_at
        +int dispensed
    }

    class Event {
        +UUID id
        +String machine_id
        +UUID session_id
        +String event_type
        +String client_id
        +JSON payload
        +DateTime created_at
    }

    class FastAPIBackend {
        +websocket_endpoint()
        +claim_session()
        +session_status()
        +cancel_session()
        +trigger_dispense()
        +create_order()
        +verify_payment()
        +razorpay_webhook()
        +confirm_machine()
        +admin_login()
        +update_stock()
        +session_expiry_sweeper()
    }

    class SessionDB {
        +create_session()
        +claim_session()
        +get_session_by_token()
        +cancel_session()
        +update_session_status()
        +expire_stale_sessions()
        +expire_and_renew_sessions()
        +reserve_stock_atomic()
        +release_stock()
        +create_order_record()
        +complete_session()
        +trigger_dispense_session()
        +log_event()
    }

    class ESP32Device {
        +MachineState currentState
        +String sessionToken
        +String sessionUrl
        +drawHeader()
        +displayQRCode()
        +displayInUse()
        +displayDispensing()
        +displayCompleted()
        +displayError()
        +displayOffline()
        +motorRunForward()
        +motorStop()
        +checkJam()
    }

    class ReactFrontend {
        +App
        +MachineList
        +VendingMachine
        +VendingSession
        +QuantitySelector
        +SuccessPopup
        +AdminDashboard
        +AdminLogin
        +FeedbackForm
    }

    class RazorpayClient {
        +order.create()
        +utility.verify_payment_signature()
    }

    Machine "1" -- "0..*" Session : has
    Machine "1" -- "0..*" Transaction : generates
    Machine "1" -- "0..*" Event : logs
    Session "1" -- "0..*" Order : maps to
    Session "1" -- "0..*" Event : logged
    FastAPIBackend --> SessionDB : uses
    FastAPIBackend --> Machine : manages
    FastAPIBackend --> RazorpayClient : uses
    ESP32Device --> FastAPIBackend : connects via WebSocket
    ReactFrontend --> FastAPIBackend : API calls
    ReactFrontend --> RazorpayClient : payment UI
```

---

## 3. Sequence Diagrams

### 3.1 QR Scan → Claim → Pay → Dispense (v3.0)

```mermaid
sequenceDiagram
    actor User
    participant Phone as Phone Browser
    participant FE as React Frontend
    participant API as FastAPI Backend
    participant DB as Supabase DB
    participant WS as WebSocket
    participant ESP as ESP32 + TFT
    participant RP as Razorpay

    Note over ESP,API: Boot & Registration
    ESP->>API: WS: register(M001, api_key)
    API->>DB: upsert machine + create session
    API-->>ESP: WS: { type: "session", token, url }
    ESP->>ESP: Generate QR bitmap → render on TFT

    Note over User,ESP: QR Scan Flow
    User->>ESP: Scans QR with phone camera
    Phone->>FE: Opens /vend/M001/xK9mBq2P
    FE->>API: GET /api/session/status { token, client_id }
    API-->>FE: { status: "active" }
    FE->>FE: Show name entry (first time) or auto-claim
    FE->>API: POST /api/session/claim { token, client_id, name }
    API->>DB: UPDATE sessions SET status='in_progress' WHERE token=? AND status='active'
    API->>DB: UPDATE machines SET status='in_use'
    API-->>FE: { status: "in_progress", expires_at }
    API->>ESP: WS: { type: "claimed", claimed_by_name: "Goutham" }
    ESP->>ESP: TFT: "SmartVend" + "IN USE" + "Goutham"

    Note over User,RP: Payment Flow
    User->>FE: Select qty=2, click Pay ₹20
    FE->>API: POST /create-order { qty, machine_id, session_token }
    API->>DB: Check stock availability (no decrement yet)
    API->>RP: order.create({ amount: 2000 })
    RP-->>API: { order_id }
    API->>DB: INSERT INTO orders (order_id, session_id, ...)
    API-->>FE: order data
    FE->>RP: Open checkout
    User->>RP: Completes payment
    RP-->>FE: { payment_id, order_id, signature }

    Note over FE,ESP: Dispense
    FE->>API: POST /api/session/trigger-dispense { token, client_id, qty, order_id, payment_id, signature }
    API->>RP: verify_signature()
    API->>DB: Validate order↔session↔client
    API->>DB: Reserve stock (atomic decrement)
    API->>DB: Check idempotency, create transaction
    API->>DB: UPDATE sessions SET status='dispensing'
    API->>ESP: WS: { type: "command", action: "dispense", duration: 2, tx_id=order_id }
    ESP->>ESP: TFT: "SmartVend" + "Dispensing..." + progress bar
    ESP->>ESP: Motor runs → stops
    ESP->>API: POST /confirm { order_id, dispensed: 2 }
    API->>DB: Complete transaction + session
    API->>DB: Create new session (new token)
    API->>ESP: WS: { type: "new_session", token: "pR7nWm4K", url: "..." }
    ESP->>ESP: Generate new QR → render on TFT
    API-->>FE: Success
    FE->>User: Show success popup → feedback form 🎉
```

### 3.2 Session Expiry & QR Rotation

```mermaid
sequenceDiagram
    participant Sweeper as Session Expiry Sweeper
    participant API as FastAPI Backend
    participant DB as Supabase DB
    participant ESP as ESP32 + TFT

    Note over Sweeper: Runs every 10 seconds
    loop Every 10 seconds
        Sweeper->>DB: SELECT expired sessions WHERE status IN ('active','in_progress') AND expires_at < NOW()
        alt Active session expired (nobody scanned)
            Sweeper->>DB: UPDATE session SET status='expired'
            Sweeper->>DB: CREATE new session for machine
            Sweeper->>ESP: WS: { type: "new_session", token, url }
            ESP->>ESP: Generate new QR → render on TFT
        else In_progress session expired (user abandoned)
            Sweeper->>DB: UPDATE session SET status='expired'
            Sweeper->>DB: Release reserved stock (if any)
            Sweeper->>DB: SET machine status='idle'
            Sweeper->>DB: CREATE new session for machine
            Sweeper->>ESP: WS: { type: "new_session", token, url }
            ESP->>ESP: Generate new QR → render on TFT
        end
    end
```

### 3.3 Webhook Reconciliation (Tab Closed After Payment)

```mermaid
sequenceDiagram
    actor User
    participant FE as React Frontend
    participant API as FastAPI Backend
    participant DB as Supabase DB
    participant ESP as ESP32
    participant RP as Razorpay

    User->>FE: Pays via Razorpay
    FE->>FE: ⚠️ User closes tab BEFORE /trigger-dispense

    RP->>API: POST /api/razorpay-webhook (payment.captured)
    API->>API: Verify webhook HMAC signature
    API->>DB: Look up order_id → session_id, machine_id, quantity
    API->>DB: Check: transaction exists for this order?
    alt No existing transaction
        API->>DB: Create transaction { status: 'webhook_captured' }
        API->>DB: UPDATE sessions SET status='dispensing'
        API->>ESP: WS: { type: "command", action: "dispense", duration, tx_id=order_id }
        API->>DB: Log event: 'webhook_auto_dispense'
        ESP->>ESP: Motor runs → confirms
    else Transaction already exists
        API->>API: Skip (already handled)
    end
```

### 3.4 Admin Operations

```mermaid
sequenceDiagram
    actor Admin
    participant UI as Admin Dashboard
    participant API as FastAPI Backend
    participant DB as Supabase DB
    participant ESP as ESP32

    Admin->>UI: Navigate to /admin
    UI->>UI: Check stored token
    alt Token exists
        UI->>API: GET /api/admin/verify
        API-->>UI: Token valid
        UI->>UI: Show dashboard
    else No token
        UI->>UI: Show login form
        Admin->>UI: Enter password
        UI->>API: POST /api/admin/login
        API->>API: Verify password hash
        API-->>UI: { token }
        UI->>UI: Store token, show dashboard
    end

    Admin->>UI: Click "Update Stock"
    Admin->>UI: Enter new stock level
    UI->>API: POST /api/machine/{id}/update-stock { stock }
    API->>DB: Update current_stock, last_refill_at
    API->>ESP: WS: { type: "stock_update", stock }
    API-->>UI: Success
```

---

## 4. Activity Diagrams

### 4.1 User Complete Flow (v3.0)

```mermaid
flowchart TD
    A([Start]) --> B["Scan QR on machine TFT"]
    B --> C["Phone opens /vend/M001/xK9mBq2P"]
    C --> D{"Session status?"}

    D -->|"active"| E{"Has saved name?"}
    E -->|Yes| F["Auto-claim with saved name"]
    E -->|No| G["Enter name → click Continue"]
    G --> F
    D -->|"in_progress + owner"| H["Resume session"]
    D -->|"in_progress + other"| I["Show 'Session in use' error"]
    D -->|"expired / 404"| J["Show 'QR Expired' screen"]
    D -->|"completed"| K["Show 'Completed' screen"]

    F --> L["Session claimed ✓"]
    H --> L
    L --> M["Select Quantity"]
    M --> N["Click Pay ₹X"]
    N --> O["POST /create-order"]
    O --> P{"Stock available?"}
    P -->|No| Q["Error: Out of stock"]
    Q --> M
    P -->|Yes| R["Open Razorpay Checkout"]

    R --> S{"Payment completed?"}
    S -->|Cancelled| M
    S -->|Success| W["POST /api/session/trigger-dispense\n(with order_id + payment proof)"]

    W --> X["ESP32 runs motor"]
    X --> Y["Dispensing animation on frontend"]
    Y --> Z["ESP32 confirms → backend completes session"]
    Z --> AA["Success popup"]
    AA --> AB["Feedback form"]
    AB --> AC(["Done → redirect home"])

    L --> AD{"Claim TTL expired?"}
    AD -->|"5 min elapsed"| AE["Session auto-expired"]
    AE --> AF["New QR on machine"]
```

### 4.2 ESP32 State Machine (v3.0)

```mermaid
stateDiagram-v2
    [*] --> BOOTING
    BOOTING --> IDLE : WiFi + WS connected + registered

    state IDLE {
        ShowQR : TFT shows SmartVend + QR code
        WaitScan : Awaiting user scan
        [*] --> ShowQR
        ShowQR --> WaitScan
    }

    state IN_USE {
        ShowInUse : TFT shows SmartVend + In Use + name
        WaitPayment : Awaiting dispense command
        [*] --> ShowInUse
        ShowInUse --> WaitPayment
    }

    state DISPENSING {
        MotorRunning : Motor forward + progress bar
        MotorDone : Duration elapsed
        JamDetected : Current spike on GPIO 34
        SendConfirm : POST /confirm to server
        [*] --> MotorRunning
        MotorRunning --> MotorDone
        MotorRunning --> JamDetected
        MotorDone --> SendConfirm
    }

    state COMPLETED {
        ShowDone : TFT shows SmartVend + Done! + checkmark
        [*] --> ShowDone
    }

    state ERROR {
        ShowError : TFT shows SmartVend + Error message
        [*] --> ShowError
    }

    state OFFLINE {
        ShowOffline : TFT shows SmartVend + Offline
        Reconnecting : Auto-retry every 30s
        [*] --> ShowOffline
        ShowOffline --> Reconnecting
    }

    IDLE --> IN_USE : WS "claimed" message
    IDLE --> IDLE : WS "new_session" (QR rotation)
    IN_USE --> DISPENSING : WS "command" dispense
    IN_USE --> IDLE : Local timeout 10 min
    IN_USE --> IDLE : WS "new_session" (session expired)
    DISPENSING --> COMPLETED : Motor done + confirmed
    DISPENSING --> ERROR : Jam detected
    COMPLETED --> IDLE : After 2s flash + new QR
    ERROR --> IDLE : Auto-recovery after 60s

    IDLE --> OFFLINE : WiFi/WS disconnected
    IN_USE --> OFFLINE : WiFi/WS disconnected
    OFFLINE --> BOOTING : WiFi restored
```

### 4.3 Payment + Dispense Flow (v3.0)

```mermaid
flowchart TD
    A(["Payment Initiated"]) --> B["POST /create-order"]
    B --> C{"Session valid + owned?"}
    C -->|No| D["Error: Invalid session"]
    C -->|Yes| E{"Quantity > 0?"}
    E -->|No| F["Error: Invalid quantity"]
    E -->|Yes| G["Check stock availability"]

    G --> H{"Stock >= Quantity?"}
    H -->|No| I["Error 409: Insufficient stock"]
    H -->|Yes| J["Create Razorpay Order"]
    J --> K["Store order_id → session mapping"]
    K --> L["Return order to frontend"]

    L --> M["Frontend opens Razorpay Checkout"]
    M --> N{"User completes payment?"}
    N -->|Cancelled| O["Session stays claimed, can retry"]
    N -->|Success| Q["POST /api/session/trigger-dispense\n(with order_id + payment proof)"]
    Q --> R{"Transaction already processed?"}
    R -->|Yes| S["Return: duplicate"]
    R -->|No| T["Validate session + payment proof + order mapping"]

    T --> U{"Session valid?"}
    U -->|Invalid| V["Error: Session invalid"]
    U -->|Valid| W["Create transaction record"]

    W --> X["UPDATE session → dispensing"]
    X --> Y["Send WS dispense command"]
    Y --> Z(["Dispense in progress"])
```

### 4.4 Session Expiry Sweeper (v3.0)

```mermaid
flowchart TD
    A(["Sweeper Running"]) --> B["Sleep 10 seconds"]
    B --> C["Query DB: expired active sessions"]
    C --> D{"Any expired?"}
    D -->|No| B
    D -->|Yes| E["For each expired session:"]

    E --> F{"Was it in_progress?"}
    F -->|Yes| G["Release reserved stock if order exists"]
    G --> H["Set machine status → idle"]
    F -->|No| H

    H --> I["SET session status → expired"]
    I --> J["Create new session for machine"]
    J --> K{"Machine connected via WS?"}
    K -->|Yes| L["Send WS: new_session { token, url }"]
    K -->|No| M["Pending for next connect"]
    L --> B
    M --> B
```

---

## 5. Deployment Architecture

```mermaid
graph TB
    subgraph "User Devices"
        Phone["📱 Phone (QR Scan)"]
        Browser["🌐 Browser"]
    end

    subgraph "Cloud (Render)"
        Backend["FastAPI Backend<br/>uvicorn + WebSocket"]
    end

    subgraph "Supabase"
        DB["PostgreSQL<br/>machines, sessions, orders,<br/>transactions, events"]
    end

    subgraph "Redis"
        Redis["Redis Pub/Sub<br/>Cross-worker WS fanout"]
    end

    subgraph "Razorpay"
        RP["Payment Gateway<br/>Orders + Webhooks"]
    end

    subgraph "Hardware"
        ESP["ESP32 + TFT<br/>QR Code + Motor"]
    end

    Phone --> Browser
    Browser -->|HTTPS| Backend
    ESP -->|WSS| Backend
    ESP -->|HTTPS| Backend
    Backend -->|REST| DB
    Backend -->|PubSub| Redis
    Backend -->|REST| RP
    RP -->|Webhook| Backend
```
