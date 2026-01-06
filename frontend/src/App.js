import React from 'react';
import { Routes, Route } from 'react-router-dom';
import './App.css';
import Terms from './Terms';
import Privacy from './Privacy';
import DeleteYourData from './DeleteYourData';
import Help from './Help';
import Login from './Login';
import AdminDashboard from './AdminDashboard';
import Pricing from './Pricing';
import ProtectedRoute from './components/auth/ProtectedRoute';
import LandingOrApp from './components/layout/LandingOrApp';
import AppRoutes from './routes/AppRoutes';
import NotFound from './components/common/NotFound';

/**
 * Main App component - routing only
 */
function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/pricing" element={<Pricing />} />
      <Route path="/terms" element={<Terms />} />
      <Route path="/privacy" element={<Privacy />} />
      <Route path="/delete-your-data" element={<DeleteYourData />} />
      <Route path="/help" element={<Help />} />
      <Route path="/" element={<LandingOrApp />} />
      <Route path="/app/*" element={<ProtectedRoute><AppRoutes /></ProtectedRoute>} />
      <Route path="/admin" element={<ProtectedRoute requireAdmin><AdminDashboard /></ProtectedRoute>} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

export default App;
