import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { listIncidents } from '../api';

function isUUID(str) {
  if (!str || typeof str !== 'string') return false;
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(str.trim());
}

const COMMON_WORDS = new Set([
  'id', 'identifier', 'report', 'fact', 'record', 'with', 'in', 'on',
  'at', 'for', 'from', 'to', 'by', 'is', 'was', 'has', 'had', 'a',
  'an', 'the', 'during', 'caused', 'summary', 'details', 'data', 'test'
]);

/**
 * Derive prior incident ID from metadata.incident_id, else text regex.
 * Skips the item if neither matches. NEVER returns or displays a UUID.
 */
function extractPriorIncidentId(item) {
  if (!item) return null;

  // 1. metadata.incident_id (if not a UUID)
  const metaId = item.metadata?.incident_id;
  if (metaId && typeof metaId === 'string' && metaId.trim() && !isUUID(metaId.trim())) {
    return metaId.trim();
  }

  // 2. regex in text /Incident\s+([A-Za-z0-9._-]+)/
  if (item.text && typeof item.text === 'string') {
    const match = item.text.match(/\bIncident\s+([A-Za-z0-9._-]+)/i);
    if (match && match[1]) {
      const candidate = match[1].replace(/[.,:;]+$/, '').trim();
      if (
        candidate &&
        !COMMON_WORDS.has(candidate.toLowerCase()) &&
        /[0-9_-]/.test(candidate) &&
        !isUUID(candidate)
      ) {
        return candidate;
      }
    }
  }

  // 3. Fallback: non-UUID document_id (e.g. test environments)
  const docId = item.document_id;
  if (docId && typeof docId === 'string' && docId.trim() && !isUUID(docId.trim())) {
    return docId.trim();
  }

  // Else skip item. NEVER display a UUID!
  return null;
}

export default function MemoryExplorerPage() {
  const [incidents, setIncidents] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState('');
  const [filterQuery, setFilterQuery] = useState('');

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setErrorMessage('');
    try {
      const data = await listIncidents();
      setIncidents(Array.isArray(data) ? data : []);
    } catch (err) {
      setErrorMessage(err.message || 'Failed to load memory records.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Section A: Incidents with memory_status === 'persisted'
  const persistedIncidents = useMemo(() => {
    return incidents.filter((inc) => inc.memory_status === 'persisted');
  }, [incidents]);

  // Section B: Incidents with confirmed_resolution but memory_status === 'not_persisted'
  const notPersistedIncidents = useMemo(() => {
    return incidents.filter(
      (inc) =>
        Boolean(inc.confirmed_resolution && inc.confirmed_resolution.trim()) &&
        inc.memory_status === 'not_persisted'
    );
  }, [incidents]);

  // Section C: Aggregate historical_context across all stored last_analysis objects
  const recalledGroups = useMemo(() => {
    const groups = new Map();

    incidents.forEach((inc) => {
      const lastAnalysis = inc.last_analysis || {};
      const contextItems = Array.isArray(lastAnalysis.historical_context)
        ? lastAnalysis.historical_context
        : [];

      contextItems.forEach((item) => {
        const priorId = extractPriorIncidentId(item);
        if (!priorId) {
          // Skip item per requirements: NEVER display a UUID
          return;
        }

        if (!groups.has(priorId)) {
          groups.set(priorId, {
            priorIncidentId: priorId,
            records: [],
            analysesUsing: new Set(),
            isSynthetic: false,
          });
        }

        const grp = groups.get(priorId);
        grp.records.push(item);
        if (inc.incident_id) {
          grp.analysesUsing.add(inc.incident_id);
        }
        if (item.is_synthetic) {
          grp.isSynthetic = true;
        }
      });
    });

    return Array.from(groups.values()).map((g) => {
      const rawText = g.records[0]?.text || '';
      const cleanText = rawText.replace(/\n+/g, ' ').trim();
      const representativeText =
        cleanText.length > 200 ? cleanText.slice(0, 200) + '...' : cleanText;

      return {
        priorIncidentId: g.priorIncidentId,
        recordCount: g.records.length,
        analysesCount: g.analysesUsing.size,
        representativeText,
        isSynthetic: g.isSynthetic,
        fullRecords: g.records,
      };
    });
  }, [incidents]);

  // Filtered lists for free-text search (Sections A and C)
  const q = filterQuery.toLowerCase().trim();

  const filteredPersisted = useMemo(() => {
    if (!q) return persistedIncisted(persistedIncidents);
    return persistedIncidents.filter((inc) => {
      return (
        (inc.incident_id || '').toLowerCase().includes(q) ||
        (inc.service || '').toLowerCase().includes(q) ||
        (inc.symptoms || '').toLowerCase().includes(q) ||
        (inc.confirmed_resolution || '').toLowerCase().includes(q)
      );
    });
  }, [persistedIncidents, q]);

  function persistedIncisted(list) {
    return list;
  }

  const filteredRecalled = useMemo(() => {
    if (!q) return recalledGroups;
    return recalledGroups.filter((g) => {
      const matchId = g.priorIncidentId.toLowerCase().includes(q);
      const matchText = g.representativeText.toLowerCase().includes(q);
      const matchAny = g.fullRecords.some((r) =>
        (r.text || '').toLowerCase().includes(q)
      );
      return matchId || matchText || matchAny;
    });
  }, [recalledGroups, q]);

  if (isLoading && incidents.length === 0) {
    return (
      <div className="page-wrapper" style={{ textAlign: 'center', padding: '4rem 1rem' }}>
        <div style={{ fontSize: '2rem', marginBottom: '1rem' }}>⏳</div>
        <p style={{ color: 'var(--text-muted)' }}>Inspecting team memory bank...</p>
      </div>
    );
  }

  return (
    <div className="page-wrapper">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h1>Hindsight Memory Explorer</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>
            Audit persistent team memories, recalled historical incident patterns, and synchronization health.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={loadData}
          disabled={isLoading}
        >
          {isLoading ? '⏳ Refreshing...' : '🔄 Refresh Memory View'}
        </button>
      </div>

      {/* Safety Notice Banner */}
      <div className="alert alert-info" style={{ marginBottom: '1.5rem' }}>
        <span>ℹ️ <strong>Read-Only Audit:</strong> This page reads local records and makes no memory or AI calls.</span>
      </div>

      {errorMessage && (
        <div className="alert alert-error" style={{ marginBottom: '1.5rem' }}>
          <strong>Error loading memory records:</strong> {errorMessage}
        </div>
      )}

      {/* Search Filter Box */}
      <div className="filter-bar">
        <div className="search-input-wrapper">
          <input
            type="text"
            className="form-input"
            value={filterQuery}
            onChange={(e) => setFilterQuery(e.target.value)}
            placeholder="Filter saved memories and recalled history by keyword, ID, service, or resolution..."
          />
        </div>
        {filterQuery && (
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => setFilterQuery('')}
            style={{ padding: '0.4rem 0.75rem', fontSize: '0.8rem' }}
          >
            Clear Search
          </button>
        )}
      </div>

      {/* Section D: Memory Integrity Legend Card */}
      <div className="card" style={{ marginBottom: '2rem', background: 'var(--bg-surface)' }}>
        <div className="card-header">
          <h3 className="card-title">
            <span>🛡️</span> Memory Integrity Architecture
          </h3>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem', padding: '0.75rem', background: 'var(--color-success-bg)', border: '1px solid var(--color-success-border)', borderRadius: 'var(--radius-md)' }}>
            <span className="badge badge-persisted" style={{ whiteSpace: 'nowrap', marginTop: '0.1rem' }}>
              Green &bull; Saved
            </span>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              <strong style={{ color: '#34d399' }}>Engineer-Confirmed & Saved:</strong> Production resolution verified by a human engineer and durably persisted to Hindsight Cloud memory for future recall.
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem', padding: '0.75rem', background: 'var(--color-warning-bg)', border: '1px solid var(--color-warning-border)', borderRadius: 'var(--radius-md)' }}>
            <span className="badge badge-confidence-medium" style={{ whiteSpace: 'nowrap', marginTop: '0.1rem' }}>
              Amber &bull; Unverified
            </span>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              <strong style={{ color: '#fbbf24' }}>AI Hypotheses (Never Saved):</strong> Diagnostic suggestions generated by Groq LLM. Strictly unverified and NEVER saved into the durable memory bank.
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem', padding: '0.75rem', background: 'var(--color-danger-bg)', border: '1px solid var(--color-danger-border)', borderRadius: 'var(--radius-md)' }}>
            <span className="badge badge-synthetic" style={{ whiteSpace: 'nowrap', marginTop: '0.1rem' }}>
              Red &bull; Warning
            </span>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              <strong style={{ color: '#f87171' }}>Synthetic Test Data or Save Failure:</strong> Simulated testing drill records or confirmed resolutions that could not be retained due to offline status.
            </div>
          </div>
        </div>
      </div>

      {/* Section A: Saved to Team Memory */}
      <div style={{ marginBottom: '2.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.5rem' }}>
          <div>
            <h2>Section A: Saved to Team Memory</h2>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
              Incidents with confirmed resolutions successfully persisted to the Hindsight memory bank.
            </p>
          </div>
          <span className="badge badge-resolved">
            {filteredPersisted.length} Saved {filteredPersisted.length === 1 ? 'Incident' : 'Incidents'}
          </span>
        </div>

        {filteredPersisted.length > 0 ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '1.25rem' }}>
            {filteredPersisted.map((inc) => (
              <div
                key={inc.incident_id}
                className="card"
                style={{
                  margin: 0,
                  display: 'flex',
                  flexDirection: 'column',
                  borderColor: 'var(--color-success-border)',
                }}
              >
                <div className="card-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                    <span className="mono" style={{ fontWeight: 700, color: 'var(--text-primary)' }}>
                      {inc.incident_id}
                    </span>
                    <span className="badge badge-persisted">
                      ✓ Engineer-confirmed
                    </span>
                    {inc.is_synthetic && (
                      <span className="badge badge-synthetic">
                        SYNTHETIC TEST DATA
                      </span>
                    )}
                  </div>
                  <Link
                    to={`/report/${encodeURIComponent(inc.incident_id)}`}
                    style={{ fontSize: '0.8rem', whiteSpace: 'nowrap' }}
                  >
                    Report →
                  </Link>
                </div>

                <div style={{ display: 'flex', gap: '1rem', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '0.75rem' }}>
                  <span>Service: <strong className="mono" style={{ color: 'var(--text-secondary)' }}>{inc.service}</strong></span>
                  <span>Env: <strong style={{ color: 'var(--text-secondary)' }}>{inc.environment}</strong></span>
                </div>

                <div style={{ marginBottom: '0.75rem' }}>
                  <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '0.2rem' }}>
                    Symptoms
                  </div>
                  <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.4, margin: 0 }}>
                    {inc.symptoms}
                  </p>
                </div>

                <div style={{ marginTop: 'auto', paddingTop: '0.75rem', borderTop: '1px solid var(--border-subtle)' }}>
                  <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', color: '#34d399', fontWeight: 600, marginBottom: '0.25rem' }}>
                    Durable Fix in Memory
                  </div>
                  <div style={{ background: 'var(--bg-surface-elevated)', padding: '0.6rem 0.75rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
                    <p style={{ fontSize: '0.85rem', color: 'var(--text-primary)', margin: 0, lineHeight: 1.5, whiteSpace: 'pre-line' }}>
                      {inc.confirmed_resolution}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <div className="empty-state-icon">🌱</div>
            <h3>No saved team memories yet</h3>
            <p>
              When an engineer confirms an incident resolution, it is persisted to Hindsight and appears here.
            </p>
          </div>
        )}
      </div>

      {/* Section B: Not Saved (Retention Failures or Offline) */}
      {notPersistedIncidents.length > 0 && (
        <div style={{ marginBottom: '2.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.5rem' }}>
            <div>
              <h2 style={{ color: '#f87171' }}>Section B: Not Saved to Memory Bank</h2>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                Incidents confirmed locally by an engineer but where memory persistence failed or Hindsight was offline.
              </p>
            </div>
            <span className="badge badge-not-persisted">
              {notPersistedIncidents.length} Persistence Warning
            </span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {notPersistedIncidents.map((inc) => (
              <div
                key={inc.incident_id}
                className="card"
                style={{
                  margin: 0,
                  borderColor: 'var(--color-danger-border)',
                  background: 'rgba(239, 68, 68, 0.04)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem', flexWrap: 'wrap', gap: '0.5rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span className="mono" style={{ fontWeight: 700, color: 'var(--text-primary)' }}>
                      {inc.incident_id}
                    </span>
                    <span className="mono" style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                      ({inc.service})
                    </span>
                  </div>
                  <Link to={`/report/${encodeURIComponent(inc.incident_id)}`} style={{ fontSize: '0.8rem' }}>
                    View Incident Report →
                  </Link>
                </div>

                <div className="alert alert-error" style={{ marginBottom: '0.75rem', padding: '0.5rem 0.75rem' }}>
                  ⚠️ Resolution confirmed but could NOT be saved to memory.
                </div>

                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                  <strong>Confirmed resolution:</strong> {inc.confirmed_resolution}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Section C: What the System Recalled */}
      <div style={{ marginBottom: '2.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.5rem' }}>
          <div>
            <h2>Section C: What the System Recalled</h2>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
              Historical context patterns retrieved from the memory bank during previous incident analyses.
            </p>
          </div>
          <span className="badge badge-neutral">
            {filteredRecalled.length} Prior {filteredRecalled.length === 1 ? 'Pattern' : 'Patterns'}
          </span>
        </div>

        {filteredRecalled.length > 0 ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '1.25rem' }}>
            {filteredRecalled.map((g) => (
              <div
                key={g.priorIncidentId}
                className="card"
                style={{
                  margin: 0,
                  display: 'flex',
                  flexDirection: 'column',
                  background: 'var(--bg-surface-elevated)',
                }}
              >
                <div className="card-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span className="mono" style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                      Prior Incident: {g.priorIncidentId}
                    </span>
                    {g.isSynthetic && (
                      <span className="badge badge-synthetic">SYNTHETIC</span>
                    )}
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '1.25rem', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '0.75rem' }}>
                  <div>
                    Recalled records: <strong style={{ color: 'var(--text-primary)' }}>{g.recordCount}</strong>
                  </div>
                  <div>
                    Used in: <strong style={{ color: 'var(--text-primary)' }}>{g.analysesCount}</strong> {g.analysesCount === 1 ? 'analysis' : 'analyses'}
                  </div>
                </div>

                <div style={{ marginTop: 'auto', background: 'var(--bg-primary)', padding: '0.75rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-default)' }}>
                  <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>
                    Representative Recall Observation
                  </div>
                  <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.5, margin: 0 }}>
                    {g.representativeText}
                  </p>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <div className="empty-state-icon">📡</div>
            <h3>No recalled memory records</h3>
            <p>
              When incident analyses trigger memory recall against Hindsight, retrieved patterns will appear grouped here.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

