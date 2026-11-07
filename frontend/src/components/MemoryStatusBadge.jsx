import React from 'react';

export default function MemoryStatusBadge({ memoryStatus }) {
  const status = (memoryStatus || 'not_applicable').toLowerCase();

  if (status === 'persisted') {
    return (
      <span className="badge badge-persisted" title="Confirmed resolution persisted to Hindsight Cloud memory">
        ✓ Saved to Hindsight memory
      </span>
    );
  }

  if (status === 'not_persisted') {
    return (
      <span className="badge badge-not-persisted" title="Resolution confirmed locally but retain failed or offline">
        ✕ Resolution NOT saved to memory
      </span>
    );
  }

  return (
    <span className="badge badge-neutral" title="Memory persistence pending confirmed resolution">
      ○ Memory: Pending Resolution
    </span>
  );
}

