import React, { useState, useEffect, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getIncident, resolveIncident } from '../api';
import StatusBadge from '../components/StatusBadge';
import MemoryStatusBadge from '../components/MemoryStatusBadge';
import SummaryStepsCard from '../components/SummaryStepsCard';
import HistoricalContextCard from '../components/HistoricalContextCard';
import AIHypothesesCard from '../components/AIHypothesesCard';
import VerifiedFindingsCard from '../components/VerifiedFindingsCard';
import './ReportPage.css';

function formatDate(isoString) {
  if (!isoString) return '—';
  try {
    const d = new Date(isoString);
    return isNaN(d.getTime()) ? isoString : d.toLocaleString();
  } catch {
    return isoString;
  }
}

export default function ReportPage() {
  const { incident_id: incidentId } = useParams();

  const [incident, setIncident] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState('');
  const [is404, setIs404] = useState(false);

  // Resolution panel state
  const [resolutionText, setResolutionText] = useState('');
  const [isVerifiedChecked, setIsVerifiedChecked] = useState(false);
  const [isResolving, setIsResolving] = useState(false);
  const [resolveError, setResolveError] = useState('');
  const [resolveSuccessMsg, setResolveSuccessMsg] = useState('');

  const fetchIncidentData = useCallback(async () => {
    if (!incidentId) return;
    setIsLoading(true);
    setErrorMessage('');
    setIs404(false);

    try {
      const data = await getIncident(incidentId);
      setIncident(data);
    } catch (err) {
      if (err.status === 404) {
        setIs404(true);
      } else {
        setErrorMessage(err.message || 'Failed to retrieve incident details.');
      }
    } finally {
      setIsLoading(false);
    }
  }, [incidentId]);

  useEffect(() => {
    fetchIncidentData();
  }, [fetchIncidentData]);

  const handleResolveSubmit = async (e) => {
    e.preventDefault();
    if (!resolutionText.trim() || !isVerifiedChecked || isResolving) return;

    setIsResolving(true);
    setResolveError('');
    setResolveSuccessMsg('');

    try {
      await resolveIncident(incidentId, resolutionText.trim());
      setResolveSuccessMsg('Resolution confirmed successfully! Re-syncing memory status...');
      // Refetch incident from backend to read the durable memory_status
      await fetchIncidentData();
      setResolutionText('');
      setIsVerifiedChecked(false);
    } catch (err) {
      setResolveError(err.message || 'Failed to confirm incident resolution.');
    } finally {
      setIsResolving(false);
    }
  };

  const handlePrint = () => {
    window.print();
  };

  if (isLoading) {
    return (
      <div className="page-wrapper" style={{ textAlign: 'center', padding: '4rem 1rem' }}>
        <div style={{ fontSize: '1.75rem', marginBottom: '1rem' }}>⏳</div>
        <p style={{ color: 'var(--text-muted)' }}>Loading investigation report for {incidentId}...</p>
      </div>
    );
  }

  if (is404) {
    return (
      <div className="page-wrapper" style={{ textAlign: 'center', padding: '4rem 1rem' }}>
        <div className="card" style={{ maxWidth: '520px', margin: '0 auto', padding: '2.5rem' }}>
          <div style={{ fontSize: '2.5rem', marginBottom: '1rem' }}>🔍</div>
          <h2>Incident Not Found</h2>
          <p style={{ color: 'var(--text-muted)', margin: '1rem 0 1.5rem' }}>
            We could not find an incident with ID <code className="mono">{incidentId}</code> in the database.
          </p>
          <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center' }}>
            <Link to="/analyze" className="btn btn-primary">
              Analyze a New Incident
            </Link>
          </div>
        </div>
      </div>
    );
  }

  if (errorMessage || !incident) {
    return (
      <div className="page-wrapper" style={{ padding: '3rem 1rem' }}>
        <div className="alert alert-error">
          <strong>Error loading report:</strong> {errorMessage || 'Incident record is unavailable.'}
        </div>
        <div style={{ marginTop: '1rem' }}>
          <button className="btn btn-secondary" onClick={fetchIncidentData}>
            🔄 Retry
          </button>
        </div>
      </div>
    );
  }

  const isResolved = (incident.status || '').toLowerCase() === 'resolved';
  const isSynthetic = Boolean(
    incident.is_synthetic ||
    (incident.metadata && incident.metadata.type === 'synthetic_test')
  );

  const lastAnalysis = incident.last_analysis || {};

  return (
    <div className="page-wrapper">
      {/* Report Header */}
      <div className="report-header">
        <div className="report-title-area">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
            <h1 className="mono" style={{ fontSize: '1.5rem', margin: 0 }}>
              {incident.incident_id}
            </h1>
            <StatusBadge status={incident.status} />
            <MemoryStatusBadge memoryStatus={incident.memory_status} />
            {isSynthetic && (
              <span className="badge badge-synthetic">
                SYNTHETIC TEST DATA
              </span>
            )}
          </div>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', margin: 0 }}>
            Investigation report for <strong>{incident.service}</strong> ({incident.environment})
          </p>
        </div>

        <div className="report-actions no-print">
          <button type="button" className="btn btn-secondary" onClick={handlePrint} title="Print or save as PDF">
            🖨️ Print / Export PDF
          </button>
          <Link to="/analyze" className="btn btn-secondary">
            + New Incident
          </Link>
        </div>
      </div>

      {/* Incident Metadata & Symptoms Card */}
      <div className="card">
        <div className="card-header">
          <h3 className="card-title">
            <span>ℹ️</span> Incident Specifications
          </h3>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Recorded: {formatDate(incident.created_at)}
          </span>
        </div>

        <div style={{ marginBottom: '1rem' }}>
          <div style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>
            Symptoms & Observed Failures
          </div>
          <p style={{ color: 'var(--text-secondary)', lineHeight: 1.6, whiteSpace: 'pre-line' }}>
            {incident.symptoms}
          </p>
        </div>

        {Array.isArray(incident.possible_causes) && incident.possible_causes.length > 0 && (
          <div style={{ marginBottom: '1rem' }}>
            <div style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>
              Engineer Initial Hypotheses (Unverified)
            </div>
            <ul style={{ paddingLeft: '1.25rem', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
              {incident.possible_causes.map((cause, idx) => (
                <li key={idx}>{cause}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="incident-meta-grid">
          <div className="meta-item">
            <span className="meta-label">Service</span>
            <span className="meta-value mono">{incident.service}</span>
          </div>
          <div className="meta-item">
            <span className="meta-label">Environment</span>
            <span className="meta-value">{incident.environment}</span>
          </div>
          <div className="meta-item">
            <span className="meta-label">Created At</span>
            <span className="meta-value">{formatDate(incident.created_at)}</span>
          </div>
          <div className="meta-item">
            <span className="meta-label">Last Updated</span>
            <span className="meta-value">{formatDate(incident.updated_at)}</span>
          </div>
        </div>
      </div>

      {/* Confirm Resolution Panel (only while status != resolved) */}
      {!isResolved && (
        <div className="confirm-panel no-print">
          <div className="confirm-header">
            <div>
              <h3 style={{ fontSize: '1.05rem', color: 'var(--text-primary)', marginBottom: '0.25rem' }}>
                🛡️ Confirm Incident Resolution
              </h3>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.825rem', margin: 0 }}>
                Confirmed resolutions are saved to team memory and used for future recall.
              </p>
            </div>
            {isSynthetic && (
              <span className="badge badge-synthetic">
                Synthetic Test Incident
              </span>
            )}
          </div>

          {isSynthetic && (
            <div className="alert alert-info" style={{ marginBottom: '1rem' }}>
              ℹ️ <strong>Note:</strong> This is synthetic test data. Resolution will be retained as synthetic test data.
            </div>
          )}

          {resolveSuccessMsg && (
            <div className="alert alert-success" style={{ marginBottom: '1rem' }}>
              {resolveSuccessMsg}
            </div>
          )}

          {resolveError && (
            <div className="alert alert-error" style={{ marginBottom: '1rem' }}>
              <strong>Error:</strong> {resolveError}
            </div>
          )}

          <form onSubmit={handleResolveSubmit}>
            <div className="form-group">
              <label className="form-label" htmlFor="resolution_text">
                Verified Root Cause & Permanent Fix <span style={{ color: 'var(--color-danger)' }}>*</span>
              </label>
              <textarea
                id="resolution_text"
                className="form-textarea"
                rows={3}
                value={resolutionText}
                onChange={(e) => setResolutionText(e.target.value)}
                placeholder="Explain the verified root cause and how it was resolved (e.g. Scaled connection pool from 20 to 100; patched deadlock in worker queue)..."
                required
                disabled={isResolving}
              />
            </div>

            <div className="form-group">
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={isVerifiedChecked}
                  onChange={(e) => setIsVerifiedChecked(e.target.checked)}
                  required
                  disabled={isResolving}
                />
                <span>
                  <strong>I confirm an engineer verified this resolution</strong>
                </span>
              </label>
            </div>

            <button
              type="submit"
              className="btn btn-success"
              disabled={!resolutionText.trim() || !isVerifiedChecked || isResolving}
            >
              {isResolving ? 'Persisting to Hindsight memory...' : '✓ Confirm & Persist Resolution'}
            </button>
          </form>
        </div>
      )}

      {/* Card 4: Verified Findings Card (Prominently shown if resolved) */}
      <VerifiedFindingsCard
        confirmedResolution={incident.confirmed_resolution || lastAnalysis.confirmed_resolution}
        memoryStatus={incident.memory_status}
        isResolved={isResolved}
      />

      {/* Card 1: Investigation Summary & Recommended Steps */}
      <SummaryStepsCard
        summary={lastAnalysis.investigation_summary}
        recommendedSteps={lastAnalysis.recommended_steps}
      />

      {/* Card 2: Similar Past Incidents */}
      <HistoricalContextCard
        historicalContext={lastAnalysis.historical_context}
        matchCount={lastAnalysis.historical_match_count}
      />

      {/* Card 3: AI Hypotheses Card */}
      <AIHypothesesCard
        aiLabel={lastAnalysis.ai_label}
        aiStatus={lastAnalysis.ai_status}
        aiHypotheses={lastAnalysis.ai_hypotheses}
        aiInvestigationPlan={lastAnalysis.ai_investigation_plan}
        aiCaveats={lastAnalysis.ai_caveats}
      />
    </div>
  );
}

