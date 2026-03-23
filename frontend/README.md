# SmartVend Frontend

React + Vite + Tailwind 4 frontend for the SmartVend vending machine platform.

## Setup

```bash
npm install
npm run dev
```

Open http://localhost:5173

## Environment Variables

Create a `.env` file:

```env
VITE_BACKEND_URL=http://localhost:8000
VITE_RAZORPAY_KEY_ID=rzp_test_xxx
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=your-anon-key
VITE_PRICE_PER_UNIT=1
```

## Routes

| Route | Component | Purpose |
|---|---|---|
| `/` | `MachineList` | Browse available machines |
| `/machine/:machineId` | `VendingMachine` | Legacy code-entry flow |
| `/vend/:machineId/:sessionToken` | `VendingSession` | **v3.0 QR scan flow** |
| `/admin` | `AdminDashboard` | Admin panel (JWT auth) |
| `/admin-login` | `AdminLogin` | Admin login form |

## Key Components

| Component | File | Purpose |
|---|---|---|
| `VendingSession` | `src/VendingSession.jsx` | QR scan → claim → pay → dispense flow |
| `VendingMachine` | `src/VendingMachine.jsx` | Legacy code-entry flow (still works) |
| `MachineList` | `src/components/MachineList.jsx` | Machine browser |
| `QuantitySelector` | `src/components/QuantitySelector.jsx` | Qty +/- control |
| `SuccessPopup` | `src/components/SuccessPopup.jsx` | Dispense animation + success |
| `FeedbackForm` | `src/components/FeedbackForm.jsx` | Post-purchase feedback |
| `AdminDashboard` | `src/components/AdminDashboard.jsx` | Stock management |
| `AdminLogin` | `src/components/AdminLogin.jsx` | Admin auth |

## Build

```bash
npm run build   # Output in dist/
npm run preview # Preview production build
```

## Tech Stack

- React 19
- Vite 6
- Tailwind CSS 4
- react-router-dom 7
- Razorpay Checkout SDK (loaded via script tag)
