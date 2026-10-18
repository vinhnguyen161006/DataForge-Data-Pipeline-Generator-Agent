<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/brand/logo-lockup-dark.svg">
  <img alt="DataForge" src="assets/brand/logo-lockup-light.svg" width="380">
</picture>

### **DATAFORGE AI AGENT**
**From Raw CSV to a Verified Data Warehouse**

*Evidence-Backed Profiling • Human-Approved Models • Executed Tests • Measured SQL Rewrites • Reproducible Exports*

---

[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2-FF6F00?style=for-the-badge&logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![React 19](https://img.shields.io/badge/React-19.3-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://react.dev/)
[![dbt](https://img.shields.io/badge/dbt--core-1.12-FF694B?style=for-the-badge&logo=dbt&logoColor=white)](https://www.getdbt.com/)
[![DuckDB](https://img.shields.io/badge/DuckDB-1.5-FFF000?style=for-the-badge&logo=duckdb&logoColor=black)](https://duckdb.org/)
[![PostgreSQL 16](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Airflow 3](https://img.shields.io/badge/Airflow-3.3-017CEE?style=for-the-badge&logo=apacheairflow&logoColor=white)](https://airflow.apache.org/)
[![Metabase](https://img.shields.io/badge/Metabase-0.63-509EE3?style=for-the-badge&logo=metabase&logoColor=white)](https://www.metabase.com/)
[![Qdrant](https://img.shields.io/badge/Qdrant-1.19-DC244C?style=for-the-badge&logo=qdrant&logoColor=white)](https://qdrant.tech/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)

</div>

---

## Executive Overview

### The Data Onboarding Challenge
Every new data source costs a data team the same repetitive work before anyone sees a dashboard:
- **Profiling by hand**: inferring types, null rates, candidate keys and join paths across files that arrive with different encodings, delimiters and null markers.
- **Boilerplate engineering**: writing bronze, silver and mart dbt models, the tests that guard them, and the scheduler DAG that runs them.
- **Generated code that only looks right**: an LLM can write plausible SQL, but plausible is not correct; a wrong join silently multiplies rows and every metric downstream inherits the error.
- **Decisions that are not technical**: the grain of a fact table, what "revenue" means, or how invalid rows are treated are business choices that no tool should make alone.

### The DataForge Solution
**DataForge** takes **raw CSV files and a plain-language analysis request** and returns three things: a **warehouse** of marts on PostgreSQL, a set of **Metabase dashboards**, and the **full pipeline source** as a standalone dbt project (ZIP or Pull Request). A stateful **LangGraph** workflow automates the repetitive part, while two mandatory **human approval gates** keep people in charge of the business decisions and of what gets published.

Three properties hold throughout:
- **LLMs propose, deterministic tools judge.** Generated code is verified by running it and comparing results, never by asking another model.
- **A SQL rewrite is kept only if it is both faster and equivalent** on the test batch.
- **Generated code never runs inside the backend process**, and the system never touches the user's production environment.

---

## System Architecture & Pipeline

The authoring workflow is one **LangGraph `StateGraph`** with a Postgres checkpointer, so a restarted backend resumes every run at the exact point it was waiting.

```mermaid
flowchart TB
  Start(["CSV files + analysis request"]) --> Profile["Profiler<br/>DuckDB statistics, candidate keys,<br/>relationship evidence"]
  Profile --> Modeler["Modeler (LLM)<br/>proposes a data design"]
  Modeler -- "Information missing" --> Clarify["Ask the Engineer"]
  Clarify --> Modeler
  Modeler -- "Design ready" --> Gate1{"Gate 1<br/>Engineer reviews the design"}
  Gate1 -- "Return with comment" --> Modeler
  Gate1 -- "Approve (optionally edited)" --> Codegen["Codegen (LLM)<br/>silver + mart models"]
  Codegen --> Execute["Isolated sandbox worker<br/>dbt build on DuckDB, metrics per model"]
  Execute -- "Compile or test failure" --> Codegen
  Execute --> Optimize["Optimizer (LLM + sqlglot rules)<br/>propose rewrites"]
  Optimize --> Judge{"Deterministic judge<br/>equivalent AND faster?"}
  Judge -- "Rejected: wrong data, run error,<br/>not faster, timeout" --> Optimize
  Judge -- "Kept or none needed" --> Gate2{"Gate 2<br/>Reviewer approves code + evidence"}
  Gate2 -- "Return" --> Codegen
  Gate2 -- "Approve" --> Publish["Publisher<br/>staging load, reconcile, atomic swap"]
  Publish --> Dashboard["Dashboard builder<br/>idempotent Metabase cards"]
  Dashboard --> Done(["Warehouse + dashboards + dbt project"])
```

Approved pipelines are registered as **Airflow** DAGs generated from a fixed template, so scheduled reruns execute exactly the approved version. LangGraph orchestrates *writing* the pipeline; Airflow orchestrates *running* it.

### Process Boundaries

| Process | Allowed | Never allowed |
| :--- | :--- | :--- |
| **API** (FastAPI) | Accept requests, manage state, run LangGraph, call Gemini | Execute generated code, write the warehouse |
| **Sandbox worker** | Run LLM-generated dbt/DuckDB in a resource-limited subprocess, one workspace and DuckDB file per run | Hold warehouse credentials, reach the Internet (internal network only) |
| **Publisher** | Write the warehouse, call the Metabase API | Run LLM-generated code |
| **Airflow** | Rerun approved pipelines with an isolated dbt virtualenv | Hold warehouse credentials, load arbitrary Python |

Full boundary rules and schema ownership per database: [ARCHITECT.md](ARCHITECT.md).

---

## Key Capabilities & Technical Highlights

> These describe the target design of the first release. See [Project Status](#-project-status--roadmap) for what is implemented today.

### 1. Evidence-Backed Profiling
- **Format sniffing**: encoding, delimiter, quote, null tokens and date formats are detected per file, with a preview the Engineer confirms before anything is profiled. Original files are stored byte-for-byte with their read configuration.
- **Statistics, not rows**: DuckDB computes inferred types, null ratios, distinct counts, ranges and samples. Only this `DataProfile` ever reaches the LLM.
- **Key and relationship evidence**: candidate keys (including composite keys) and join paths come with match ratios, orphan counts and **fan-out warnings** for joins that would multiply rows.

### 2. A Modeler That Asks Instead of Guessing
- **Six-part data design**: grain, keys and relationships, metric definitions, cleaning rules, refresh strategy and dashboard requirements, each with its rationale.
- **Clarification loop**: when the profile cannot settle a question (is `amount` a unit price, a line total or the amount paid?), the Modeler asks the Engineer rather than inventing an answer.

### 3. Gate 1: Design Approval
- The Engineer approves the design, edits it section by section, or returns it with a comment. **No code is generated before approval.**
- Approval is bound to the **content hash of the exact design version**; editing creates a new version that needs its own approval.

### 4. Three-Layer dbt Generation
- **Bronze** keeps the source representation untyped (`00123` stays `00123`) with batch, file, row and load metadata. **Silver** types, deduplicates and quarantines bad rows with reasons. **Marts** implement the approved star schema.
- **Tests come only from approved constraints.** Statistical observations are offered as suggestions with evidence; they never become mandatory tests on their own.

### 5. Verified Optimizer
- Rewrites are produced by **sqlglot rules** and an **LLM optimizer**, then judged deterministically.
- **Equivalent** means matching output schema and an identical **multiset of rows with multiplicities**, with explicit rules for NULLs, float tolerance and timestamps, and fixed values for `now()` or random functions.
- **Faster** means a median improvement over repeated runs that exceeds the measured noise, on the same data, engine version and resources. Every rejected rewrite is logged as *wrong data*, *run error*, *not faster* or *timeout*.

### 6. Gate 2: Version-Bound Code Review
- The Reviewer sees the code diff, test results, the before/after performance table and the dashboard configuration.
- Approval binds to a fingerprint of **design + code + tests + batch + run + report**. Any later edit invalidates it. In team mode the Reviewer must differ from the Engineer; in individual mode the history records that there was no independent review.

### 7. Safe Publication and Reproducible Export
- Marts load into **Postgres staging** with `COPY`, are reconciled, then published by an atomic swap; a failure mid-way leaves the previous version serving dashboards. Re-running the same batch replaces data instead of duplicating it.
- **Metabase** cards (KPI, line, bar) are upserted by a stable logical key, so retries never create duplicates.
- The approved version is exported as a **ZIP or a Pull Request** containing the dbt project, tests, loaders, publish and dashboard scripts, pinned Docker setup and the DAG, so a clean machine can rebuild the marts and dashboards without calling DataForge.

---

## Technology Stack

| Layer | Technology | Purpose |
| :--- | :--- | :--- |
| **Backend Core** | FastAPI • Python 3.11 • Pydantic v2 | Async REST API, validation of every LLM output and API contract |
| **Orchestration** | LangGraph (`StateGraph`, Postgres checkpointer) | Stateful workflow with human-in-the-loop interrupts that survive restarts |
| **LLM & Embeddings** | Google Gemini (`gemini-3.5-flash-lite`, embeddings) | Modeler, Codegen and Optimizer agents with structured JSON output |
| **Transform** | dbt-core • dbt-duckdb • DuckDB | Building and measuring models in an isolated, per-run database |
| **SQL Analysis** | sqlglot • DuckDB profiling | Rule-based rewrites on compiled SQL, execution plans and metrics |
| **Job Queue** | PostgreSQL (`FOR UPDATE SKIP LOCKED`) | Leased jobs, retries and per-pipeline serialization without Redis |
| **Scheduler** | Apache Airflow 3 (LocalExecutor) | Scheduled reruns of approved pipelines from a fixed DAG template |
| **Relational DB** | PostgreSQL 16 • SQLAlchemy 2 • Alembic | App metadata, checkpoints, Airflow and Metabase databases, the warehouse |
| **Vector DB** | Qdrant | Few-shot retrieval of example dbt models, isolated from the evaluation set |
| **BI** | Metabase (REST API, read-only account) | Dashboards over the published marts |
| **Frontend SPA** | React 19 • Vite • TypeScript • plain CSS | Landing page, workspace, upload, run tracking and review gates |
| **Evaluation** | pytest • custom SQL comparator • golden datasets | Offline evaluation on OULAD and two public datasets |
| **Quality** | Ruff • mypy (strict) • Biome • pre-commit | Linting, typing and the repository's code conventions |

---

## Infrastructure & Ports

One PostgreSQL instance hosts four databases with separate roles: the app metadata, Airflow, Metabase, and the warehouse (written only by the `publisher` role, read by `metabase_reader`).

| Service | Compose service | Host port | Purpose |
| :--- | :--- | :--- | :--- |
| **Backend API** | `backend` | `8000` | REST API, OpenAPI docs at `/docs` |
| **Frontend (dev)** | `npm run dev` | `5173` | React SPA, proxies `/api` to the backend |
| **Metabase** | `metabase` | `3000` | Dashboards |
| **Airflow** | `airflow-api-server` | `8080` | Scheduler UI and API |
| **Qdrant** | `qdrant` | `6333` | Vector database |
| **PostgreSQL** | `postgres` | `5432` | All four databases |
| **Sandbox worker** | `sandbox-worker` | none | Internal `sandbox` network only |
| **Publisher** | `publisher` | none | Warehouse and Metabase writes |

---

## Quick Start Guide

### Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) with Compose
- [uv](https://docs.astral.sh/uv/) (installs Python 3.11 when missing) and Node.js 22
- A [Google Gemini API key](https://aistudio.google.com/)
- Optional: [pre-commit](https://pre-commit.com/) for the local hooks

### 1. Clone & Configure
```bash
git clone https://github.com/vinhnguyen161006/DataForge-Data-Pipeline-Generator-Agent.git
cd DataForge-Data-Pipeline-Generator-Agent

cp .env.example .env
cp backend/.env.example backend/.env
```

Set at least `DATAFORGE_GEMINI_API_KEY` and `METABASE_ADMIN_PASSWORD` in `.env`.

### 2. Launch the Full Stack with Docker Compose
```bash
docker compose up -d --build
```
> The `migrate` service applies Alembic migrations and creates the LangGraph checkpoint tables once; the backend, sandbox worker and publisher start only after it finishes.

### 3. Develop Locally
```bash
# Backing services only
docker compose up -d postgres qdrant metabase migrate

# Backend with auto-reload
cd backend
uv sync --locked
uv run --locked uvicorn --factory app.main:create_app --reload

# Frontend (separate terminal)
cd frontend
npm ci
npm run dev
```

- **Web app**: `http://localhost:5173`
- **API docs**: `http://localhost:8000/docs`
- **Accounts**: create one with `POST /api/auth/register` (password of at least 15 characters).

> In `npm run dev`, the sign-in page uses a development-only mock adapter so the UI can be explored without a backend (`linh@retail.co` / `dataforge-demo`). Run with `VITE_AUTH_ADAPTER=api` to sign in against the real backend. Production builds always use the real API and contain no mock code.

---

## Repository Structure

```text
DataForge/
├── assets/brand/              # Logo lockups for light and dark backgrounds
├── backend/
│   ├── app/
│   │   ├── api/               # FastAPI routes, DTOs, auth and role dependencies
│   │   ├── agents/            # Gemini client, Modeler, Codegen, Optimizer, prompts
│   │   ├── graph/             # LangGraph state, nodes, interrupts, builder
│   │   ├── services/          # Run lifecycle, approvals, batches
│   │   ├── ingest/            # CSV sniffing and raw file storage
│   │   ├── profiler/          # DataProfile: the only data description sent to the LLM
│   │   ├── codegen/           # Deterministic bronze, tests from approved constraints, SQL guard
│   │   ├── compare/           # Multiset equivalence and benchmark statistics
│   │   ├── optimizer/         # sqlglot rules and the deterministic judge
│   │   ├── publisher/         # Staging load, reconcile, atomic publish
│   │   ├── metabase/          # Idempotent card and dashboard builder
│   │   ├── export/            # Deterministic ZIP and Pull Request export
│   │   ├── jobs/              # Postgres job queue (SKIP LOCKED, leases, retries)
│   │   └── db/                # ORM models, sessions, checkpointer setup
│   ├── worker/                # Sandbox worker and publisher processes
│   ├── migrations/            # Alembic migrations
│   └── tests/                 # Unit and Postgres integration tests
├── frontend/
│   ├── public/fonts/          # Self-hosted Bodoni Moda, Inter, JetBrains Mono
│   └── src/                   # Pages, workspace shell, upload, run and gate components
├── airflow/                   # Airflow image, fixed DAG template, pinned dbt virtualenv
├── eval/                      # Offline evaluation suite and golden datasets
├── infra/postgres/            # Database and role initialization
├── docs/                      # Specification and architecture diagram
├── scripts/                   # Convention checker (no comments, ASCII-only code)
└── docker-compose.yml         # Postgres, Qdrant, Metabase, backend, workers, Airflow
```

---

## Testing & Quality Assurance

```bash
cd backend

# Unit tests (no services needed)
uv run --locked pytest -q

# Include the Postgres integration tests
export DATAFORGE_TEST_DATABASE_URL=postgresql+asyncpg://dataforge:dataforge@localhost:5432/dataforge_app
uv run --locked pytest -q

# The same checks CI runs
uv run --locked ruff check . ../airflow ../scripts
uv run --locked ruff format --check . ../airflow ../scripts
uv run --locked mypy app worker tests ../scripts/check_conventions.py
uv run --locked python ../scripts/check_conventions.py

cd ../frontend
npm run ci    # Biome, tsc --noEmit, vite build
```

| CI job | Checks |
| :--- | :--- |
| `conventions` | No comments in code, ASCII-only source files |
| `backend-lint` | `ruff format --check`, `ruff check`, strict mypy |
| `backend-test` | Postgres 16, `alembic upgrade head`, `alembic check`, checkpointer setup, pytest including integration tests |
| `frontend` | `npm ci`, Biome, `tsc --noEmit`, `vite build` |
| `images` | `docker compose config`, backend and Airflow images, `dbt --version` in the isolated venv, DAG import |
| `security` | gitleaks, `pip-audit` (backend and dbt lock), `npm audit` |

---


