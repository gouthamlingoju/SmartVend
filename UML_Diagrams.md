# SmartVend UML Diagrams

## 1. Use Case Diagram

```mermaid
graph TB
    subgraph Actors
        User["👤 User"]
        Admin["🔧 Admin"]
        ESP32["⚙️ ESP32 Device"]
        Razorpay["💳 Razorpay"]
    end

    subgraph SmartVend System
        UC1["View Machine List"]
        UC2["Lock Machine by Code"]
        UC3["Select Quantity"]
        UC4["Make Payment"]
        UC5["Receive Dispensed Item"]
        UC6["Submit Feedback"]
        UC7["Unlock Machine"]
        UC8["Admin Login"]
        UC9["View Dashboard"]
        UC10["Update Stock"]
        UC11["View Feedback"]
        UC12["Register Machine via WS"]
        UC13["Receive Dispense Command"]
        UC14["Confirm Dispensing"]
        UC15["Report Error"]
        UC16["Display Code on LCD"]
        UC17["Process Payment"]
        UC18["Verify Payment Signature"]
        UC19["Send Webhook Events"]
    end

    User --> UC1
    User --> UC2
    User --> UC3
    User --> UC4
    User --> UC5
    User --> UC6
    User --> UC7

    Admin --> UC8
    Admin --> UC9
    Admin --> UC10
    Admin --> UC11

    ESP32 --> UC12
    ESP32 --> UC13
    ESP32 --> UC14
    ESP32 --> UC15
    ESP32 --> UC16

    Razorpay --> UC17
    Razorpay --> UC18
    Razorpay --> UC19

    UC2 -.->|"includes"| UC16
    UC4 -.->|"includes"| UC17
    UC4 -.->|"includes"| UC18
    UC5 -.->|"includes"| UC13
    UC5 -.->|"includes"| UC14
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
        +String display_code
        +DateTime display_code_expires_at
        +DateTime last_seen_at
        +DateTime last_refill_at
    }

    class Lock {
        +String machine_id
        +String locked_by
        +String access_code_hash
        +DateTime locked_at
        +DateTime expires_at
        +String status
    }

    class Transaction {
        +UUID id
        +String machine_id
        +String client_id
        +String access_code
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
        +String client_id
        +String type
        +JSON payload
        +DateTime created_at
    }

    class FastAPIBackend {
        +websocket_endpoint()
        +lock_by_code()
        +trigger_dispense()
        +confirm_dispense()
        +create_order()
        +verify_payment()
        +list_machines()
        +admin_login()
        +update_stock()
    }

    class ESP32Device {
        +DeviceState state
        +String currentDisplayCode
        +String lockedByName
        +bool motorRunning
        +webSocketEvent()
        +sendRegister()
        +sendConfirmation()
        +fetchDisplayCode()
        +motorRunForward()
        +motorStop()
    }

    class ReactFrontend {
        +App
        +MachineList
        +VendingMachine
        +LockSection
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

    Machine "1" -- "0..1" Lock : has
    Machine "1" -- "0..*" Transaction : generates
    Machine "1" -- "0..*" Event : logs
    FastAPIBackend --> Machine : manages
    FastAPIBackend --> Lock : manages
    FastAPIBackend --> Transaction : creates
    FastAPIBackend --> RazorpayClient : uses
    ESP32Device --> FastAPIBackend : connects via WebSocket
    ReactFrontend --> FastAPIBackend : API calls
    ReactFrontend --> RazorpayClient : payment UI
```

---

## 3. Sequence Diagrams

### 3.1 Lock and Dispense Flow

```mermaid
sequenceDiagram
    actor User
    participant UI as React Frontend
    participant API as FastAPI Backend
    participant DB as Supabase DB
    participant WS as WebSocket
    participant ESP as ESP32 Device
    participant RP as Razorpay

    Note over ESP,API: ESP32 Boot & Registration
    ESP->>API: WS connect + register(machine_id, api_key)
    API->>DB: upsert_machine()
    API-->>ESP: display_code message
    ESP->>ESP: LCD shows "Code: XXXXXX"

    Note over User,ESP: User Lock Flow
    User->>UI: Enter name + display code
    UI->>API: POST /api/lock-by-code {client_id, code, name}
    API->>DB: Find machine by display_code
    API->>DB: Check existing lock
    API->>DB: Create lock row (expires_at = now+10min)
    API->>DB: Set machine status = locked
    API-->>UI: {machine_id, status: locked, expires_at}
    API->>ESP: WS: {type: lock, locked_by_name}
    ESP->>ESP: State → LOCKED, LCD "By: {name}"
    UI->>User: Alert "Locked until X"
    UI->>API: GET /public-status (fetch server time)
    API-->>UI: {server_time, expires_at}
    UI->>UI: Start countdown timer

    Note over User,RP: Payment Flow
    User->>UI: Select quantity, click Pay
    UI->>API: POST /create-order {quantity, machine_id}
    API->>DB: check_stock_available()
    API->>RP: order.create({amount, currency})
    RP-->>API: {order_id, amount}
    API-->>UI: order data
    UI->>RP: Open Razorpay checkout
    User->>RP: Complete payment
    RP-->>UI: {payment_id, signature}
    UI->>API: POST /verify-payment
    API->>RP: verify_payment_signature()
    RP-->>API: verified
    API-->>UI: Payment verified

    Note over UI,ESP: Dispense Flow
    UI->>API: POST /trigger-dispense {client_id, access_code, quantity, tx_id}
    API->>DB: Validate lock ownership & access_code
    API->>DB: Create transaction row
    API->>DB: Update lock status → consumed
    API->>ESP: WS: {type: command, action: dispense, duration, tx_id}
    ESP->>ESP: Motor runs for duration
    ESP->>ESP: Motor stops
    ESP->>API: POST /confirm {transaction_id, dispensed}
    API->>DB: Update transaction → completed
    API->>DB: Decrement current_stock
    API->>DB: Delete lock row
    API->>DB: Generate new display_code
    API->>ESP: WS: {type: unlock}
    API->>ESP: WS: {type: display_code, value: NEW_CODE}
    ESP->>ESP: State → UNLOCKED, LCD "Code: NEW_CODE"
    UI->>User: Show success popup
```

### 3.2 Lock Timeout Flow

```mermaid
sequenceDiagram
    participant Sweeper as Lock Expiry Sweeper
    participant API as FastAPI Backend
    participant DB as Supabase DB
    participant ESP as ESP32 Device

    Note over Sweeper: Runs every 2 seconds
    loop Every 2 seconds
        Sweeper->>DB: Check expired locks
        alt Lock expired
            Sweeper->>DB: Delete lock row
            Sweeper->>DB: Rotate display_code
            Sweeper->>DB: Set machine status → idle
            Sweeper->>ESP: WS: {type: unlock}
            Sweeper->>ESP: WS: {type: display_code, value: NEW}
            ESP->>ESP: State → UNLOCKED
        end
    end

    Note over ESP: ESP32 also has local timeout
    ESP->>ESP: if LOCKED > 10 min → UNLOCKED
    ESP->>API: WS: {type: status, value: unlocked}
```

### 3.3 Admin Operations Flow

```mermaid
sequenceDiagram
    actor Admin
    participant UI as Admin Dashboard
    participant API as FastAPI Backend
    participant DB as Supabase DB
    participant ESP as ESP32 Device

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
        API-->>UI: {token}
        UI->>UI: Store token, show dashboard
    end

    Admin->>UI: Click "Update Stock"
    Admin->>UI: Enter new stock level
    UI->>API: POST /api/machine/{id}/update-stock {stock}
    API->>DB: Update current_stock, last_refill_at
    API->>ESP: WS: {type: stock_update, stock}
    API-->>UI: Success
```

---

## 4. Activity Diagrams

### 4.1 User Complete Flow

```mermaid
flowchart TD
    A([Start]) --> B[Open SmartVend App]
    B --> C[View Machine List]
    C --> D{Select Machine}
    D -->|Machine Available| E[View Machine Page]
    D -->|Machine Offline/Out of Stock| C

    E --> F{Machine Locked by Others?}
    F -->|Yes| G[Wait for countdown to end]
    G --> F
    F -->|No| H[Enter Name & Display Code]

    H --> I[Click Lock]
    I --> J{Lock Success?}
    J -->|No - Invalid Code| H
    J -->|No - Already Locked| G
    J -->|Yes| K[Alert: Machine Locked]

    K --> L[Dismiss Alert]
    L --> M[Fetch Server Time]
    M --> N[Start 10-min Countdown]

    N --> O[Select Quantity]
    O --> P[Click Proceed to Payment]
    P --> Q{Locked?}
    Q -->|No| H
    Q -->|Yes| R[Create Razorpay Order]

    R --> S{Stock Available?}
    S -->|No| T[Error: Insufficient Stock]
    T --> O
    S -->|Yes| U[Open Razorpay Checkout]

    U --> V{Payment Completed?}
    V -->|Cancelled| O
    V -->|Yes| W[Verify Payment Signature]

    W --> X{Verified?}
    X -->|No| Y[Error: Verification Failed]
    Y --> O
    X -->|Yes| Z[Trigger Dispense]

    Z --> AA[ESP32 Runs Motor]
    AA --> AB[Show Dispensing Animation]
    AB --> AC[ESP32 Confirms Dispensing]
    AC --> AD[Show Success Popup]
    AD --> AE[Show Feedback Form]
    AE --> AF([End])

    N --> AG{Timeout?}
    AG -->|10 min elapsed| AH[Auto Unlock]
    AH --> C
```

### 4.2 ESP32 State Machine

```mermaid
stateDiagram-v2
    [*] --> Boot
    Boot --> WiFiConnect
    WiFiConnect --> WaitHealth
    WaitHealth --> WSConnect
    WSConnect --> UNLOCKED

    state UNLOCKED {
        ShowCode : Show display code on LCD
        SendHeartbeat : Send heartbeat every 1s
        RefreshCode : Refresh code every 5 min

        [*] --> ShowCode
        ShowCode --> SendHeartbeat
        SendHeartbeat --> ShowCode
        ShowCode --> RefreshCode
        RefreshCode --> ShowCode
    }

    state LOCKED {
        ShowLockedBy : LCD shows locked by username
        WaitCommand : Awaiting dispense command
        Dispensing : Received dispense command
        MotorRunning : Motor running forward
        MotorDone : Duration elapsed
        JamDetected : Current spike detected
        SendConfirm : POST confirm to server
        WaitUnlock : Awaiting unlock from server
        ErrorState : Stays LOCKED and sends error

        [*] --> ShowLockedBy
        ShowLockedBy --> WaitCommand
        WaitCommand --> Dispensing
        Dispensing --> MotorRunning
        MotorRunning --> MotorDone
        MotorRunning --> JamDetected
        MotorDone --> SendConfirm
        SendConfirm --> WaitUnlock
        JamDetected --> ErrorState
        ErrorState --> WaitUnlock
    }

    UNLOCKED --> LOCKED : Receive lock WS msg
    LOCKED --> UNLOCKED : Receive unlock WS msg
    LOCKED --> UNLOCKED : Lock timeout 10 min

    state WiFiLost {
        Reconnecting : Attempting reconnection
        [*] --> Reconnecting
        Reconnecting --> [*]
    }

    UNLOCKED --> WiFiLost : WiFi disconnected
    LOCKED --> WiFiLost : WiFi disconnected
    WiFiLost --> WSConnect : WiFi restored
```

### 4.3 Payment Processing Activity

```mermaid
flowchart TD
    A([Payment Initiated]) --> B[POST /create-order]
    B --> C{Razorpay Configured?}
    C -->|No| D[Error: Razorpay not configured]
    C -->|Yes| E{Quantity > 0?}
    E -->|No| F[Error: Invalid quantity]
    E -->|Yes| G[Check Stock Availability]

    G --> H{Stock >= Quantity?}
    H -->|No| I[Error 409: Insufficient stock]
    H -->|Yes| J[Create Razorpay Order]
    J --> K[Return order to frontend]

    K --> L[Frontend opens Razorpay Checkout]
    L --> M{User completes payment?}
    M -->|Cancelled| N([Payment Cancelled])
    M -->|Success| O[POST /verify-payment]

    O --> P[Verify Razorpay Signature]
    P --> Q{Signature Valid?}
    Q -->|No| R[Error 400: Verification failed]
    Q -->|Yes| S[POST /trigger-dispense]

    S --> T{Transaction already processed?}
    T -->|Yes| U[Error 409: Duplicate]
    T -->|No| V[Validate lock ownership]

    V --> W{Lock valid & owned?}
    W -->|No lock| X[Error 409: No active lock]
    W -->|Not owner| Y[Error 403: Not lock owner]
    W -->|Code mismatch| Z[Error 403: Access mismatch]
    W -->|Expired| AA[Error 409: Lock expired]
    W -->|Valid| AB[Create transaction record]

    AB --> AC[Mark lock as consumed]
    AC --> AD[Set machine status: dispatch_sent]
    AD --> AE[Send WS command to ESP32]
    AE --> AF([Dispatch Sent])
```

### 4.4 Server-Side Lock Expiry

```mermaid
flowchart TD
    A([Lock Expiry Sweeper Running]) --> B[Sleep 2 seconds]
    B --> C[Iterate connected machines]
    C --> D{Machine has active lock?}
    D -->|No| C
    D -->|Yes| E{Lock expired?}
    E -->|No| C
    E -->|Yes| F[Delete lock row]
    F --> G[Generate new display code]
    G --> H[Set machine status: idle]
    H --> I[Send WS unlock to ESP32]
    I --> J[Send new display_code to ESP32]
    J --> K[Publish to Redis for other workers]
    K --> C
```
