import React from 'react';

export default function StatusBadge({ status }) {
  const norm = (status || 'investigating').toLowerCase();
  let badgeClass = 'badge-investigating';
  let label = status || 'investigating';

  if (norm === 'resolved') {
    badgeClass = 'badge-resolved';
    label = 'Resolved';
  } else if (norm === 'investigating') {
    badgeClass = 'badge-investigating';
    label = 'Investigating';
  } else {
    badgeClass = 'badge-neutral';
  }

  return (
    <span className={`badge ${badgeClass}`}>
      {label}
    </span>
  );
}

