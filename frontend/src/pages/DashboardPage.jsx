import React, { useState, useEffect, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getStats, listIncidents } from '../api';
import StatusBadge from '../components/StatusBadge';
import MemoryStatusBadge from '../components/MemoryStatusBadge';

function formatDate(isoString) {
  if (!isoString) return '—';
  try {
    const d = new Date(isoString);
    return isNaN(d.getTime()) ? isoString : d.toLocaleString();
  } catch {
    return isoString;
  }
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const [stats, setStats] = useState(null);
  const [incidents, setIncidents] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState('');

  const loadDashboardData = useCallback(async () => {
    setIsLoading(true);
    setErrorMessage('');
    try {
      const [statsData, incidentsData] = await Promise.all([
        getStats(),
        listIncidents(),
      ]);
      setStats(statsData);
      setIncidents(Array.isArray(incidentsData) ? incidentsData : []);
    } catch (err) {
      setErrorMessage(err.message || 'Failed to load dashboard metrics.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDashboardData();
  }, [loadDashboardData]);

  // Compute honest memory numbers client-side from incidents list
  const verifiedProductionLearnings = incidents.filter(
    (inc) => inc.memory_status === 'persisted' && !inc.is_synthetic
  ).length;

  const syntheticRecordsInMemory = incidents.filter(
    (inc) => inc.memory_status === 'persisted' && inc.is_synthetic
  ).length;

  // Compute status distribution percentages
  const total = stats?.total || 0;
  const investigatingCount = stats?.by_status?.investigating || 0;
  const resolvedCount = stats?.resolved_count || stats?.by_status?.resolved || 0;
  const otherCount = Math.max(0, total - (investigatingCount + resolvedCount));

  const investigatingPct = total > 0 ? (investigatingCount / total) * 100 : 0;
  const resolvedPct = total > 0 ? (resolvedCount / total) * 100 : 0;
  const otherPct = total > 0 ? (otherCount / total) * 100 : 0;

  if (isLoading && !stats) {
    return (
      <div className="page-wrapper" style={{ textAlign: 'center', padding: '4rem 1rem' }}>
        <div style={{ fontSize: '2rem', marginBottom: '1rem' }}>⏳</div>
        <p style={{ color: 'var(--text-muted)' }}>Loading reliability metrics...</p>
      </div>
    );
  }

  if (errorMessage && !stats) {
    return (
      <div className="page-wrapper">
        <div className="alert alert-error">
          <strong>Error loading dashboard:</strong> {errorMessage}
        </div>
        <button type="button" className="btn btn-secondary" onClick={loadDashboardData}>
          🔄 Retry
        </button>
      </div>
    );
  }

  const recentIncidents = stats?.recent_incidents || [];
  const hasIncidents = total > 0 || recentIncidents.length > 0;

  return (
    <div className="page-wrapper">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '2rem', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h1>Incident Dashboard</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>
            System reliability overview, resolution tracking, and durable team memory metrics.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={loadDashboardData}
            disabled={isLoading}
            title="Refresh dashboard data"
          >
            {isLoading ? '⏳ Refreshing...' : '🔄 Refresh'}
          </button>
          <Link to="/analyze" className="btn btn-primary">
            + Ingest Incident
          </Link>
        </div>
      </div>

      {errorMessage && (
        <div className="alert alert-error" style={{ marginBottom: '1.5rem' }}>
          <strong>Error refreshing data:</strong> {errorMessage}
        </div>
      )}

      {/* Stat Cards from GET /stats */}
      <div className="stat-grid">
        <div className="stat-card">
          <span className="stat-title">Total Incidents</span>
          <span className="stat-value">{stats?.total ?? 0}</span>
          <span className="stat-subtext">All time recorded</span>
        </div>

        <div className="stat-card">
          <span className="stat-title">Investigating</span>
          <span className="stat-value" style={{ color: '#60a5fa' }}>
            {investigatingCount}
          </span>
          <span className="stat-subtext">Active investigations</span>
        </div>

        <div className="stat-card stat-success">
          <span className="stat-title">Resolved</span>
          <span className="stat-value">{resolvedCount}</span>
          <span className="stat-subtext">Engineer verified fixes</span>
        </div>

        <div className="stat-card stat-success">
          <span className="stat-title">Saved to Memory</span>
          <span className="stat-value">{stats?.persisted_count ?? 0}</span>
          <span className="stat-subtext">Persisted to Hindsight</span>
        </div>

        <div className={`stat-card ${(stats?.not_persisted_count || 0) > 0 ? 'stat-danger' : ''}`}>
          <span className="stat-title">Not Saved</span>
          <span className="stat-value">{stats?.not_persisted_count ?? 0}</span>
          <span className="stat-subtext">Offline or save failed</span>
        </div>

        <div className="stat-card">
          <span className="stat-title">Synthetic Records</span>
          <span className="stat-value" style={{ color: '#f87171' }}>
            {stats?.synthetic_count ?? 0}
          </span>
          <span className="stat-subtext">Testing & drill data</span>
        </div>
      </div>

      {/* Honest Memory Numbers Card */}
      <div className="card" style={{ borderColor: 'var(--border-subtle)', background: 'linear-gradient(180deg, var(--bg-surface) 0%, rgba(31, 41, 55, 0.4) 100%)' }}>
        <div className="card-header">
          <h3 className="card-title">
            <span>🧠</span> Durable Team Memory Breakdown
          </h3>
          <span className="badge badge-neutral">Client-Side Verified</span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '1.25rem', marginBottom: '1rem' }}>
          <div style={{ padding: '1rem', background: 'var(--color-success-bg)', border: '1px solid var(--color-success-border)', borderRadius: 'var(--radius-md)' }}>
            <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#34d399', textTransform: 'uppercase', marginBottom: '0.25rem' }}>
              Verified Production Learnings
            </div>
            <div className="mono" style={{ fontSize: '2rem', fontWeight: 700, color: '#34d399' }}>
              {verifiedProductionLearnings}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
              Confirmed production incident fixes in memory bank
            </div>
          </div>

          <div style={{ padding: '1rem', background: 'var(--color-danger-bg)', border: '1px solid var(--color-danger-border)', borderRadius: 'var(--radius-md)' }}>
            <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#f87171', textTransform: 'uppercase', marginBottom: '0.25rem' }}>
              Synthetic Test Records in Memory
            </div>
            <div className="mono" style={{ fontSize: '2rem', fontWeight: 700, color: '#f87171' }}>
              {syntheticRecordsInMemory}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
              Explicitly labelled testing & simulation records
            </div>
          </div>
        </div>

        <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', margin: 0 }}>
          💡 <strong>Integrity Guarantee:</strong> Only engineer-confirmed resolutions are saved to memory; AI hypotheses never are.
        </p>
      </div>

      {/* Status Distribution Bars */}
      <div className="card">
        <div className="card-header">
          <h3 className="card-title">
            <span>📈</span> Status Distribution
          </h3>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            {total} incident{total === 1 ? '' : 's'} recorded
          </span>
        </div>

        {total > 0 ? (
          <div>
            <div className="dist-bar-container">
              {investigatingPct > 0 && (
                <div
                  className="dist-bar-segment"
                  style={{ width: `${investigatingPct}%`, backgroundColor: '#3b82f6' }}
                  title={`Investigating: ${investigatingCount} (${investigatingPct.toFixed(1)}%)`}
                />
              )}
              {resolvedPct > 0 && (
                <div
                  className="dist-bar-segment"
                  style={{ width: `${resolvedPct}%`, backgroundColor: '#10b981' }}
                  title={`Resolved: ${resolvedCount} (${resolvedPct.toFixed(1)}%)`}
                />
              )}
              {otherPct > 0 && (
                <div
                  className="dist-bar-segment"
                  style={{ width: `${otherPct}%`, backgroundColor: '#6b7280' }}
                  title={`Other: ${otherCount} (${otherPct.toFixed(1)}%)`}
                />
              )}
            </div>

            <div className="dist-legend">
              <div className="dist-legend-item">
                <span className="dist-dot" style={{ backgroundColor: '#3b82f6' }} />
                <span>Investigating ({investigatingCount} &bull; {investigatingPct.toFixed(0)}%)</span>
              </div>
              <div className="dist-legend-item">
                <span className="dist-dot" style={{ backgroundColor: '#10b981' }} />
                <span>Resolved ({resolvedCount} &bull; {resolvedPct.toFixed(0)}%)</span>
              </div>
              {otherCount > 0 && (
                <div className="dist-legend-item">
                  <span className="dist-dot" style={{ backgroundColor: '#6b7280' }} />
                  <span>Other ({otherCount} &bull; {otherPct.toFixed(0)}%)</span>
                </div>
              )}
            </div>
          </div>
        ) : (
          <p style={{ color: 'var(--text-muted)', margin: 0 }}>No incidents recorded yet.</p>
        )}
      </div>

      {/* Recent Incidents Table */}
      <div className="card">
        <div className="card-header">
          <h3 className="card-title">
            <span>🕒</span> Recent Incidents
          </h3>
          <Link to="/history" style={{ fontSize: '0.85rem' }}>
            View all history →
          </Link>
        </div>

        {hasIncidents && recentIncidents.length > 0 ? (
          <div className="table-responsive">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Incident ID</th>
                  <th>Service</th>
                  <th>Status</th>
                  <th>Memory Status</th>
                  <th>Recorded</th>
                  <th style={{ textAlign: 'right' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {recentIncidents.map((inc) => (
                  <tr
                    key={inc.incident_id}
                    className="clickable-row"
                    onClick={() => navigate(`/report/${encodeURIComponent(inc.incident_id)}`)}
                  >
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span className="mono" style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                          {inc.incident_id}
                        </span>
                        {inc.is_synthetic && (
                          <span className="badge badge-synthetic">SYNTHETIC</span>
                        )}
                      </div>
                    </td>
                    <td className="mono">{inc.service}</td>
                    <td>
                      <StatusBadge status={inc.status} />
                    </td>
                    <td>
                      <MemoryStatusBadge memoryStatus={inc.memory_status} />
                    </td>
                    <td style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                      {formatDate(inc.created_at)}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <Link
                        to={`/report/${encodeURIComponent(inc.incident_id)}`}
                        className="btn btn-secondary"
                        style={{ padding: '0.25rem 0.65rem', fontSize: '0.75rem' }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        Report →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state">
            <div className="empty-state-icon">📋</div>
            <h3>No incidents yet</h3>
            <p style={{ marginBottom: '1.25rem' }}>
              Analyze a new incident or load a synthetic test drill to start building memory.
            </p>
            <Link to="/analyze" className="btn btn-primary">
              Analyze New Incident →
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}

