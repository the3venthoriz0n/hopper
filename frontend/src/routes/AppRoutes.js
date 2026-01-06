import React from 'react';
import { Routes, Route } from 'react-router-dom';
import Home from '../components/home/Home';

/**
 * App routes component - nested routes for authenticated app section
 * @param {object} props
 */
export default function AppRoutes({ user, isAdmin, setUser, authLoading }) {
  return (
    <Routes>
      <Route index element={<Home user={user} isAdmin={isAdmin} setUser={setUser} authLoading={authLoading} />} />
      <Route path="subscription" element={<Home user={user} isAdmin={isAdmin} setUser={setUser} authLoading={authLoading} />} />
      <Route path="subscription/success" element={<Home user={user} isAdmin={isAdmin} setUser={setUser} authLoading={authLoading} />} />
    </Routes>
  );
}

