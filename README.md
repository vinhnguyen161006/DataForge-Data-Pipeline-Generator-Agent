# DataForge

An agent that turns raw CSV files and a plain-language analysis request into a working data warehouse, a Metabase dashboard set, and a standalone dbt project.

Onboarding a new data source involves repetitive work: profiling, writing dbt models and tests, building the DAG, tuning queries and building dashboards. DataForge automates that work and keeps humans in charge of the decisions that need business judgment (grain, metric definitions, star schema).

## Overview

![DataForge architecture](docs/diagram.png)

Input: **CSV files + a natural-language request**. Output:

1. A **warehouse** (marts on Postgres).
2. A set of **Metabase dashboards**.
3. The **full pipeline source** as a dbt project that runs on its own (ZIP or Pull Request).

Design principles:

- **LLMs propose, deterministic tools judge.** Generated code is verified by running it and comparing results.
- **The optimizer keeps a rewrite only if it is both faster and equivalent** on a test dataset.
- **Two mandatory human approval gates.** Generated code never runs inside the backend process, and the system never touches the user's production environment.

### Pipeline

```
CSV + request
  -> Profiler          (deterministic)  statistical profile of the data
  -> Modeler           (LLM)            data design; asks the user when information is missing
  -> [Gate 1]          Engineer approves the design
  -> Codegen           (LLM)            dbt models + tests + DAG config
  -> Isolated worker   (deterministic)  run and measure
       <-> Optimizer   (LLM + rules)    propose rewrite -> rerun -> compare
  -> [Gate 2]          Reviewer approves code + evidence
  -> Publisher         (deterministic)  load staging -> reconcile -> publish to Postgres
  -> Dashboard         (deterministic)  Metabase cards + dashboard -> link
```

- dbt models have three layers: **bronze** (source as-is), **silver** (typed, deduplicated, bad rows quarantined with reasons), **mart** (fact + dimensions per the approved design).
- Approvals are bound to one exact version. Editing code invalidates the approval.
- Only statistical profiles are sent to the LLM, never raw rows.
- Only the publisher can write to the warehouse; Metabase reads with a read-only account.

More detail: [ARCHITECT.md](ARCHITECT.md) (boundaries), [CLAUDE.md](CLAUDE.md) (rules and conventions), [docs/](docs/) (specification).

## Tech stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, Python 3.11, Pydantic v2 |
| Orchestration | LangGraph (Postgres checkpointer) |
| LLM / embeddings | Google Gemini (`gemini-3.5-flash-lite`, `gemini-embedding-001`) |
| Transform | dbt-core, dbt-duckdb, DuckDB |
| SQL analysis | sqlglot, DuckDB profiling |
| Scheduler | Apache Airflow 3 (LocalExecutor) |
| Databases | PostgreSQL (SQLAlchemy, Alembic), Qdrant |
| Publish / export | psycopg `COPY`, GitHub API, ZIP |
| BI | Metabase (REST API) |
| Frontend | React 19, Vite, TypeScript, Monaco editor |
| Eval | pytest, custom SQL comparator, golden datasets |
| Deploy | Docker Compose, Vercel (static SPA) |

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (installs Python 3.11 automatically if missing)
- Node.js 22
- Docker with Compose
- Git and [pre-commit](https://pre-commit.com/)

## Installation

1. Clone the repository and enter it:

   ```bash
   git clone https://github.com/vinhnguyen161006/DataForge-AI_Agent.git
   cd DataForge-AI_Agent
   ```

2. Install backend dependencies:

   ```bash
   cd backend
   cp .env.example .env
   uv sync --locked
   cd ..
   ```

3. Install frontend dependencies:

   ```bash
   cd frontend
   npm ci
   cd ..
   ```

4. Install the git hooks:

   ```bash
   pre-commit install
   ```

## Usage

### Run the full stack with Docker Compose

From the repo root:

```bash
cp .env.example .env
docker compose up -d --build
```

Set `DATAFORGE_GEMINI_API_KEY` and `METABASE_ADMIN_PASSWORD` in `.env` first. The `migrate` service runs Alembic and the checkpointer setup once; the backend, worker and publisher start after it finishes.

| Service | URL |
|---|---|
| Backend API | http://localhost:8000 |
| Metabase | http://localhost:3000 |
| Airflow | http://localhost:8080 |
| Qdrant | http://localhost:6333 |
| Postgres | localhost:5432 |

### Develop the backend on your machine

Start only the backing services, then run the API with auto-reload:

```bash
docker compose up -d postgres qdrant metabase migrate
cd backend
uv run --locked uvicorn --factory app.main:create_app --reload
```

### Run the tests

```bash
cd backend
uv run --locked pytest -q
```

Unit tests need no services. To include the integration tests, start Postgres and set:

```bash
export DATAFORGE_TEST_DATABASE_URL=postgresql+asyncpg://dataforge:dataforge@localhost:5432/dataforge_app
```

### Run the frontend

```bash
cd frontend
npm run dev
```

The dev server proxies `/api` to `http://localhost:8000`.

### Checks before committing

```bash
cd backend
uv run --locked ruff check . ../airflow ../scripts
uv run --locked ruff format --check . ../airflow ../scripts
uv run --locked mypy app worker tests ../scripts/check_conventions.py
uv run --locked python ../scripts/check_conventions.py
cd ../frontend
npm run ci
```

## Features and roadmap

| Area | Status |
|---|---|
| Project skeleton, settings, ORM models, migrations, Compose, CI | Done |
| CSV ingest and profiler | Planned |
| Modeler, Gate 1, Codegen | Planned |
| Isolated worker, Optimizer, Gate 2 | Planned |
| Publisher, Metabase dashboards | Planned |
| Airflow scheduled reruns, ZIP / Pull Request export | Planned |
| Offline evaluation on golden datasets (OULAD + two public sets) | Planned |

The schedule runs from 2026-10-02 to 2026-11-12; see [WORKLOG.md](WORKLOG.md). The first version deliberately supports only full-snapshot replacement, SQL rewrites on DuckDB, and three card types (KPI, line, bar).

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | FastAPI app, LangGraph pipeline, workers, Alembic migrations |
| `airflow/` | Airflow image, fixed DAG template, pinned dbt environment |
| `frontend/` | React SPA |
| `eval/` | Offline evaluation suite and golden datasets |
| `infra/` | Postgres init (databases and roles) |
| `docs/` | Specification and diagrams |
| `scripts/` | Internal tooling (convention checker) |

## Contributing

1. Pick a task from [WORKLOG.md](WORKLOG.md). Each module has one owner; open a pull request and ask the owner to review changes to modules you do not own.
2. Create a branch and keep CI green: `conventions`, `backend-lint`, `backend-test`, `frontend`.
3. Follow the code conventions in [CLAUDE.md](CLAUDE.md) section 10: English only, no comments, ASCII-only source, pinned dependencies, Alembic migration for any schema change.
4. Report bugs and ideas through [GitHub Issues](https://github.com/vinhnguyen161006/DataForge-AI_Agent/issues). Security problems: see [SECURITY.md](SECURITY.md).

## License

No license has been chosen yet, so all rights are reserved by the authors.

## Contact

Open an issue on [GitHub](https://github.com/vinhnguyen161006/DataForge-AI_Agent/issues), or reach the maintainers [@vinhnguyen161006](https://github.com/vinhnguyen161006) and [@Choco2006](https://github.com/Choco2006).
