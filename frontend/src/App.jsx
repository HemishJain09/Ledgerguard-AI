import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import Layout from './layouts/Layout';
import Dashboard from './pages/Dashboard';
import ExceptionsQueue from './pages/ExceptionsQueue';
import ReconExceptions from './pages/ReconExceptions';

function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="exceptions" element={<ExceptionsQueue />} />
        <Route path="recon-exceptions" element={<ReconExceptions />} />
      </Route>
    </Routes>
  );
}

export default App;
