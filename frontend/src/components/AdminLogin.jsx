import React, { useState } from 'react';

export default function AdminLogin({ onSuccess, onBack }) {
  const [adminPassword, setAdminPassword] = useState("");
  const [authError, setAuthError] = useState("");
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gradient-to-br from-purple-200 via-blue-100 to-pink-100">
      <div className="bg-white rounded-2xl shadow-lg p-10 flex flex-col items-center">
        <h2 className="text-2xl font-bold text-purple-700 mb-4">Admin Login</h2>
        <input
          type="password"
          placeholder="Enter Admin Password"
          className="mt-3 p-3 border border-gray-300 rounded-md w-full focus:ring-2 focus:ring-purple-500 focus:border-transparent"
          value={adminPassword}
          onChange={e => setAdminPassword(e.target.value)}
        />
        {authError && <div className="text-red-600 mt-2">{authError}</div>}
        <button
          className="mt-6 bg-purple-600 hover:bg-purple-700 text-white py-2 px-8 rounded-md text-lg"
          onClick={() => {
            if (adminPassword === 'admin123') {
              setAuthError("");
              onSuccess();
            } else {
              setAuthError("Incorrect password");
            }
          }}
        >Login</button>
        <button className="mt-2 text-gray-500 underline" onClick={onBack}>Back</button>
      </div>
    </div>
  );
}
