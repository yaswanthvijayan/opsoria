import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { listIncidents } from '../api';
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

export default function HistoryPage() {
  const navigate = useNavigate();
  const [incidents, setIncidents] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState('');

  // Client-side filter controls
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all'); // 'all' | 'investigating' | 'resolved'
  const [hideSynthetic, setHideSynthetic] = useState(false);

  const fetchHistory = useCallback(async () => {
    setIsLoading(true);
    setErrorMessage('');
    try {
      const data = await listIncidents();
      setIncidents(Array.isArray(data) ? data : []);
    } catch (err) {
      setErrorMessage(err.message || 'Failed to fetch incident history.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  // Client-side filtering
  const filteredIncidents = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();

    return incidents.filter((inc) => {
      // 1. Synthetic filter
      if (hideSynthetic && inc.is_synthetic) {
        return false;
      }

      // 2. Status filter
      if (statusFilter !== 'all') {
        const normStatus = (inc.status || '').toLowerCase();
        if (normStatus !== statusFilter) {
          return false;
        }
      }

      // 3. Search query filter over incident_id, service, symptoms
      if (q) {
        const idMatch = (inc.incident_id || '').toLowerCase().includes(q);
        const serviceMatch = (inc.service || '').toLowerCase().includes(q);
        const symptomsMatch = (inc.symptoms || '').toLowerCase().includes(q);
        if (!idMatch && !serviceMatch && !symptomsMatch) {
          return false;
        }
      }

      return true;
    });
  }, [incidents, searchQuery, statusFilter, hideSynthetic]);

  if (isLoading && incidents.length === 0) {
    return (
      <div className="page-wrapper" style={{ textAlign: 'center', padding: '4rem 1rem' }}>
        <div style={{ fontSize: '2rem', marginBottom: '1rem' }}>⏳</div>
        <p style={{ color: 'var(--text-muted)' }}>Loading incident history...</p>
      </div>
    );
  }

  const totalCount = incidents.length;
  const filteredCount = filteredIncidents.length;

  return (
    <div className="page-wrapper">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '2rem', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h1>Incident History</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>
            Comprehensive log of all live and simulated incidents stored in the Opsoria database.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={fetchHistory}
            disabled={isLoading}
            title="Refresh history"
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
          <strong>Error loading history:</strong> {errorMessage}
        </div>
      )}

      {/* Filter and Search Controls */}
      <div className="filter-bar">
        <div className="search-input-wrapper">
          <input
            type="text"
            className="form-input"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by ID, service, or symptoms..."
          />
        </div>

        <div style={{ minWidth: '160px' }}>
          <select
            className="form-select"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="all">All Statuses</option>
            <option value="investigating">Investigating</option>
            <option value="resolved">Resolved</option>
          </select>
        </div>

        <div>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={hideSynthetic}
              onChange={(e) => setHideSynthetic(e.target.checked)}
            />
            <span>Hide synthetic test data</span>
          </label>
        </div>

        <div style={{ marginLeft: 'auto', fontSize: '0.825rem', color: 'var(--text-muted)' }}>
          Showing <strong>{filteredCount}</strong> of <strong>{totalCount}</strong> incidents
        </div>
      </div>

      {/* Table Card */}
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        {filteredCount > 0 ? (
          <div className="table-responsive">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Incident ID</th>
                  <th>Service</th>
                  <th>Environment</th>
                  <th>Status</th>
                  <th>Memory Status</th>
                  <th>Recorded</th>
                  <th style={{ textAlign: 'right' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {filteredIncidents.map((inc) => (
                  <tr
                    key={inc.incident_id}
                    className="clickable-row"
                    onClick={() => navigate(`/report/${encodeURIComponent(inc.incident_id)}`)}
                  >
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
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
                      <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                        {inc.environment}
                      </span>
                    </td>
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
          <div className="empty-state" style={{ margin: '2rem 1.5rem', border: 'none' }}>
            <div className="empty-state-icon">🔍</div>
            <h3>No matching incidents found</h3>
            <p style={{ marginBottom: '1.25rem' }}>
              {totalCount === 0
                ? 'No incidents have been recorded yet.'
                : 'No incidents match your current search and filter criteria.'}
            </p>
            {totalCount === 0 ? (
              <Link to="/analyze" className="btn btn-primary">
                Analyze New Incident →
              </Link>
            ) : (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => {
                  setSearchQuery('');
                  setStatusFilter('all');
                  setHideSynthetic(false);
                }}
              >
                Clear Filters
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

