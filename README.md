# Opsoria — Incident Intelligence with Persistent Team Memory

**Team:** Code Pioneers  
**Project:** Opsoria  
**Category:** AI-assisted Site Reliability Engineering (SRE)

## Overview

Opsoria is an AI-assisted incident investigation platform designed to help SREs and backend developers investigate recurring software incidents.

Traditional incident investigation often requires engineers to search through old incident reports, logs, and documentation manually. Opsoria uses **Hindsight persistent memory** to recall relevant historical incidents and their previously confirmed resolutions.

Instead of treating every incident as an isolated problem, Opsoria helps teams learn from their investigation history.

## The Problem

Engineering teams frequently face recurring incidents, but knowledge about previous root causes and resolutions can become scattered across logs, reports, and team conversations.

This leads to:
- Repeated investigation effort.
- Slower incident resolution.
- Loss of valuable engineering knowledge.
- Difficulty identifying patterns across previous incidents.

## Our Solution

Opsoria combines AI-assisted analysis with persistent team memory.

When an engineer submits an incident:

1. **Incident submission:** The engineer provides incident details and symptoms.
2. **Historical recall:** Hindsight retrieves relevant information from previous incidents.
3. **AI analysis:** Groq helps generate possible causes and investigation guidance.
4. **Investigation report:** Opsoria presents the analysis and relevant historical context.
5. **Engineer verification:** The engineer reviews and confirms the actual root cause and resolution.
6. **Persistent learning:** Only engineer-confirmed findings and resolutions are retained in Hindsight.

This creates a feedback loop in which verified incident knowledge can help with future investigations.

## Key Features

- **Dashboard:** Overview of incident activity and investigation statistics.
- **Incident Analyzer:** Submit incidents and receive AI-assisted investigation guidance.
- **Incident History:** Review previously submitted incidents.
- **Memory Explorer:** Explore historical knowledge retrieved from Hindsight.
- **Investigation Reports:** Review investigation findings and suggested next steps.
- **Verified Knowledge Retention:** Store confirmed findings and resolutions for future recall.

## Technology Stack

| Component | Technology |
|---|---|
| Frontend | React, Vite |
| Backend | Python, FastAPI |
| Persistent memory | Hindsight Cloud |
| AI analysis | Groq API |
| Database | SQLite |
| API documentation | FastAPI Swagger UI |

## Architecture

```text
              React + Vite
                   |
                   v
              FastAPI Backend
              /      |       \
             /       |        \
            v        v         v
       Hindsight    Groq      SQLite
        Cloud       API       Database
       Memory      Analysis   Incident
                              History
```

### Why Hindsight?

Hindsight is the central memory layer of Opsoria.

It enables the application to retain verified incident knowledge and recall relevant historical information during future investigations.

**Our memory integrity approach:**
- AI-generated hypotheses are treated as suggestions, not confirmed facts.
- Only engineer-confirmed findings and resolutions are eligible for trusted retention.
- Synthetic test records are explicitly labelled.
- Synthetic-only historical evidence must not be presented as a verified production fix.

## API Endpoints

The backend exposes the following API routes:

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Check backend health |
| POST | `/incidents` | Submit and analyze an incident |
| GET | `/incidents` | List incidents |
| GET | `/incidents/{id}` | Retrieve incident details |
| POST | `/incidents/{id}/resolve` | Submit a confirmed resolution |
| GET | `/stats` | Retrieve incident statistics |

Interactive API documentation is available at:

`http://127.0.0.1:8000/docs`

## Getting Started

### Prerequisites

- Python 3.14 or a compatible Python version supported by the project dependencies.
- Node.js 18 or later.
- npm.
- Hindsight Cloud API credentials.
- Groq API key.

### 1. Clone the repository

```bash
git clone https://github.com/yaswanthvijayan/opsoria.git
cd opsoria
```

### 2. Set up the backend

From the project root:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r backend/requirements.txt
```

Create your backend environment file:

```powershell
Copy-Item backend/.env.example backend/.env
```

Configure the required credentials and settings in `backend/.env`. Never commit real API keys.

Start the backend:

```powershell
cd backend
uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

### 3. Set up the frontend

Open another terminal at the project root:

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

Open the local Vite URL displayed in the terminal.

## Running Backend Tests

From the project root:

```powershell
$env:PYTHONPATH = "backend"
python -m unittest discover -s backend/tests -p "test_*.py" -v
```

The backend test suite has been run with **67 passing tests**. External service behavior in integration tests may be mocked; passing tests should not be confused with proof that every live cloud operation has been tested.

## Demo Mode

Opsoria includes a demo-mode configuration for controlled demonstrations.

Refer to the backend environment example and implementation for the supported settings and restrictions. Synthetic demo records must remain clearly distinguishable from real engineering incidents.

## Current Limitations

Opsoria is a hackathon prototype. It does not currently provide:

- Live production infrastructure monitoring.
- Automated incident remediation.
- Slack integration.
- Predictive outage detection.
- Advanced multi-organization access controls.

AI-generated findings require engineer review and should not be treated as authoritative without verification.

## Future Scope

- Integration with monitoring and observability platforms.
- Log-based incident ingestion and analysis.
- Team collaboration and incident assignment.
- More advanced historical incident correlation.
- Integrations with engineering communication platforms.

## Team

**Code Pioneers**

Built for the Hindsight Hackathon.

## Repository

[https://github.com/yaswanthvijayan/opsoria](https://github.com/yaswanthvijayan/opsoria)

---

*Opsoria — Learn from every incident. Investigate smarter next time.*