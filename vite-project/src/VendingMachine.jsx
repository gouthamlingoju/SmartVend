import { useState } from "react";

export default function VendingMachine() {
  const [availablePads, setAvailablePads] = useState(6);
  const [selectedPads, setSelectedPads] = useState(1);
  const [showPopup, setShowPopup] = useState(false);
  const [isDispensing, setIsDispensing] = useState(false); // New state for dispensing simulation
  const [dispensedPads, setDispensedPads] = useState(0); // To track how many pads are dispensed

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

  const handlePayment = async () => {
    try {
      console.log("Payment button clicked! Pads selected: ", selectedPads);

      // Step 1: Create the order on your backend
      const response = await fetch('http://localhost:5000/create-order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amount: selectedPads * 500 }), // amount in paise (e.g., 500 paise = 5 INR per pad)
      });

      const data = await response.json();
      const { order_id, amount, currency } = data;

      // Step 2: Open the Razorpay checkout modal
      const options = {
        key: "rzp_test_ZEcyPeIGYJzIxT",  // Your Razorpay public key
        amount: amount,
        currency: currency,
        name: "SmartVend",
        description: "Test Transaction",
        order_id: order_id,
        handler: async function (response) {
          // Step 3: Call backend to verify the payment signature
          const paymentData = {
            razorpay_payment_id: response.razorpay_payment_id,
            razorpay_order_id: response.razorpay_order_id,
            razorpay_signature: response.razorpay_signature,
          };

          try {
            // Step 4: Verify payment
            const verifyResponse = await fetch('http://localhost:5000/verify-payment', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(paymentData),
            });

            const verificationData = await verifyResponse.json();

            if (1) {
              // Successfully verified, now update the available pads
              setAvailablePads(availablePads - selectedPads);

              // Simulate dispensing process
              setIsDispensing(true);
              for (let i = 0; i <= selectedPads; i++) {
                setTimeout(() => {
                  setDispensedPads(i + 1);
                }, 1000 * (i + 1)); // Delay for each pad dispensed
              }

              // After dispensing is done, reset the dispensing state and show success popup
              setTimeout(() => {
                setIsDispensing(false);
                setShowPopup(true);
              }, 1000 * selectedPads);

              // Check for low stock after dispensing
              if (availablePads - selectedPads <= 5) {
                const lowStockResponse = await fetch('http://localhost:5000/low-stock-alert', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ message: "Pads are low in stock. Please restock." }),
                });

                const lowStockData = await lowStockResponse.json();
                console.log("Low stock alert sent to the backend:", lowStockData);

                alert("Low stock alert sent to the backend!");
              }

            } else {
              console.log("Payment verification failed!", verificationData);
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
    <div className="min-h-screen flex flex-col items-center justify-center bg-purple-100 p-6">
      <h1 className="text-3xl font-bold text-purple-700">Smart Vend</h1>
      <p className="text-sm text-purple-500 mb-6">Hygiene Products Dispenser</p>

      <div
        className={`w-96 p-6 rounded-xl shadow-md ${
          availablePads < 5 ? "bg-red-100" : "bg-white"
        }`}
      >
        <div className="grid grid-cols-1 text-center gap-4 mb-4">
          <div className="p-3 bg-gray-100 rounded-lg">
            <p className="text-gray-500 text-sm">Machine ID</p>
            <p className="font-bold">B-123</p>
          </div>
        </div>

        <p className="text-lg font-medium">
          Pads Available: <span className="font-bold">{availablePads}</span>
        </p>

        <div className="flex items-center justify-between mt-3">
          <p className="text-lg font-medium">Pads Selected:</p>
          <div className="flex items-center">
            <button
              className="w-8 h-8 bg-gray-300 text-black rounded-md"
              onClick={handleDecrement}
            >
              -
            </button>
            <p className="mx-4">{selectedPads}</p>
            <button
              className="w-8 h-8 bg-gray-300 text-black rounded-md"
              onClick={handleIncrement}
            >
              +
            </button>
          </div>
        </div>

        <p className="text-xl font-bold mt-4">Total Price: ₹{selectedPads * 5}</p>

        {availablePads > 0 && selectedPads <= availablePads && (
          <button
            onClick={handlePayment}
            className="bg-blue-500 text-white py-2 px-4 rounded hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            Pay Here
          </button>
        )}
      </div>

      {/* Dispensing Simulation */}
      {isDispensing && (
        <div className="fixed inset-0 flex items-center justify-center bg-black bg-opacity-50">
          <div className="bg-white p-6 rounded-lg shadow-lg text-center">
            <h2 className="text-xl font-bold text-yellow-600">Dispensing Pads...</h2>
            <p className="text-gray-600">{dispensedPads} / {selectedPads} Pad(s) dispensed</p>
          </div>
        </div>
      )}

      {/* Payment Success Popup */}
      {showPopup && (
        <div className="fixed inset-0 flex items-center justify-center bg-black bg-opacity-50">
          <div className="bg-white p-6 rounded-lg shadow-lg text-center">
            <h2 className="text-xl font-bold text-green-600">Payment Successful!</h2>
            <p className="text-gray-600">{selectedPads} Pad(s) dispensed successfully!!</p>
            <button
              className="mt-4 bg-green-600 text-white px-4 py-2 rounded-md"
              onClick={() => {setShowPopup(false);
                setSelectedPads(1);
              }}
            >
              OK
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
