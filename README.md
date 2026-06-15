# KYC Sentinel — Agentic KYC Intelligence Platform

AMD Agentic AI Hackathon 2026 submission. Multi-agent KYC due diligence with explainable risk scoring, human-in-the-loop review, and auditable decisions.

## Architecture

```
Customer Input → Orchestrator Agent → Dynamic Investigation → Specialized Agents
  → Risk Scoring → Explainability → Decision → Human Review → Audit Report
```

**Tech Stack**
- **Frontend:** React + Vite + TypeScript
- **Backend:** FastAPI + Python
- **Vector DB:** TF-IDF vector store (sanctions, PEP, adverse media semantic search)
- **Matching:** RapidFuzz + vector similarity search
- **Agent Framework:** Custom orchestrator with dynamic routing (LangGraph-compatible state)

## Quick Start

### Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

## Demo Cases

| Customer | Expected | Decision |
|----------|----------|----------|
| Emily Chen / James Wilson | Low Risk | **APPROVE** |
| Marco Silva / Viktor Petrov | Medium Risk | **REVIEW** |
| Ahmad Al-Rashid / Kim Jong-un / Carlos Mendez | High Risk | **ESCALATE** |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/customers` | Sample customers |
| POST | `/api/kyc/run/{customer_id}` | Run full KYC workflow |
| POST | `/api/kyc/run` | Run with custom customer JSON |
| GET | `/api/cases` | List all cases |
| GET | `/api/cases/{id}` | Case detail |
| POST | `/api/cases/{id}/review` | Submit human review |
| GET | `/api/cases/{id}/audit` | Audit report |

## Agents

1. **Customer Intake** — Structure onboarding data
2. **Profile Normalization** — Standardize names, dates, fields
3. **Entity Resolution** — RapidFuzz matching to reduce false positives
4. **Compliance Screening** — Sanctions + PEP (vector DB + fuzzy)
5. **Adverse Media** — Semantic search over news/regulatory data
6. **Financial Profiling** — Country/occupation/funds risk
7. **Risk Scoring** — Weighted aggregation (0–100)
8. **Explainability** — Human-readable reasoning
9. **Decision** — Approve (0–39) / Review (40–69) / Escalate (70+)
10. **Human Review** — Compliance officer override
11. **Audit Report** — Full evidence trail

## AMD Alignment

- Vector search layer designed for ROCm-accelerated embedding models (PyTorch / sentence-transformers)
- Designed for Ryzen AI edge deployment of lightweight screening models
- Multi-agent orchestration demonstrates agentic AI on AMD infrastructure

## Data Sources

Real compliance data is loaded via `python -m scripts.fetch_datasets`:

| Source | Dataset | Used For |
|--------|---------|----------|
| **OpenSanctions** | [Consolidated Sanctions](https://www.opensanctions.org/datasets/sanctions/) + [PEP](https://www.opensanctions.org/datasets/peps/) | Sanctions screening, PEP screening, vector DB |
| **Kaggle** (optional) | [Synthetic KYC & Transaction Risk](https://www.kaggle.com/datasets/chaitalithakkar/synthetic-kyc-and-transaction-risk-dataset) | Country risk, adverse media flags, extra PEP/sanctions |
| **Kaggle** (optional) | [Synthetic AML Transactions](https://www.kaggle.com/datasets/berkanoztas/synthetic-transaction-monitoring-dataset-aml) | AML risk patterns |

### Fetch / refresh datasets

```bash
cd backend
python -m scripts.fetch_datasets
```

### Kaggle setup (optional)

1. Create account at [kaggle.com](https://www.kaggle.com)
2. Go to **Settings → API → Create New Token** (downloads `kaggle.json`)
3. Place at `~/.kaggle/kaggle.json` (Windows: `C:\Users\<you>\.kaggle\kaggle.json`)
4. Re-run `python -m scripts.fetch_datasets`

Local files:
- `data/sanctions_watchlist.json` — 5,000+ sanctions + PEP entries
- `data/country_risk.csv` — 200+ countries from OpenSanctions
- `data/adverse_media.json` — Adverse media (Kaggle flags when available)
- `data/occupation_risk.csv` — Occupation risk reference
