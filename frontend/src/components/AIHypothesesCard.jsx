import React from 'react';

export default function AIHypothesesCard({
  aiLabel,
  aiStatus,
  aiHypotheses,
  aiInvestigationPlan,
  aiCaveats,
}) {
  const label = aiLabel || 'AI-generated hypotheses - UNVERIFIED. Not a confirmed root cause.';
  const status = (aiStatus || '').toLowerCase();
  const hypotheses = Array.isArray(aiHypotheses) ? aiHypotheses : [];
  const plan = Array.isArray(aiInvestigationPlan) ? aiInvestigationPlan : [];
  const caveats = Array.isArray(aiCaveats) ? aiCaveats : [];

  let statusBadge = null;
  if (status === 'success') {
    statusBadge = <span className="badge badge-resolved">AI Analysis Ready</span>;
  } else if (status === 'unavailable') {
    statusBadge = <span className="badge badge-synthetic">AI Offline</span>;
  } else if (status === 'not_configured') {
    statusBadge = <span className="badge badge-neutral">AI Not Configured</span>;
  }

  return (
    <div
      className="card"
      style={{
        borderColor: 'var(--color-warning-border)',
        boxShadow: '0 0 0 1px var(--color-warning-border)',
      }}
    >
      <div className="card-header">
        <h3 className="card-title" style={{ color: '#fbbf24' }}>
          <span>⚡</span> AI Investigation Hypotheses
        </h3>
        {statusBadge}
      </div>

      {/* Prominent Warning Banner for AI Hypotheses */}
      <div className="alert alert-warning" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <span style={{ fontSize: '1.25rem' }}>⚠️</span>
        <div>
          <div style={{ fontWeight: 600, letterSpacing: '0.02em' }}>{label}</div>
          <div style={{ fontSize: '0.75rem', marginTop: '0.15rem', opacity: 0.9 }}>
            All hypotheses are AI-generated suggestions. Validate against production logs and telemetry before taking remediation actions.
          </div>
        </div>
      </div>

      {/* Friendly note if AI is not configured or unavailable */}
      {(status === 'not_configured' || status === 'unavailable') && (
        <div className="alert alert-info" style={{ marginTop: '0.5rem' }}>
          ℹ️ The AI reasoning service is currently {status === 'not_configured' ? 'not configured' : 'temporarily unavailable'}.
          The rest of your incident analysis, memory recall, and retention workflows are completely unaffected.
        </div>
      )}

      {/* Hypotheses List */}
      {hypotheses.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', marginTop: '1rem' }}>
          {hypotheses.map((hypo, idx) => {
            const conf = (hypo.confidence || 'low').toLowerCase();
            const confClass =
              conf === 'high'
                ? 'badge-confidence-high'
                : conf === 'medium'
                ? 'badge-confidence-medium'
                : 'badge-confidence-low';

            return (
              <div
                key={idx}
                style={{
                  background: 'var(--bg-surface-elevated)',
                  border: '1px solid var(--border-default)',
                  borderRadius: 'var(--radius-md)',
                  padding: '1.15rem',
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    justifyContent: 'space-between',
                    marginBottom: '0.5rem',
                    gap: '1rem',
                  }}
                >
                  <h4 style={{ fontSize: '1rem', color: 'var(--text-primary)', fontWeight: 600 }}>
                    {idx + 1}. {hypo.title || 'Untitled Hypothesis'}
                  </h4>
                  <span className={`badge ${confClass}`}>
                    Confidence: {conf.toUpperCase()}
                  </span>
                </div>

                <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', lineHeight: 1.5, marginBottom: '0.75rem' }}>
                  {hypo.reasoning}
                </p>

                {/* Evidence references */}
                {Array.isArray(hypo.evidence_refs) && hypo.evidence_refs.length > 0 && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Supporting Evidence:</span>
                    {hypo.evidence_refs.map((ref, refIdx) => (
                      <span
                        key={refIdx}
                        className="mono"
                        style={{
                          fontSize: '0.75rem',
                          background: 'rgba(59, 130, 246, 0.1)',
                          color: '#93c5fd',
                          padding: '0.15rem 0.45rem',
                          borderRadius: 'var(--radius-sm)',
                          border: '1px solid rgba(59, 130, 246, 0.2)',
                        }}
                      >
                        {ref}
                      </span>
                    ))}
                  </div>
                )}

                {/* Suggested Checks */}
                {Array.isArray(hypo.suggested_checks) && hypo.suggested_checks.length > 0 && (
                  <div style={{ background: 'var(--bg-primary)', padding: '0.65rem 0.85rem', borderRadius: 'var(--radius-sm)' }}>
                    <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '0.25rem', textTransform: 'uppercase' }}>
                      Suggested Checks
                    </div>
                    <ul style={{ paddingLeft: '1.25rem', margin: 0, fontSize: '0.825rem', color: 'var(--text-secondary)' }}>
                      {hypo.suggested_checks.map((chk, chkIdx) => (
                        <li key={chkIdx}>{chk}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        status === 'success' && (
          <p style={{ color: 'var(--text-muted)', marginTop: '0.5rem' }}>
            No specific AI hypotheses were generated for this incident.
          </p>
        )
      )}

      {/* Investigation Plan */}
      {plan.length > 0 && (
        <div style={{ marginTop: '1.25rem', paddingTop: '1rem', borderTop: '1px solid var(--border-subtle)' }}>
          <h4 style={{ fontSize: '0.875rem', color: 'var(--text-muted)', marginBottom: '0.5rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            AI Investigation Plan
          </h4>
          <ol style={{ paddingLeft: '1.25rem', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
            {plan.map((step, idx) => (
              <li key={idx} style={{ marginBottom: '0.35rem' }}>
                {step}
              </li>
            ))}
          </ol>
        </div>
      )}

      {/* Caveats */}
      {caveats.length > 0 && (
        <div style={{ marginTop: '1rem', paddingTop: '0.75rem', borderTop: '1px solid var(--border-subtle)' }}>
          <h4 style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '0.35rem', textTransform: 'uppercase' }}>
            Caveats & Notes
          </h4>
          <ul style={{ paddingLeft: '1.25rem', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
            {caveats.map((c, idx) => (
              <li key={idx} style={{ marginBottom: '0.25rem' }}>
                {c}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

