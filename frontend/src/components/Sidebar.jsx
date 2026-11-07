import React from 'react';
import { NavLink } from 'react-router-dom';
import './Sidebar.css';

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <NavLink to="/" className="sidebar-brand">
          <div className="brand-icon">Ω</div>
          <div>
            <div className="brand-title">Opsoria</div>
            <div className="brand-subtitle">Incident Intelligence</div>
          </div>
        </NavLink>
      </div>

      <nav className="sidebar-nav">
        <NavLink
          to="/dashboard"
          className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
        >
          <span className="nav-icon">📊</span>
          <span>Dashboard</span>
        </NavLink>

        <NavLink
          to="/analyze"
          className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
        >
          <span className="nav-icon">🔍</span>
          <span>Incident Analyzer</span>
        </NavLink>

        <NavLink
          to="/history"
          className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
        >
          <span className="nav-icon">📋</span>
          <span>History</span>
        </NavLink>

        <NavLink
          to="/memory"
          className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
        >
          <span className="nav-icon">🧠</span>
          <span>Memory Explorer</span>
        </NavLink>
      </nav>

      <div className="sidebar-footer">
        <div>Hindsight + Groq AI</div>
        <div className="env-tag">Engineered for SREs</div>
      </div>
    </aside>
  );
}

