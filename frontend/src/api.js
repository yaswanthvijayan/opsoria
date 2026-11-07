/**
 * Opsoria Frontend API Client
 * Communicates with the FastAPI backend using standard fetch.
 */

const RAW_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000';
export const API_BASE = RAW_BASE.replace(/\/+$/, '');
const API_KEY = (import.meta.env.VITE_API_KEY || '').trim();

/**
 * Common request wrapper with authentication and unified error handling.
 */
async function apiRequest(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  if (API_KEY) {
    headers['x-api-key'] = API_KEY;
  }

  let response;
  try {
    response = await fetch(url, {
      ...options,
      headers,
    });
  } catch (networkError) {
    throw new Error(
      `Backend is unreachable at ${API_BASE}. Please ensure the Opsoria API server is running.`
    );
  }

  if (!response.ok) {
    let errorDetail = `Request failed with status ${response.status} (${response.statusText})`;
    try {
      const errData = await response.json();
      if (errData && errData.detail) {
        if (typeof errData.detail === 'string') {
          errorDetail = errData.detail;
        } else if (Array.isArray(errData.detail)) {
          // FastAPI validation errors (422)
          errorDetail = errData.detail
            .map((e) => `${e.loc ? e.loc.join('.') : 'field'}: ${e.msg}`)
            .join('; ');
        }
      }
    } catch {
      // Ignore JSON parse errors for non-JSON response bodies
    }
    const err = new Error(errorDetail);
    err.status = response.status;
    throw err;
  }

  return response.json();
}

/**
 * Ingest a new incident for analysis and AI hypothesis synthesis.
 * Calls POST /incidents
 */
export async function createIncident(incidentData) {
  return apiRequest('/incidents', {
    method: 'POST',
    body: JSON.stringify(incidentData),
  });
}

/**
 * Confirm the verified resolution of an incident.
 * Calls POST /incidents/:id/resolve
 */
export async function resolveIncident(incidentId, confirmedResolution) {
  return apiRequest(`/incidents/${encodeURIComponent(incidentId)}/resolve`, {
    method: 'POST',
    body: JSON.stringify({
      confirmed_resolution: confirmedResolution,
    }),
  });
}

/**
 * Fetch a single incident record by ID, including last_analysis.
 * Calls GET /incidents/:id
 */
export async function getIncident(incidentId) {
  return apiRequest(`/incidents/${encodeURIComponent(incidentId)}`);
}

/**
 * List incidents, ordered newest first, with optional status filter.
 * Calls GET /incidents?status=...
 */
export async function listIncidents(status) {
  const query = status ? `?status=${encodeURIComponent(status)}` : '';
  return apiRequest(`/incidents${query}`);
}

/**
 * Fetch aggregate statistics and recent incidents.
 * Calls GET /stats
 */
export async function getStats() {
  return apiRequest('/stats');
}

/**
 * Check backend health status without touching Retain/Recall.
 * Calls GET /health
 */
export async function checkHealth() {
  return apiRequest('/health');
}

