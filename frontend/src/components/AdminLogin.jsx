import React, { useState, useEffect } from 'react';
const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;

export default function AdminLogin({ onSuccess, onBack }) {
  const [adminPassword, setAdminPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [loading, setLoading] = useState(true);

  // Check for existing token on mount
  useEffect(() => {
    const token = localStorage.getItem('admin_token');
    if (token) {
      verifyToken(token);
    } else {
      setLoading(false);
    }
  }, []);

  const verifyToken = async (token) => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/admin/verify`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      if (res.ok) {
        onSuccess();
      } else {
        localStorage.removeItem('admin_token');
        setLoading(false);
      }
    } catch (err) {
      console.error('Token verification failed:', err);
      localStorage.removeItem('admin_token');
      setLoading(false);
    }
  };

  const handleLogin = async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/admin/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: adminPassword })
      });

      if (res.ok) {
        const data = await res.json();
        localStorage.setItem('admin_token', data.token);
        setAuthError("");
        onSuccess();
      } else {
        const error = await res.json();
        setAuthError(error.detail || "Login failed");
      }
    } catch (err) {
      console.error('Login error:', err);
      setAuthError("Login failed. Please try again.");
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-purple-200 via-blue-100 to-pink-100">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-purple-600 border-t-transparent"></div>
      </div>
    );
  }

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
          onKeyPress={e => e.key === 'Enter' && handleLogin()}
        />
        {authError && <div className="text-red-600 mt-2">{authError}</div>}
        <button
          className="mt-6 bg-purple-600 hover:bg-purple-700 text-white py-2 px-8 rounded-md text-lg"
          onClick={handleLogin}
        >
          Login
        </button>
        <button className="mt-2 text-gray-500 underline" onClick={onBack}>Back</button>
      </div>
    </div>
  );
}
