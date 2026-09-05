import React from 'react';
import { Bell, Search, UserCircle } from 'lucide-react';
import './Header.css';

const Header = () => {
  return (
    <header className="header">
      <div className="header-search">
        <Search size={18} className="search-icon" />
        <input type="text" placeholder="Search accounts, invoices, or transactions..." />
      </div>
      <div className="header-actions">
        <button className="icon-btn">
          <Bell size={20} />
          <span className="notification-dot"></span>
        </button>
        <div className="user-profile">
          <UserCircle size={32} />
          <div className="user-info">
            <span className="user-name">Hemish Jain</span>
            <span className="user-role">Finance Admin</span>
          </div>
        </div>
      </div>
    </header>
  );
};

export default Header;
