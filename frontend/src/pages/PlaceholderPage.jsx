import React from 'react';
import { Link } from 'react-router-dom';

export default function PlaceholderPage({ title, description }) {
  return (
    <div className="page-wrapper" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh' }}>
      <div className="card" style={{ maxWidth: '480px', textAlign: 'center', padding: '2.5rem 2rem' }}>
        <div style={{ fontSize: '2.5rem', marginBottom: '1rem' }}>🚧</div>
        <h2 style={{ marginBottom: '0.75rem' }}>{title}</h2>
        <p style={{ color: 'var(--text-muted)', marginBottom: '1.5rem', lineHeight: 1.6 }}>
          {description || 'This feature is coming next in an upcoming task.'}
        </p>
        <Link to="/analyze" className="btn btn-primary">
          Go to Incident Analyzer →
        </Link>
      </div>
    </div>
  );
}

