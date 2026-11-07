import React, { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import DashboardPage from './pages/DashboardPage';
import AnalyzerPage from './pages/AnalyzerPage';
import ReportPage from './pages/ReportPage';
import HistoryPage from './pages/HistoryPage';
import MemoryExplorerPage from './pages/MemoryExplorerPage';
import { checkHealth, API_BASE } from './api';

export default function App() {
  const [isBackendHealthy, setIsBackendHealthy] = useState(true);
  const [backendCheckDone, setBackendCheckDone] = useState(false);

  useEffect(() => {
    let mounted = true;
    async function verifyBackend() {
      try {
        await checkHealth();
        if (mounted) setIsBackendHealthy(true);
      } catch {
        if (mounted) setIsBackendHealthy(false);
      } finally {
        if (mounted) setBackendCheckDone(true);
      }
    }
    verifyBackend();

    // Check periodically every 30 seconds
    const interval = setInterval(verifyBackend, 30000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  return (
    <BrowserRouter>
      <div className="app-container">
        <Sidebar />

        <div className="main-content">
          {backendCheckDone && !isBackendHealthy && (
            <div className="backend-banner no-print">
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span>⚠️</span>
                <span>
                  <strong>Backend unreachable:</strong> Cannot connect to the Opsoria API server at{' '}
                  <code className="mono">{API_BASE}</code>. Ensure the backend is running.
                </span>
              </div>
              <button
                type="button"
                className="btn btn-secondary"
                style={{ padding: '0.2rem 0.6rem', fontSize: '0.75rem' }}
                onClick={async () => {
                  try {
                    await checkHealth();
                    setIsBackendHealthy(true);
                  } catch {
                    setIsBackendHealthy(false);
                  }
                }}
              >
                🔄 Recheck
              </button>
            </div>
          )}

          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/analyze" element={<AnalyzerPage />} />
            <Route path="/report/:incident_id" element={<ReportPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/memory" element={<MemoryExplorerPage />} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  );
}

