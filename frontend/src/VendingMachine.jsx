import { useState, useEffect, useRef } from "react";
import FeedbackForm from "./components/FeedbackForm";
import supabase from './supabase'; // added import

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL ;
const RAZORPAY_KEY_ID = import.meta.env.VITE_RAZORPAY_KEY_ID || 'rzp_test_9wMmdAOOz3dAXZ';
export default function VendingMachine({ machine, onBack }) {
  const [availablePads, setAvailablePads] = useState(machine.current_stock);
  const [selectedPads, setSelectedPads] = useState(1);
  const [accessCodeInput, setAccessCodeInput] = useState("");
  const [locked, setLocked] = useState(false);
  const [lockedUntil, setLockedUntil] = useState(null);
  const [lockedRemaining, setLockedRemaining] = useState(0);
  const [clientId, setClientId] = useState(() => {
    try { return localStorage.getItem('sv_client_id') || crypto.randomUUID(); } catch(e) { return 'client-' + Date.now(); }
  });
  const [transactionId, setTransactionId] = useState(null);
  const [showPopup, setShowPopup] = useState(false);
  const [isDispensing, setIsDispensing] = useState(false);
  const [dispensedPads, setDispensedPads] = useState(0);
  const [showFeedback, setShowFeedback] = useState(false);

  const handleIncrement = () => {
    if (selectedPads < 5 && selectedPads < availablePads) {
      setSelectedPads(selectedPads + 1);
    }
  };

  // persist clientId
  try { localStorage.setItem('sv_client_id', clientId); } catch(e) {}

  // countdown helper
  const getRemainingSeconds = (iso) => {
    if (!iso) return 0;
    const now = new Date();
    const exp = new Date(iso);
    return Math.max(0, Math.floor((exp - now) / 1000));
  }

  async function handleLockCode() {
    if (!accessCodeInput) return alert('Enter code shown on the machine');
    try {
      const res = await fetch(`${BACKEND_URL}/api/lock-by-code`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_id: clientId, code: accessCodeInput }),
      });
      if (!res.ok) {
        const err = await res.json().catch(()=>({detail:'Lock failed'}));
        return alert(err.detail || err.message || 'Lock failed');
      }
      const data = await res.json();
      setLocked(true);
      setLockedUntil(data.expires_at);
      // start polling machine status in background
      startStatusPolling();
      alert('Machine locked for you until ' + new Date(data.expires_at).toLocaleTimeString());
    } catch (err) {
      console.error('Lock error', err);
      alert('Lock failed');
    }
  }

  const statusPollRef = useRef(null);
  const countdownRef = useRef(null);
  function startStatusPolling() {
    if (statusPollRef.current) return;
    statusPollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${BACKEND_URL}/api/machine/${machine.machine_id}/public-status?client_id=${encodeURIComponent(clientId)}`);
        if (!res.ok) return;
        const s = await res.json();
        // update locked state from server
        if (s.locked && s.locked_by && s.locked_by === clientId) {
          setLocked(true);
          setLockedUntil(s.expires_at);
          // compute remaining seconds using server_time to avoid client clock drift
          if (s.server_time && s.expires_at) {
            try {
              const serverMs = Date.parse(s.server_time);
              const expMs = Date.parse(s.expires_at);
              const remaining = Math.max(0, Math.floor((expMs - serverMs) / 1000));
              setLockedRemaining(remaining);
              // start per-second countdown if not already
              if (!countdownRef.current) {
                countdownRef.current = setInterval(() => {
                  setLockedRemaining(r => {
                    if (r <= 1) {
                      clearInterval(countdownRef.current);
                      countdownRef.current = null;
                      return 0;
                    }
                    return r - 1;
                  });
                }, 1000);
              }
            } catch (e) {
              // ignore parse errors
            }
          }
        } else if (!s.locked) {
          setLocked(false);
          setLockedUntil(null);
          setLockedRemaining(0);
          if (countdownRef.current) { clearInterval(countdownRef.current); countdownRef.current = null; }
        }

        // detect dispense completion: when server reports idle after dispensing
        if (isDispensing && s.status === 'idle') {
          setIsDispensing(false);
          setShowPopup(true);
          // stop polling
          if (statusPollRef.current) {
            clearInterval(statusPollRef.current);
            statusPollRef.current = null;
          }
        }
      } catch (e) {
        // ignore errors, we'll retry
      }
    }, 2000);
  }

  useEffect(() => {
    return () => {
      if (statusPollRef.current) {
        clearInterval(statusPollRef.current);
        statusPollRef.current = null;
      }
      if (countdownRef.current) { clearInterval(countdownRef.current); countdownRef.current = null; }
    }
  }, []);

  // on mount, check whether this client already holds a lock for this machine
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const res = await fetch(`${BACKEND_URL}/api/machine/${machine.machine_id}/public-status?client_id=${encodeURIComponent(clientId)}`);
        if (!mounted || !res.ok) return;
        const s = await res.json();
        if (s.locked && s.locked_by && s.locked_by === clientId) {
          setLocked(true);
          setLockedUntil(s.expires_at);
          // compute remaining seconds using server_time
          if (s.server_time && s.expires_at) {
            const serverMs = Date.parse(s.server_time);
            const expMs = Date.parse(s.expires_at);
            const remaining = Math.max(0, Math.floor((expMs - serverMs) / 1000));
            setLockedRemaining(remaining);
            // start countdown and polling
            startStatusPolling();
          }
        }
      } catch (e) {
        // ignore
      }
    })();
    return () => { mounted = false; }
  }, []);

  // helper to format seconds into mm:ss
  const formatSeconds = (s) => {
    const mm = Math.floor(s / 60).toString().padStart(2, '0');
    const ss = (s % 60).toString().padStart(2, '0');
    return `${mm}:${ss}`;
  }

  const handleDecrement = () => {
    if (selectedPads > 1) {
      setSelectedPads(selectedPads - 1);
    }
  };

  async function dispense(number) {
  try {
    // Use trigger-dispense endpoint with required validation fields
    const res = await fetch(`${BACKEND_URL}/api/machine/${machine.machine_id}/trigger-dispense`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ 
        client_id: clientId,
        access_code: accessCodeInput,
        quantity: number,
        transaction_id: crypto.randomUUID(),
        amount: number * 500
      }),
    });

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }

    const data = await res.json();

    // backend returns { status: "ok", ... }
    if (data.status === "ok" || data.status === "success") {
      // fetch current stock from supabase and update
      const { data: stockData, error: fetchError } = await supabase
        .from("machines")
        .select("current_stock")
        .eq("machine_id", machine.machine_id)
        .single();

      if (fetchError) throw fetchError;
      const newStock = (stockData.current_stock ?? 0) - number;

      const { error: updateError } = await supabase
        .from("machines")
        .update({ current_stock: newStock })
        .eq("machine_id", machine.machine_id);

      if (updateError) {
        alert(`Dispense ok, but stock update failed: ${updateError.message}`);
      } else {
        alert("✅ Dispensing successful and stock updated!");
      }
    } else {
      alert(`❌ Hardware dispensing failed: ${data.error || JSON.stringify(data)}`);
    }
  } catch (err) {
    alert(`❌ Error: ${err?.message ?? err}`);
  }
}

  const handlePayment = async () => {
    if (!locked) return alert('Please lock the machine by entering the code first');
    const txId = (crypto && crypto.randomUUID) ? crypto.randomUUID() : 'tx-' + Date.now();
    setTransactionId(txId);
    try {
      console.log('Making payment request to:', `${BACKEND_URL}/create-order`);
      const response = await fetch(`${BACKEND_URL}/create-order`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // amount in paise; include transaction metadata so backend can link if desired
        body: JSON.stringify({ amount: selectedPads * 500, metadata: { transaction_id: txId, client_id: clientId, machine_id: machine.machine_id } }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      const { order_id, amount, currency } = data;
      const options = {
        key: RAZORPAY_KEY_ID,
        amount: amount,
        currency: currency,
        name: "SmartVend",
        description: "Purchase",
        order_id: order_id,
        handler: async function (response) {
          const paymentData = {
            razorpay_payment_id: response.razorpay_payment_id,
            razorpay_order_id: response.razorpay_order_id,
            razorpay_signature: response.razorpay_signature,
          };
          try {
            const verifyResponse = await fetch(`${BACKEND_URL}/verify-payment`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(paymentData),
            });
            const verificationData = await verifyResponse.json();
            // after successful verification, request backend to trigger dispense
            const tdRes = await fetch(`${BACKEND_URL}/api/machine/${machine.machine_id}/trigger-dispense`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ client_id: clientId, access_code: accessCodeInput, quantity: selectedPads, transaction_id: txId, amount: selectedPads * 500 }),
            });
            if (!tdRes.ok) {
              const err = await tdRes.json().catch(() => ({}));
              throw new Error(err.detail || err.message || 'Trigger dispense failed');
            }

            // success: update UI and start polling status for confirmation
            setAvailablePads(availablePads - selectedPads);
            setIsDispensing(true);
            startStatusPolling();
            // animate dispensed count locally
            for (let i = 1; i <= selectedPads; i++) {
              setTimeout(() => setDispensedPads(i), 1000 * i);
            }

          } catch (error) {
            console.error("Payment verification or trigger error:", error);
            alert(error.message || 'Payment/dispense failed');
          }
        },
        theme: { color: "#F37254" },
      };
      const razorpay = new window.Razorpay(options);
      razorpay.open();
    } catch (error) {
      console.error("Payment error", error);
      alert("Payment failed. Please try again.");
    }
  };

  return (
    <div className="min-h-screen flex flex-col bg-gradient-to-b from-purple-50 to-purple-100 p-6 relative">
      <button
        className="absolute top-4 left-4 bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-lg transition-colors duration-200 shadow-md flex items-center space-x-2"
        onClick={onBack}
        aria-label="Back to machine selection"
      >
        <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M7.707 14.707a1 1 0 01-1.414 0l-5-5a1 1 0 010-1.414l5-5a1 1 0 111.414 1.414L4.414 8H17a1 1 0 110 2H4.414l3.293 3.293a1 1 0 010 1.414z" clipRule="evenodd" />
        </svg>
        <span>Back</span>
      </button>
      <div className="max-w-md w-full mx-auto mt-12 mb-8 bg-white rounded-2xl shadow-lg overflow-hidden">
        <div className="bg-gradient-to-r from-purple-600 to-violet-500 text-white p-6 text-center">
          <div className="flex justify-center space-x-2">
            <img src="/logo.png" alt="SmartVend Logo" className="h-10 w-10" />
            <h1 className="text-3xl font-bold">Smart<span className="text-green-400">Vend</span></h1>
          </div>
          <div className="flex items-center justify-between mt-2">
            <p className="text-purple-100">Hygiene Products Dispenser</p>
            <button
              onClick={() => setShowFeedback(true)}
              className="flex items-center space-x-1 bg-white/10 hover:bg-white/20 text-white px-3 py-1 rounded-full text-sm transition-colors duration-200"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M18 10c0 4.418-3.582 8-8 8s-8-3.582-8-8 3.582-8 8-8 8 3.582 8 8zm-8-3a1 1 0 00-1 1v2a1 1 0 102 0V8a1 1 0 00-1-1zm0 6a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
              </svg>
              <span>Feedback</span>
            </button>
          </div>
        </div>
        <div className="grid text-center gap-4 p-6 bg-gray-50">
          <div className="p-3 bg-white rounded-lg shadow-sm border border-gray-100">
            <p className="text-gray-500 text-sm">Machine ID</p>
            <p className="font-bold text-gray-800 font-mono">{machine.machine_id}</p> {/* use machine_id */}
            <p className="text-gray-500 text-sm mt-1">Location: <span className="font-semibold text-purple-700">{machine.location}</span></p>
          </div>
          <div className="p-3 bg-white rounded-lg shadow-sm border border-gray-100">
            <p className="text-gray-500 text-sm">Enter Code shown on machine</p>
            <div className="flex items-center justify-center mt-2 space-x-2">
              <input value={accessCodeInput} onChange={(e)=>setAccessCodeInput(e.target.value)} className="px-3 py-2 border rounded-md w-48" placeholder="MV-XXXXXXX" />
              <button onClick={handleLockCode} className="bg-purple-600 text-white px-3 py-2 rounded-md">Lock</button>
            </div>
            {locked && (
              <p className="text-green-600 text-sm mt-2">Locked — time left: <span className="font-mono ml-1">{formatSeconds(lockedRemaining)}</span></p>
            )}
            {locked && (
              <div className="mt-2">
                <button onClick={async ()=>{
                  try {
                    const res = await fetch(`${BACKEND_URL}/api/machine/${machine.machine_id}/unlock`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ client_id: clientId }) });
                    if (!res.ok) { const e = await res.json().catch(()=>({detail:'unlock failed'})); return alert(e.detail || e.message || 'Unlock failed'); }
                    const d = await res.json();
                    setLocked(false); setLockedUntil(null); setAccessCodeInput('');
                    alert('Unlocked ');
                  } catch(err) { console.error(err); alert('Unlock failed'); }
                }} className="bg-red-500 text-white px-3 py-1 rounded-md">Unlock</button>
              </div>
            )}
          </div>
        </div>
        <div className="p-6 border-b border-gray-200">
          <div className="flex justify-between items-center">
            <p className="text-lg font-medium text-gray-700">Pads Available:</p>
            <div className="bg-purple-100 px-4 py-1 rounded-full">
              <span className="font-bold text-purple-800">{availablePads}</span>
            </div>
          </div>
          {availablePads < 3 && (
            <div className="mt-2 text-sm text-amber-600 flex items-center">
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 mr-1" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
              </svg>
              Low inventory
            </div>
          )}
        </div>
        <div className="p-6 border-b border-gray-200">
          <p className="text-lg font-medium text-gray-700 mb-3">Select Quantity:</p>
          <div className="flex items-center justify-between bg-gray-50 p-4 rounded-lg">
            <button
              className="w-10 h-10 flex items-center justify-center bg-white text-purple-600 rounded-full shadow-sm border border-gray-200 hover:bg-purple-50 transition-colors duration-200"
              onClick={handleDecrement}
              disabled={selectedPads <= 1}
              aria-label="Decrease quantity"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M3 10a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" clipRule="evenodd" />
              </svg>
            </button>
            <div className="flex flex-col items-center">
              <p className="text-2xl font-bold text-gray-800">{selectedPads}</p>
              <p className="text-sm text-gray-500">pad{selectedPads > 1 ? 's' : ''} selected</p>
            </div>
            <button
              className="w-10 h-10 flex items-center justify-center bg-white text-purple-600 rounded-full shadow-sm border border-gray-200 hover:bg-purple-50 transition-colors duration-200"
              onClick={handleIncrement}
              disabled={selectedPads >= 5 || selectedPads >= availablePads}
              aria-label="Increase quantity"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clipRule="evenodd" />
              </svg>
            </button>
          </div>
        </div>
        <div className="p-6">
          <div className="flex justify-between items-center mb-6">
            <p className="text-lg text-gray-600">Total Price:</p>
            <p className="text-2xl font-bold text-purple-700">₹{selectedPads * 5}</p>
          </div>
          <div className="flex flex-col space-y-4">
            <button
              className="w-full bg-purple-600 hover:bg-purple-700 text-white py-3 px-4 rounded-lg font-medium shadow-md transition-colors duration-200 flex items-center justify-center space-x-2"
              onClick={handlePayment}
              disabled={availablePads < selectedPads}
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clipRule="evenodd" />
              </svg>
              <span>Proceed to Payment</span>
            </button>
          </div>
        </div>
      </div>
      {showPopup && (
        <div className="fixed inset-0 flex items-center justify-center bg-black bg-opacity-50 z-50" aria-modal="true" role="dialog">
          <div className="bg-white p-6 rounded-lg shadow-xl max-w-sm w-full text-center">
            <div className="w-16 h-16 mx-auto bg-green-100 rounded-full flex items-center justify-center mb-4">
              <svg xmlns="http://www.w3.org/2000/svg" className="h-10 w-10 text-green-600" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
              </svg>
            </div>
            <h2 className="text-xl font-bold text-gray-800 mb-2">Payment Successful!</h2>
            <p className="text-gray-600 mb-6">Please collect your {selectedPads} pad{selectedPads > 1 ? 's' : ''} from the dispenser.</p>
            <button
              className="bg-purple-600 hover:bg-purple-700 text-white px-6 py-3 rounded-md transition-colors duration-200 w-full"
              onClick={() => {
                setShowPopup(false);
                setSelectedPads(1);
                setDispensedPads(1);
                setShowFeedback(true); // Re-enable automatic feedback prompt
              }}
            >
              Done
            </button>
          </div>
        </div>
      )}
      {showFeedback && (
        <FeedbackForm
          machineId={machine.machine_id}
          onClose={() => setShowFeedback(false)}
        />
      )}
      {isDispensing && (
        <div className="fixed inset-0 flex items-center justify-center bg-black bg-opacity-50">
          <div className="bg-white p-6 rounded-lg shadow-lg text-center">
            <h2 className="text-xl font-bold text-yellow-600">Dispensing Pads...</h2>
            <p className="text-gray-600">{dispensedPads} / {selectedPads} Pad(s) dispensed</p>
          </div>
        </div>
      )}
    </div>
  );
}
