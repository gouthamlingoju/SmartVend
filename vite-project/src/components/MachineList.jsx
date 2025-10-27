import React, { useState } from 'react';

import { useNavigate } from 'react-router-dom';

export default function MachineList({ machines, onSelect }) {
  const [search, setSearch] = useState("");
  const navigate = useNavigate();
  const filteredMachines = machines.filter(machine => {
    const location = machine.location || '';
    const id = machine.id || machine.machine_id || '';
    return (
      location.toLowerCase().includes(search.toLowerCase()) ||
      id.toLowerCase().includes(search.toLowerCase())
    );
  });
  const statusReasons = {
    active: null,
    maintenance: 'Under maintenance',
    out_of_stock: 'Out of stock',
    offline: 'Machine offline',
  };
  return (
    <div className="min-h-screen bg-gradient-to-br from-purple-200 via-blue-100 to-pink-100 p-8">
        <button
          className="mb-6 bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-lg transition-colors duration-200 shadow-md flex items-center space-x-2"
          onClick={() => navigate('/')}
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 mr-2" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M7.707 14.707a1 1 0 01-1.414 0l-5-5a1 1 0 010-1.414l5-5a1 1 0 111.414 1.414L4.414 8H17a1 1 0 110 2H4.414l3.293 3.293a1 1 0 010 1.414z" clipRule="evenodd" />
          </svg>
          <span>Back</span>
        </button>
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
            const machineKey = machine.machine_id || machine.id || machine.machineId || 'unknown';
            const displayId = machine.machine_id || machine.id || 'N/A';
            const isActive = (machine.status === 'working') || (machine.status === 'active'); // accept both
            return (
              <button
                key={machineKey}
                className={`bg-white rounded-xl shadow-lg p-6 flex flex-col items-center border-2 transition relative min-h-48 ${isActive ? 'border-purple-100 hover:border-purple-400' : 'border-gray-200 opacity-60 cursor-not-allowed'}`}
                onClick={() => isActive ? onSelect(machine) : null}
                disabled={!isActive}
                style={{background: isActive ? 'linear-gradient(135deg, #f3e8ff 0%, #e0e7ff 100%)' : '#f8fafc'}}
              >
                <img src="/logo.png" alt="Machine" className="h-14 w-14 mb-3" />
                <div className="font-bold text-lg text-purple-800 mb-1">{machine.location}</div>
                <div className="text-gray-500 text-sm mb-2">ID: {displayId}</div>
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
