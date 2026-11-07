import React from 'react';

/**
 * Checks if a string looks like a standard UUID (v4/v1).
 */
function isUUID(str) {
  if (!str || typeof str !== 'string') return false;
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(str.trim());
}

/**
 * Extracts a friendly prior incident identifier from metadata, text, or tags.
 */
function getPriorIncidentKey(item, fallbackIndex) {
  if (item.metadata && item.metadata.incident_id && !isUUID(item.metadata.incident_id)) {
    return String(item.metadata.incident_id).trim();
  }

  // Check text for Incident ID patterns
  if (item.text) {
    const match = item.text.match(/\bIncident\s+([A-Za-z0-9_-]+)/i);
    if (match && match[1] && !isUUID(match[1])) {
      const candidate = match[1].trim();
      const forbidden = ['id', 'identifier', 'report', 'fact', 'record'];
      if (!forbidden.includes(candidate.toLowerCase())) {
        return candidate;
      }
    }
  }

  return `Past Incident #${fallbackIndex + 1}`;
}

export default function HistoricalContextCard({ historicalContext, matchCount }) {
  const records = Array.isArray(historicalContext) ? historicalContext : [];

  if (records.length === 0) {
    return (
      <div className="card">
        <div className="card-header">
          <h3 className="card-title">
            <span>🧠</span> Similar Past Incidents
          </h3>
          <span className="badge badge-neutral">0 matches</span>
        </div>
        <p style={{ color: 'var(--text-muted)' }}>
          No similar past incidents found in the Hindsight memory bank.
        </p>
      </div>
    );
  }

  // Group records by prior incident
  const grouped = new Map();
  records.forEach((rec, idx) => {
    const key = getPriorIncidentKey(rec, grouped.size);
    if (!grouped.has(key)) {
      grouped.set(key, []);
    }
    grouped.get(key).push(rec);
  });

  const distinctCount = grouped.size;
  const countLabel = `${records.length} memory record${records.length === 1 ? '' : 's'} from ${distinctCount} prior incident${distinctCount === 1 ? '' : 's'}`;

  return (
    <div className="card">
      <div className="card-header">
        <h3 className="card-title">
          <span>🧠</span> Similar Past Incidents
        </h3>
        <span className="badge badge-neutral" style={{ textTransform: 'none' }}>
          {countLabel}
        </span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
        {Array.from(grouped.entries()).map(([groupName, items], groupIdx) => (
          <div
            key={groupIdx}
            style={{
              background: 'var(--bg-surface-elevated)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-md)',
              padding: '1rem',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: '0.75rem',
                paddingBottom: '0.5rem',
                borderBottom: '1px solid var(--border-subtle)',
              }}
            >
              <h4 style={{ fontSize: '0.95rem', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                {groupName.startsWith('Past Incident') ? groupName : `Prior Incident: ${groupName}`}
              </h4>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                {items.length} observation{items.length === 1 ? '' : 's'}
              </span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              {items.map((item, itemIdx) => {
                const finalScore = item.scores && typeof item.scores.final === 'number'
                  ? item.scores.final
                  : null;

                return (
                  <div
                    key={itemIdx}
                    style={{
                      padding: '0.75rem',
                      background: 'var(--bg-primary)',
                      border: '1px solid var(--border-default)',
                      borderRadius: 'var(--radius-sm)',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.35rem', gap: '0.5rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        {item.is_synthetic && (
                          <span className="badge badge-synthetic">
                            SYNTHETIC TEST DATA
                          </span>
                        )}
                        {item.memory_type && (
                          <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                            {item.memory_type}
                          </span>
                        )}
                      </div>

                      {finalScore !== null && (
                        <span
                          className="mono"
                          style={{
                            fontSize: '0.75rem',
                            color: finalScore > 0.7 ? '#34d399' : '#94a3b8',
                            background: 'var(--bg-surface)',
                            padding: '0.1rem 0.4rem',
                            borderRadius: 'var(--radius-sm)',
                            border: '1px solid var(--border-subtle)',
                          }}
                          title={`Raw score: ${finalScore}`}
                        >
                          Score: {(finalScore * 100).toFixed(0)}%
                        </span>
                      )}
                    </div>

                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', lineHeight: 1.5, margin: 0 }}>
                      {item.text}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

