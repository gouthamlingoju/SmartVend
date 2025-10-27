

import React, { useEffect, useState } from 'react';
import { BrowserRouter as Router, Routes, Route, useNavigate, useParams } from 'react-router-dom';
import VendingMachine from './VendingMachine';
import supabase from './supabase';
import AdminDashboard from './components/AdminDashboard';
import Welcome from './components/Welcome';
import AdminLogin from './components/AdminLogin';
import MachineList from './components/MachineList';

function AppRoutes() {
  const [machines, setMachines] = useState([]);
  const [loading, setLoading] = useState(true);
  const [adminAuth, setAdminAuth] = useState(false);

  useEffect(() => {
    async function fetchMachines() {
      const { data, error } = await supabase
        .from('machines')
        .select('*');
      if (error) {
        console.error('Error fetching machines:', error);
        setLoading(false);
        return;
      }
      setMachines(data.map(m => {
        if (m.status === 'working' && m.current_stock <= 0) {
          return { ...m, status: 'out_of_stock' };
        }
        return m;
      }));
      setLoading(false);
    }
    fetchMachines();
  }, []);

  const navigate = useNavigate();

  if (loading) return <div className="flex justify-center items-center min-h-screen text-xl">Loading machines...</div>;

  return (
    <Routes>
      <Route path="/" element={<Welcome onUser={() => navigate('/machines')} onAdmin={() => navigate('/admin-login')} />} />
      <Route path="/machines" element={<MachineList machines={machines} onSelect={machine => navigate(`/machine/${machine.machine_id}`)} />} />
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
