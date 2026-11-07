import React from 'react';

export default function SummaryStepsCard({ summary, recommendedSteps }) {
  if (!summary && (!recommendedSteps || recommendedSteps.length === 0)) {
    return null;
  }

  return (
    <div className="card">
      <div className="card-header">
        <h3 className="card-title">
          <span>📋</span> Investigation Summary & Recommended Steps
        </h3>
      </div>

      {summary && (
        <div style={{ marginBottom: '1.25rem' }}>
          <p style={{ color: 'var(--text-secondary)', lineHeight: 1.6, whiteSpace: 'pre-line' }}>
            {summary}
          </p>
        </div>
      )}

      {recommendedSteps && recommendedSteps.length > 0 && (
        <div>
          <h4 style={{ fontSize: '0.875rem', color: 'var(--text-muted)', marginBottom: '0.5rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Next Actions
          </h4>
          <ol style={{ paddingLeft: '1.25rem', color: 'var(--text-secondary)' }}>
            {recommendedSteps.map((step, idx) => (
              <li key={idx} style={{ marginBottom: '0.4rem', lineHeight: 1.5 }}>
                {step}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

