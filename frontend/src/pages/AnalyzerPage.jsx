import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { createIncident } from '../api';
import SummaryStepsCard from '../components/SummaryStepsCard';
import HistoricalContextCard from '../components/HistoricalContextCard';
import AIHypothesesCard from '../components/AIHypothesesCard';
import VerifiedFindingsCard from '../components/VerifiedFindingsCard';
import './AnalyzerPage.css';

function generateIncidentId() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  const ymd = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`;
  const hms = `${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  return `INC-${ymd}-${hms}`;
}

export default function AnalyzerPage() {
  const [incidentId, setIncidentId] = useState(generateIncidentId());
  const [service, setService] = useState('');
  const [environment, setEnvironment] = useState('production');
  const [symptoms, setSymptoms] = useState('');
  const [possibleCauses, setPossibleCauses] = useState('');
  const [isSynthetic, setIsSynthetic] = useState(false);

  const [isLoading, setIsLoading] = useState(false);
  const [cooldownRemaining, setCooldownRemaining] = useState(0);
  const [errorMessage, setErrorMessage] = useState('');
  const [analysisResult, setAnalysisResult] = useState(null);

  const cooldownTimerRef = useRef(null);

  // Clean up timer on unmount
  useEffect(() => {
    return () => {
      if (cooldownTimerRef.current) {
        clearInterval(cooldownTimerRef.current);
      }
    };
  }, []);

  const handleLoadSyntheticExample = () => {
    const synthId = `INC-SYNTH-${Date.now().toString().slice(-6)}`;
    setIncidentId(synthId);
    setService('synthetic payment-service');
    setEnvironment('synthetic-staging');
    setSymptoms(
      '[SYNTHETIC TEST RECORD] High p99 latency in payment checkout flow exceeding 5000ms. Intermittent database connection pool timeouts under simulated black-friday peak load.'
    );
    setPossibleCauses(
      'PostgreSQL pool exhaustion under burst load\nSynthetic payment gateway webhook latency'
    );
    setIsSynthetic(true);
    setErrorMessage('');
  };

  const startCooldown = (seconds = 5) => {
    setCooldownRemaining(seconds);
    if (cooldownTimerRef.current) {
      clearInterval(cooldownTimerRef.current);
    }
    cooldownTimerRef.current = setInterval(() => {
      setCooldownRemaining((prev) => {
        if (prev <= 1) {
          clearInterval(cooldownTimerRef.current);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (isLoading || cooldownRemaining > 0) return;

    if (!incidentId.trim() || !service.trim() || !symptoms.trim()) {
      setErrorMessage('Please fill in Incident ID, Service, and Symptoms.');
      return;
    }

    setIsLoading(true);
    setErrorMessage('');
    startCooldown(5);

    const causesList = possibleCauses
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean);

    const metadata = isSynthetic ? { type: 'synthetic_test' } : {};

    const payload = {
      incident_id: incidentId.trim(),
      service: service.trim(),
      environment: environment.trim() || 'production',
      status: 'investigating',
      symptoms: symptoms.trim(),
      possible_causes: causesList,
      metadata,
    };

    try {
      const response = await createIncident(payload);
      setAnalysisResult(response);
    } catch (err) {
      setErrorMessage(err.message || 'An unexpected error occurred during incident analysis.');
    } finally {
      setIsLoading(false);
    }
  };

  const isButtonDisabled = isLoading || cooldownRemaining > 0;

  return (
    <div className="page-wrapper">
      <div className="analyzer-header">
        <h1>Incident Analyzer</h1>
        <p className="analyzer-subtitle">
          Submit live or synthetic incidents for team memory recall and AI-powered diagnostic hypotheses.
        </p>
      </div>

      {errorMessage && (
        <div className="alert alert-error" style={{ marginBottom: '1.5rem' }}>
          <strong>Error:</strong> {errorMessage}
        </div>
      )}

      {/* Input Form Card */}
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">
            <span>📝</span> Ingest New Incident
          </h2>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={handleLoadSyntheticExample}
            disabled={isLoading}
          >
            ⚡ Load synthetic example
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="form-grid">
            <div className="form-group">
              <label className="form-label" htmlFor="incident_id">
                Incident ID <span style={{ color: 'var(--color-danger)' }}>*</span>
              </label>
              <input
                id="incident_id"
                className="form-input mono"
                type="text"
                value={incidentId}
                onChange={(e) => setIncidentId(e.target.value)}
                placeholder="INC-20261107-123456"
                required
                disabled={isLoading}
              />
              <div className="form-hint">Unique identifier (auto-generated, editable)</div>
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="service">
                Service <span style={{ color: 'var(--color-danger)' }}>*</span>
              </label>
              <input
                id="service"
                className="form-input"
                type="text"
                value={service}
                onChange={(e) => setService(e.target.value)}
                placeholder="e.g. checkout-service, payment-gateway"
                required
                disabled={isLoading}
              />
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="environment">
                Environment
              </label>
              <input
                id="environment"
                className="form-input"
                type="text"
                value={environment}
                onChange={(e) => setEnvironment(e.target.value)}
                placeholder="production, staging, etc."
                disabled={isLoading}
              />
            </div>

            <div className="form-group" style={{ display: 'flex', alignItems: 'center' }}>
              <label className="checkbox-label" style={{ marginTop: '1.25rem' }}>
                <input
                  type="checkbox"
                  checked={isSynthetic}
                  onChange={(e) => setIsSynthetic(e.target.checked)}
                  disabled={isLoading}
                />
                <span>
                  <strong>Mark as synthetic test data</strong> (safe for experimentation)
                </span>
              </label>
            </div>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="symptoms">
              Observed Symptoms <span style={{ color: 'var(--color-danger)' }}>*</span>
            </label>
            <textarea
              id="symptoms"
              className="form-textarea"
              rows={3}
              value={symptoms}
              onChange={(e) => setSymptoms(e.target.value)}
              placeholder="Describe user-visible errors, error rates, alerts, latency degradation..."
              required
              disabled={isLoading}
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="possible_causes">
              Your own hypotheses (unverified)
            </label>
            <textarea
              id="possible_causes"
              className="form-textarea"
              rows={2}
              value={possibleCauses}
              onChange={(e) => setPossibleCauses(e.target.value)}
              placeholder="Enter candidate hypotheses, one per line (optional)"
              disabled={isLoading}
            />
            <div className="form-hint">One hypothesis per line</div>
          </div>

          <div className="form-actions">
            <div className="submit-group">
              <button
                type="submit"
                className="btn btn-primary"
                disabled={isButtonDisabled}
                style={{ minWidth: '220px' }}
              >
                {isLoading ? (
                  <span>⏳ Searching memory & AI hypotheses...</span>
                ) : cooldownRemaining > 0 ? (
                  <span>⏳ Rate limit pause ({cooldownRemaining}s)...</span>
                ) : (
                  <span>🚀 Analyze Incident</span>
                )}
              </button>
              <div className="rate-limit-note">
                Each analysis uses 1 memory recall and 1 AI call.
              </div>
            </div>

            {analysisResult && (
              <Link
                to={`/report/${encodeURIComponent(analysisResult.incident_id)}`}
                className="btn btn-secondary"
              >
                📄 Open full report →
              </Link>
            )}
          </div>
        </form>
      </div>

      {/* Analysis Results Display */}
      {analysisResult && (
        <div className="results-section">
          <div className="results-header">
            <div>
              <h2>Investigation Results</h2>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                Incident: <span className="mono">{analysisResult.incident_id}</span> ({analysisResult.service} on {analysisResult.environment})
              </div>
            </div>
            <Link
              to={`/report/${encodeURIComponent(analysisResult.incident_id)}`}
              className="btn btn-primary"
            >
              📄 Open full report →
            </Link>
          </div>

          {/* Card 1: Summary + Recommended Steps */}
          <SummaryStepsCard
            summary={analysisResult.investigation_summary}
            recommendedSteps={analysisResult.recommended_steps}
          />

          {/* Card 2: Similar Past Incidents */}
          <HistoricalContextCard
            historicalContext={analysisResult.historical_context}
            matchCount={analysisResult.historical_match_count}
          />

          {/* Card 3: AI Hypotheses Card */}
          <AIHypothesesCard
            aiLabel={analysisResult.ai_label}
            aiStatus={analysisResult.ai_status}
            aiHypotheses={analysisResult.ai_hypotheses}
            aiInvestigationPlan={analysisResult.ai_investigation_plan}
            aiCaveats={analysisResult.ai_caveats}
          />

          {/* Card 4: Verified Findings Card */}
          <VerifiedFindingsCard
            confirmedResolution={analysisResult.confirmed_resolution}
            memoryStatus="not_applicable"
            isResolved={false}
          />
        </div>
      )}
    </div>
  );
}

