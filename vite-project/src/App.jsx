import React, { useEffect, useState } from 'react'
import VendingMachine from './VendingMachine';

const statusReasons = {
  active: null,
  maintenance: 'Under maintenance',
  out_of_stock: 'Out of stock',
  offline: 'Machine offline',
};

function AdminDashboard({ machines, onLogout }) {
  // Placeholder for stats and transactions
  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-100 via-purple-50 to-blue-100 p-8">
      <div className="max-w-5xl mx-auto">
        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold text-purple-800">Admin Dashboard</h1>
          <button onClick={onLogout} className="bg-purple-600 text-white px-4 py-2 rounded-lg">Logout</button>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {machines.map(machine => (
            <div key={machine.id} className="bg-white rounded-xl shadow p-6 border border-purple-100">
              <div className="font-bold text-lg text-purple-800 mb-1">{machine.location}</div>
              <div className="text-gray-500 text-sm mb-2">ID: {machine.id}</div>
              <div className="mb-2">Status: <span className={machine.status === 'active' ? 'text-green-700' : 'text-red-600'}>{machine.status}</span></div>
              <div>Stock: <span className="font-semibold">{machine.stock}</span></div>
              {/* Placeholder for stats/transactions */}
              <div className="mt-2 text-xs text-gray-400">(Transactions & stats coming soon)</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function App() {
  const [machines, setMachines] = useState([]);
  const [selectedMachine, setSelectedMachine] = useState(null);
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState(null); // 'user' or 'admin'
  const [adminAuth, setAdminAuth] = useState(false);
  const [adminPassword, setAdminPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    fetch('/machines.json')
      .then(res => res.json())
      .then(data => {
        setMachines(data.map(m => {
          if (m.status === 'active' && m.stock <= 0) {
            return { ...m, status: 'out_of_stock' };
          }
          return m;
        }));
        setLoading(false);
      });
  }, []);

  if (loading) return <div className="flex justify-center items-center min-h-screen text-xl">Loading machines...</div>;

  if (!mode) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-gradient-to-br from-purple-200 via-blue-100 to-pink-100">
        <div className="bg-white rounded-2xl shadow-lg p-10 flex flex-col items-center">
          <h1 className="text-3xl font-bold text-purple-700 mb-8">Welcome to SmartVend</h1>
          <div className="flex gap-8">
            <button className="bg-purple-600 hover:bg-purple-700 text-white px-8 py-4 rounded-lg text-xl font-semibold" onClick={() => setMode('user')}>User</button>
            <button className="bg-gray-700 hover:bg-gray-800 text-white px-8 py-4 rounded-lg text-xl font-semibold" onClick={() => setMode('admin')}>Admin</button>
          </div>
        </div>
      </div>
    );
  }

  if (mode === 'admin' && !adminAuth) {
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
                setAdminAuth(true);
                setAuthError("");
              } else {
                setAuthError("Incorrect password");
              }
            }}
          >Login</button>
          <button className="mt-2 text-gray-500 underline" onClick={() => setMode(null)}>Back</button>
        </div>
      </div>
    );
  }

  if (mode === 'admin' && adminAuth) {
    return <AdminDashboard machines={machines} onLogout={() => { setAdminAuth(false); setMode(null); setAdminPassword(""); }} />;
  }

  // User mode
  if (!selectedMachine) {
    const filteredMachines = machines.filter(machine =>
      machine.location.toLowerCase().includes(search.toLowerCase()) ||
      machine.id.toLowerCase().includes(search.toLowerCase())
    );
    return (
      <div className="min-h-screen bg-gradient-to-br from-purple-200 via-blue-100 to-pink-100 p-8">
        <div className="max-w-4xl mx-auto">
          <h1 className="text-3xl font-bold text-center mb-8 text-purple-700 drop-shadow">Select a Vending Machine</h1>
          <div className="flex justify-center mb-6">
            <input
              type="text"
              placeholder="Search by location or ID..."
              className="w-full max-w-md px-4 py-2 border border-purple-200 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-purple-400"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-8">
            {filteredMachines.map(machine => {
              const reason = statusReasons[machine.status] || (machine.status === 'out_of_stock' ? 'Out of stock' : 'Not available');
              const isActive = machine.status === 'active';
              return (
                <button
                  key={machine.id}
                  className={`bg-white rounded-xl shadow-lg p-6 flex flex-col items-center border-2 transition relative min-h-48 ${isActive ? 'border-purple-100 hover:border-purple-400' : 'border-gray-200 opacity-60 cursor-not-allowed'}`}
                  onClick={() => isActive ? setSelectedMachine(machine) : null}
                  disabled={!isActive}
                  style={{background: isActive ? 'linear-gradient(135deg, #f3e8ff 0%, #e0e7ff 100%)' : '#f8fafc'}}
                >
                  <img src="/logo.png" alt="Machine" className="h-14 w-14 mb-3" />
                  <div className="font-bold text-lg text-purple-800 mb-1">{machine.location}</div>
                  <div className="text-gray-500 text-sm mb-2">ID: {machine.id}</div>
                  {isActive ? (
                    <div className="text-green-700 font-semibold">Available</div>
                  ) : (
                    <div className="text-red-600 font-semibold">{reason}</div>
                  )}
                </button>
              );
            })}
            {filteredMachines.length === 0 && (
              <div className="col-span-full text-center text-gray-500">No machines found.</div>
            )}
          </div>
        </div>
      </div>
    );
  }

  return <VendingMachine machine={selectedMachine} onBack={() => setSelectedMachine(null)} />;
}

export default App
