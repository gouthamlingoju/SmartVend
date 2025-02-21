// src/components/PaymentButton.jsx
import React from 'react';

const PaymentButton = (props) => {
  // Function to handle the payment

  const handlePayment = async () => {
    console.log("Payment button clicked! Pads selected: ", props.selectedPads);
    try {
      // Step 1: Create the order on your backend
      const response = await fetch('http://localhost:5000/create-order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amount: 5000 }), // Example: 5000 paise = 50 INR
      });
  
      const data = await response.json();
      const { order_id, amount, currency } = data;
  
      // Step 2: Open the Razorpay checkout modal
      const options = {
        key: "rzp_test_ZEcyPeIGYJzIxT",  // Your Razorpay public key
        amount: amount,
        currency: currency,
        name: "Your Company Name",
        description: "Test Transaction",
        order_id: order_id,
        handler: async function (response) {
          alert(`${props.selectedPads} Pads Dispensed Successfully!`); // Show success message
          // Step 3: Call backend to verify the payment signature
          const paymentData = {
            razorpay_payment_id: response.razorpay_payment_id,
            razorpay_order_id: response.razorpay_order_id,
            razorpay_signature: response.razorpay_signature,
          };
  
          const verifyResponse = await fetch('http://localhost:5000/verify-payment', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(paymentData),
          });
  
          const verificationData = await verifyResponse.json();
          alert(verificationData.message); // Show success message
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
    }
  };
  

  return (
    <div>
        <button onClick={handlePayment} className="bg-blue-500 text-white py-2 px-4 rounded hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500">
          Pay Here
        </button>
    </div>
  );
};

export default PaymentButton;
