

// FIX: architecture_review.md — "Unify Frontend Data Access"
// Replaced direct Supabase query with backend API call for machine listing.
import React, { useEffect, useState } from 'react';
import { BrowserRouter as Router, Routes, Route, useNavigate, useParams } from 'react-router-dom';
import VendingMachine from './VendingMachine';
import AdminDashboard from './components/AdminDashboard';
import Welcome from './components/Welcome';
import AdminLogin from './components/AdminLogin';
import MachineList from './components/MachineList';

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;

function AppRoutes() {
  const [machines, setMachines] = useState([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(null);
  const [adminAuth, setAdminAuth] = useState(false);
  const navigate = useNavigate();

  const fetchMachines = async () => {
    try {
      setFetchError(null);
      const res = await fetch(`${BACKEND_URL}/api/machines`);
      if (!res.ok) {
        throw new Error(`Failed to fetch machines (HTTP ${res.status})`);
      }
      const data = await res.json();
      // out_of_stock derivation now handled server-side
      setMachines(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error('Error fetching machines:', err);
      setFetchError(err.message || 'Failed to load machines');
      setMachines([]);
    }
  };

  useEffect(() => {
    setLoading(true);
    fetchMachines().finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="flex justify-center items-center min-h-screen text-xl">Loading machines...</div>;
  if (fetchError) return <div className="flex flex-col justify-center items-center min-h-screen text-xl text-red-600"><p>{fetchError}</p><button className="mt-4 bg-purple-600 text-white px-4 py-2 rounded" onClick={() => { setLoading(true); fetchMachines().finally(() => setLoading(false)); }}>Retry</button></div>;

  return (
    <Routes>
      <Route path="/" element={<Welcome onUser={() => navigate('/machines')} onAdmin={() => navigate('/admin-login')} />} />
      <Route path="/machines" element={<MachineList machines={machines} onSelect={machine => navigate(`/machine/${machine.machine_id}`)} onRefresh={fetchMachines} />} />
      <Route path="/machine/:machineId" element={<VendingMachineWrapper machines={machines} />} />
      <Route path="/admin-login" element={<AdminLogin onSuccess={() => { setAdminAuth(true); navigate('/admin'); }} onBack={() => navigate('/')} />} />
      <Route path="/admin" element={adminAuth ? <AdminDashboard machines={machines} onLogout={() => { setAdminAuth(false); navigate('/'); }} /> : <AdminLogin onSuccess={() => { setAdminAuth(true); navigate('/admin'); }} onBack={() => navigate('/')} />} />
      <Route path="*" element={<div className="min-h-screen flex items-center justify-center text-2xl">404 Not Found</div>} />
    </Routes>
  );
}

function VendingMachineWrapper({ machines }) {
  const navigate = useNavigate();
  const { machineId } = useParams();
  const machine = machines.find(m => m.machine_id === machineId);
  if (!machine) {
    return <div className="min-h-screen flex items-center justify-center text-2xl">Machine not found</div>;
  }
  return <VendingMachine machine={machine} onBack={() => navigate('/machines')} />;
}

export default function App() {
  return (
    <Router>
      <AppRoutes />
    </Router>
  );
}

