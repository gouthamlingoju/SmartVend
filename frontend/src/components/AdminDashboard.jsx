import React, { useState, useEffect } from 'react';
import FeedbackList from './FeedbackList';

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;

const statusReasons = {
  active: null,
  maintenance: 'Under maintenance',
  out_of_stock: 'Out of stock',
  offline: 'Machine offline',
};

export default function AdminDashboard({ machines, onLogout }) {
  const [activeTab, setActiveTab] = useState('machines');

  useEffect(() => {
    // Verify token periodically
    const interval = setInterval(async () => {
      const token = localStorage.getItem('admin_token');
      if (!token) {
        onLogout();
        return;
      }

      try {
        const res = await fetch(`${BACKEND_URL}/api/admin/verify`, {
          headers: {
            'Authorization': `Bearer ${token}`
          }
        });
        if (!res.ok) {
          localStorage.removeItem('admin_token');
          onLogout();
        }
      } catch (err) {
        console.error('Token verification failed:', err);
        localStorage.removeItem('admin_token');
        onLogout();
      }
    }, 60000); // Check every minute

    return () => clearInterval(interval);
  }, [onLogout]);
  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-100 via-purple-50 to-blue-100 p-8">
      <div className="max-w-6xl mx-auto">
        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold text-purple-800">Admin Dashboard</h1>
          <button onClick={() => {
            localStorage.removeItem('admin_token');
            onLogout();
          }} className="bg-purple-600 text-white px-4 py-2 rounded-lg">Logout</button>
        </div>

        <div className="bg-white rounded-xl shadow-lg p-4 mb-8">
          <div className="flex space-x-4 border-b">
            <button
              className={`px-4 py-2 font-medium ${
                activeTab === 'machines'
                  ? 'text-purple-600 border-b-2 border-purple-600'
                  : 'text-gray-500 hover:text-purple-600'
              }`}
              onClick={() => setActiveTab('machines')}
            >
              Machines
            </button>
            <button
              className={`px-4 py-2 font-medium ${
                activeTab === 'feedback'
                  ? 'text-purple-600 border-b-2 border-purple-600'
                  : 'text-gray-500 hover:text-purple-600'
              }`}
              onClick={() => setActiveTab('feedback')}
            >
              Feedback
            </button>
          </div>
        </div>

        {activeTab === 'machines' ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {machines.map(machine => (
            <div key={machine.machine_id} className="bg-white rounded-xl shadow p-6 border border-purple-100">
              <div className="font-bold text-lg text-purple-800 mb-1">{machine.location}</div>
              <div className="text-gray-500 text-sm mb-2">ID: {machine.machine_id}</div>
              <div className="mb-2">Status: <span className={machine.status === 'working' ? 'text-green-700' : 'text-red-600'}>{machine.status}</span></div>
              <div className="flex items-center justify-between mb-4">
                <div>Stock: <span className="font-semibold">{machine.current_stock}</span></div>
                <button
                  onClick={async () => {
                    const newStock = prompt("Enter new stock level after refill:", machine.current_stock);
                    if (newStock === null) return; // User cancelled
                    
                    const stockNum = parseInt(newStock);
                    if (isNaN(stockNum) || stockNum < 0) {
                      alert("Please enter a valid number (0 or greater)");
                      return;
                    }

                    try {
                      const token = localStorage.getItem('admin_token');
                      const res = await fetch(`${BACKEND_URL}/api/machine/${machine.machine_id}/update-stock`, {
                        method: 'POST',
                        headers: {
                          'Content-Type': 'application/json',
                          'Authorization': `Bearer ${token}`
                        },
                        body: JSON.stringify({ stock: stockNum })
                      });

                      if (!res.ok) {
                        const error = await res.json();
                        throw new Error(error.detail || 'Failed to update stock');
                      }

                      // Update local state
                      machine.current_stock = stockNum;
                      // Force re-render
                      setActiveTab(prev => prev);
                      alert('Stock updated successfully!');
                    } catch (err) {
                      console.error('Stock update failed:', err);
                      alert(err.message || 'Failed to update stock');
                    }
                  }}
                  className="bg-green-600 text-white px-3 py-1 rounded-lg text-sm hover:bg-green-700 transition-colors"
                >
                  Update Stock
                </button>
              </div>
              {machine.last_refill_at && (
                <div className="text-xs text-gray-500">
                  Last refill: {new Date(machine.last_refill_at).toLocaleString()}
                </div>
              )}
              <div className="mt-2 text-xs text-gray-400">(Transactions & stats coming soon)</div>
            </div>
          ))}
          </div>
        ) : (
          <FeedbackList />
        )}
      </div>
    </div>
  );
}
