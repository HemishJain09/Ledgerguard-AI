import React from 'react';
import { NavLink } from 'react-router-dom';
import { LayoutDashboard, AlertCircle, FileText, Settings, ShieldCheck } from 'lucide-react';
import './Sidebar.css';

const Sidebar = () => {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <ShieldCheck className="brand-icon" size={28} />
        <span className="brand-name">Ledger Guard</span>
      </div>
      <nav className="sidebar-nav">
        <div className="nav-section">
          <span className="nav-label">RECONCILIATION</span>
          <NavLink to="/dashboard" className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}>
            <LayoutDashboard size={18} />
            Overview
          </NavLink>
          <NavLink to="/exceptions" className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}>
            <AlertCircle size={18} />
            Ingestion Interrupts
          </NavLink>
          <NavLink to="/recon-exceptions" className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}>
            <AlertCircle size={18} />
            AI Forensic Queue
            <span className="nav-badge">3</span>
          </NavLink>
          <NavLink to="/reports" className="nav-item disabled">
            <FileText size={18} />
            Audit Reports
          </NavLink>
        </div>
      </nav>
      <div className="sidebar-footer">
        <NavLink to="/settings" className="nav-item disabled">
          <Settings size={18} />
          Settings
        </NavLink>
      </div>
    </aside>
  );
};

export default Sidebar;
