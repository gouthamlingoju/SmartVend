import { useState } from "react";

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;
const RAZORPAY_KEY_ID = import.meta.env.VITE_RAZORPAY_KEY_ID;

export default function VendingMachine({ machine, onBack }) {
  const [availablePads, setAvailablePads] = useState(machine.stock);
  const [selectedPads, setSelectedPads] = useState(1);
  const [showPopup, setShowPopup] = useState(false);
  const [isDispensing, setIsDispensing] = useState(false);
  const [dispensedPads, setDispensedPads] = useState(0);

  const handleIncrement = () => {
    if (selectedPads < 5 && selectedPads < availablePads) {
      setSelectedPads(selectedPads + 1);
    }
  };

  const handleDecrement = () => {
    if (selectedPads > 1) {
      setSelectedPads(selectedPads - 1);
    }
  };

  function blinkLED(number) {
    fetch(`${BACKEND_URL}/dispense`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ number }),
    })
      .then(res => res.json())
      .then(data => console.log(data))
      .catch(err => console.error(err));
  }

  const handlePayment = async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/create-order`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amount: selectedPads * 500 }),
      });
      const data = await response.json();
      const { order_id, amount, currency } = data;
      console.log("ID:",RAZORPAY_KEY_ID );
      const options = {
        key: "rzp_test_ZEcyPeIGYJzIxT",
        amount: amount,
        currency: currency,
        name: "SmartVend",
        description: "Test Transaction",
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
            if (1) {
              setAvailablePads(availablePads - selectedPads);
              setIsDispensing(true);
              blinkLED(selectedPads);
              for (let i = 0; i <= selectedPads; i++) {
                setTimeout(() => {
                  setDispensedPads(i + 2);
                }, 1000 * (i + 1));
              }
              setTimeout(() => {
                setIsDispensing(false);
                setShowPopup(true);
              }, 1000 * selectedPads);
              if (availablePads - selectedPads <= -1) {
                await fetch(`${BACKEND_URL}/low-stock-alert`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ message: "Pads are low in stock. Please restock.", machineID: machine.id, Remaining: (availablePads - selectedPads) }),
                });
              }
            }
          } catch (error) {
            console.error("Payment verification error:", error);
          }
        },
        prefill: {
          name: "Customer Name",
          email: "customer@example.com",
          contact: "9876543210",
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
          <p className="text-purple-100 mt-1">Hygiene Products Dispenser</p>
        </div>
        <div className="grid text-center gap-4 p-6 bg-gray-50">
          <div className="p-3 bg-white rounded-lg shadow-sm border border-gray-100">
            <p className="text-gray-500 text-sm">Machine ID</p>
            <p className="font-bold text-gray-800 font-mono">{machine.id}</p>
            <p className="text-gray-500 text-sm mt-1">Location: <span className="font-semibold text-purple-700">{machine.location}</span></p>
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
              onClick={() => {setShowPopup(false); setSelectedPads(1); setDispensedPads(1);}}
            >
              Done
            </button>
          </div>
        </div>
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
