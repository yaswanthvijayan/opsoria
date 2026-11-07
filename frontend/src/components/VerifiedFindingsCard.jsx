import React from 'react';
import MemoryStatusBadge from './MemoryStatusBadge';

export default function VerifiedFindingsCard({ confirmedResolution, memoryStatus, isResolved }) {
  const hasResolution = Boolean(confirmedResolution && confirmedResolution.trim());

  return (
    <div
      className="card"
      style={{
        borderColor: hasResolution ? 'var(--color-success-border)' : 'var(--border-default)',
        boxShadow: hasResolution ? '0 0 0 1px var(--color-success-border)' : 'none',
      }}
    >
      <div className="card-header">
        <h3 className="card-title" style={{ color: hasResolution ? '#34d399' : 'var(--text-primary)' }}>
          <span>✅</span> Verified Findings & Resolution
        </h3>
        {hasResolution && <MemoryStatusBadge memoryStatus={memoryStatus} />}
      </div>

      {hasResolution ? (
        <div style={{ background: 'var(--color-success-bg)', border: '1px solid var(--color-success-border)', borderRadius: 'var(--radius-md)', padding: '1rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
            <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#34d399', textTransform: 'uppercase' }}>
              Engineer-Verified Root Cause & Fix
            </span>
          </div>
          <p style={{ color: 'var(--text-primary)', fontSize: '0.925rem', lineHeight: 1.6, whiteSpace: 'pre-line', margin: 0 }}>
            {confirmedResolution}
          </p>
        </div>
      ) : (
        <div style={{ padding: '1rem', background: 'var(--bg-surface-elevated)', borderRadius: 'var(--radius-md)', color: 'var(--text-muted)' }}>
          <p style={{ margin: 0, fontSize: '0.875rem' }}>
            ⏳ None yet - waiting for engineer confirmation
          </p>
          <p style={{ margin: '0.35rem 0 0', fontSize: '0.75rem', color: 'var(--text-faint)' }}>
            Once the team resolves the issue and verifies the root cause, confirm the resolution to persist it into team memory.
          </p>
        </div>
      )}
    </div>
  );
}

