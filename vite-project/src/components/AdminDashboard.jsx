import React, { useState } from 'react';
import FeedbackList from './FeedbackList';

const statusReasons = {
  active: null,
  maintenance: 'Under maintenance',
  out_of_stock: 'Out of stock',
  offline: 'Machine offline',
};

export default function AdminDashboard({ machines, onLogout }) {
  const [activeTab, setActiveTab] = useState('machines');
  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-100 via-purple-50 to-blue-100 p-8">
      <div className="max-w-6xl mx-auto">
        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold text-purple-800">Admin Dashboard</h1>
          <button onClick={onLogout} className="bg-purple-600 text-white px-4 py-2 rounded-lg">Logout</button>
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
              <div>Stock: <span className="font-semibold">{machine.current_stock}</span></div>
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
