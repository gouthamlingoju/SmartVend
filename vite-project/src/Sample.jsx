import { useEffect, useState } from "react";
// import { updatePadsCount } from "./Firebase";

export default function VendingMachine() {
  const [availablePads, setAvailablePads] = useState(9);
  const [selectedPads, setSelectedPads] = useState(1);
  const [showPopup, setShowPopup] = useState(false);
  const [showAdminPopup, setShowAdminPopup] = useState(false);
  const [adminPassword, setAdminPassword] = useState("");
  const [isAdminAuthenticated, setIsAdminAuthenticated] = useState(false);
  const [newPadCount, setNewPadCount] = useState("");
  const [adminAction, setAdminAction] = useState("add"); // "add" or "set"
  const machineID="B-123";


//   useEffect(() => {
//     // Load Razorpay script dynamically
//     const script = document.createElement("script");
//     script.src = "https://checkout.razorpay.com/v1/checkout.js";
//     script.async = true;
//     document.body.appendChild(script);

//     // Check inventory level and send alert if necessary
//     if (availablePads < 5) {
//       sendLowInventoryAlert();
//     }

//     return () => {
//       // Cleanup script on component unmount
//       document.body.removeChild(script);
//     };
//   }, [availablePads]);

//   const sendLowInventoryAlert = async () => {
//     try {
//       const response = await fetch('http://localhost:5000/send-email', {
//         method: 'POST',
//         headers: {
//           'Content-Type': 'application/json',
//         },
//         body: JSON.stringify({
//           email: "test@example.com",
//           subject: "Low Inventory Alert",
//           body: "The inventory of pads is running low. Please restock soon.",
//         }),
//       });

//       const data = await response.json();
//       if (response.ok) {
//         console.log("Email sent successfully:", data.message);
//       } else {
//         console.error("Error from server:", data.error);
//       }
//     } catch (error) {
//       console.error("Error sending email:", error);
//     }
//   };

//   const handlePayment = async () => {
//     try {
//       const response = await fetch('http://localhost:5000/create-order', {
//         method: 'POST',
//         headers: {
//           'Content-Type': 'application/json',
//         },
//         body: JSON.stringify({ amount: selectedPads * 500 }), // Assuming 500 is the amount in paise (e.g., 5 INR)
//       });

//       const data = await response.json();
//       if (!response.ok) throw new Error(data.error || "Failed to create order");

//       const options = {
//         key: "rzp_test_ZEcyPeIGYJzIxT",
//         amount: data.amount,
//         currency: "INR",
//         name: "Smart Vend",
//         description: `Purchase of ${selectedPads} sanitary pad${selectedPads > 1 ? 's' : ''}`,
//         order_id: data.order_id,
//         handler: async function (response) {
//           console.log("Payment Successful:", response);
//           setAvailablePads((prev) => prev - selectedPads);
//           setShowPopup(true);
//         },
//         prefill: {
//           name: "Customer",
//           email: "customer@example.com",
//           contact: "9948587314",
//         },
//         theme: { color: "#8b5cf6" },
//       };

//       const rzp1 = new window.Razorpay(options);
//       rzp1.open();
//     } catch (error) {
//       console.error("Error initializing Razorpay:", error);
//     }
//   };
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
                  body: JSON.stringify({ message: "Pads are low in stock. Please restock.", machineID , Remaining: (availablePads-selectedPads) } ),
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


  const handleAdminSubmit = () => {
    if (adminPassword === "admin123") { // Replace with secure authentication
      setIsAdminAuthenticated(true);
    } else {
      alert("Incorrect password");
    }
  };

  

  const handleUpdatePads = () => {
    if (adminAction === "add") {
      setAvailablePads((prev) => prev + parseInt(newPadCount));
    } else {
      setAvailablePads(parseInt(newPadCount));
    }
    updatePadsCount(availablePads); // Update in Firebase
    setShowAdminPopup(false);
    setIsAdminAuthenticated(false);
    setNewPadCount("");
  };

  const handleDecrement = () => {
    if (selectedPads > 1) {
      setSelectedPads((prev) => prev - 1);
    }
  };

  const handleIncrement = () => {
    if (selectedPads < availablePads && selectedPads < 5) {
      setSelectedPads((prev) => prev + 1);
    }
  };

  return (
    <div className="min-h-screen flex flex-col bg-gradient-to-b from-purple-50 to-purple-100 p-6 relative">
      {/* Admin button */}
      <button
        className="absolute top-4 right-4 bg-gray-700 hover:bg-gray-800 text-white px-4 py-2 rounded-lg transition-colors duration-200 shadow-md flex items-center space-x-2"
        onClick={() => setShowAdminPopup(true)}
        aria-label="Open Admin Portal"
      >
        <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-6-3a2 2 0 11-4 0 2 2 0 014 0zm-2 4a5 5 0 00-4.546 2.916A5.986 5.986 0 005 16a5 5 0 0010 0c0-1.139-.321-2.203-.874-3.108A5.001 5.001 0 0010 11z" clipRule="evenodd" />
        </svg>
        <span>Admin</span>
      </button>

      {/* Main content container */}
      <div className="max-w-md w-full mx-auto mt-12 mb-8 bg-white rounded-2xl shadow-lg overflow-hidden">
        {/* Header */}
        <div className="bg-gradient-to-r from-purple-600 to-violet-500 text-white p-6 text-center">
          <h1 className="text-3xl font-bold">Smart Vend</h1>
          <p className="text-purple-100 mt-1">Hygiene Products Dispenser</p>
        </div>

        {/* Machine info */}
        <div className="grid text-center gap-4 p-6 bg-gray-50">
          {/* <div className="p-3 bg-white rounded-lg shadow-sm border border-gray-100">
            <p className="text-gray-500 text-sm">Mach</p>
            <p className="font-bold text-gray-800">B block 123</p>
          </div> */}
          <div className="p-3 bg-white rounded-lg shadow-sm border border-gray-100">
            <p className="text-gray-500 text-sm">Machine ID</p>
            <p className="font-bold text-gray-800 font-mono">{machineID}</p>
          </div>
        </div>

        {/* Inventory status */}
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

        {/* Quantity selector */}
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

        {/* Price and payment */}
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

      {/* Admin Popup */}
      {showAdminPopup && (
        <div className="fixed inset-0 flex items-center justify-center bg-black bg-opacity-50 z-50" aria-modal="true" role="dialog">
          <div className="bg-white p-6 rounded-lg shadow-xl max-w-md w-full">
            {!isAdminAuthenticated ? (
              <>
                <h2 className="text-xl font-bold text-gray-800 mb-4">Admin Login</h2>
                <input
                  type="password"
                  placeholder="Enter Password"
                  className="mt-3 p-3 border border-gray-300 rounded-md w-full focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                  value={adminPassword}
                  onChange={(e) => setAdminPassword(e.target.value)}
                />
                <div className="mt-6 flex space-x-4">
                  <button
                    className="flex-1 bg-purple-600 hover:bg-purple-700 text-white py-2 px-4 rounded-md transition-colors duration-200"
                    onClick={handleAdminSubmit}
                  >
                    Login
                  </button>
                  <button
                    className="flex-1 bg-gray-200 hover:bg-gray-300 text-gray-800 py-2 px-4 rounded-md transition-colors duration-200"
                    onClick={() => setShowAdminPopup(false)}
                  >
                    Cancel
                  </button>
                </div>
              </>
            ) : (
              <>
                <h2 className="text-xl font-bold text-gray-800 mb-4">Inventory Management</h2>
                <p className="text-sm text-gray-600 mb-4">Current inventory: <span className="font-semibold">{availablePads} pads</span></p>

                <div className="flex space-x-2 mb-6">
                  <button
                    className={`flex-1 py-2 px-3 rounded ${adminAction === 'add' ? 'bg-purple-100 text-purple-700 border-2 border-purple-500' : 'bg-gray-100 text-gray-700 border border-gray-300'}`}
                    onClick={() => setAdminAction("add")}
                  >
                    Add Inventory
                  </button>
                  <button
                    className={`flex-1 py-2 px-3 rounded ${adminAction === 'set' ? 'bg-purple-100 text-purple-700 border-2 border-purple-500' : 'bg-gray-100 text-gray-700 border border-gray-300'}`}
                    onClick={() => setAdminAction("set")}
                  >
                    Set Exact Count
                  </button>
                </div>

                <div className="mb-6">
                  <label htmlFor="padCount" className="block text-sm font-medium text-gray-700 mb-1">
                    {adminAction === 'add' ? 'Add Pad Count' : 'New Total Pad Count'}
                  </label>
                  <input
                    id="padCount"
                    type="number"
                    placeholder={adminAction === 'add' ? "Enter number to add" : "Enter total count"}
                    className="p-3 border border-gray-300 rounded-md w-full focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                    value={newPadCount}
                    onChange={(e) => setNewPadCount(e.target.value)}
                  />
                  {adminAction === 'add' && newPadCount && !isNaN(parseInt(newPadCount)) && (
                    <p className="mt-2 text-sm text-gray-600">
                      New total will be: <span className="font-bold text-purple-700">{availablePads + parseInt(newPadCount)} pads</span>
                    </p>
                  )}
                </div>

                <div className="flex space-x-4">
                  <button
                    className="flex-1 bg-green-600 hover:bg-green-700 text-white py-2 px-4 rounded-md transition-colors duration-200"
                    onClick={handleUpdatePads}
                  >
                    {adminAction === 'add' ? 'Add Inventory' : 'Update Inventory'}
                  </button>
                  <button
                    className="flex-1 bg-gray-200 hover:bg-gray-300 text-gray-800 py-2 px-4 rounded-md transition-colors duration-200"
                    onClick={() => {
                      setShowAdminPopup(false);
                      setIsAdminAuthenticated(false);
                      setNewPadCount("");
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Success Popup */}
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
              onClick={() => setShowPopup(false)}
            >
              Done
            </button>
          </div>
        </div>
      )}
    </div>
  );
}