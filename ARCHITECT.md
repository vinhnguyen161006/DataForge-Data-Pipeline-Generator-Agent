# Kiến trúc DataForge

Tài liệu này ghi các quy tắc **ranh giới** mà code phải tuân theo. Yêu cầu nghiệp vụ nằm ở [docs/đặc tả.md](docs/đặc tả.md), quy ước làm việc ở [CLAUDE.md](CLAUDE.md).

## 1. Tiến trình và quyền

| Tiến trình | Entry | Settings | Được làm | Không được làm |
|---|---|---|---|---|
| API | `uvicorn --factory app.main:create_app` | `ApiSettings` | Nhận request, quản lý trạng thái, chạy LangGraph, gọi Gemini | Chạy mã sinh ra, ghi warehouse |
| Migrate | `alembic upgrade head` + `python -m app.db.checkpointer` | `ApiSettings` | Tạo/nâng schema `dataforge_app` và bảng checkpointer | Chạy lúc có request |
| Sandbox worker | `python -m worker.main` | `WorkerSettings` | Chạy dbt/DuckDB do LLM sinh trong tiến trình con bị giới hạn | Giữ DSN warehouse, ra Internet (mạng `sandbox` là `internal`) |
| Publisher | `python -m worker.publisher_main` | `PublisherSettings` | Ghi warehouse, gọi Metabase API | Chạy mã do LLM sinh |
| Airflow | `airflow scheduler` / `dag-processor` / `api-server` | biến `AIRFLOW__*` | Chạy lại pipeline đã duyệt bằng `/opt/dbt-venv/bin/dbt` | Giữ DSN warehouse, nạp Python tùy ý |

## 2. Quy tắc phụ thuộc giữa package

```
api ──> services ──> graph ──> agents ──> (Gemini)
                      │  └──> codegen, profiler, compare, optimizer, jobs
                      └──> jobs (enqueue) ──> worker (qua bảng jobs, không import trực tiếp)
worker ──> profiler, compare, codegen, publisher, metabase
```

- `profiler`, `compare`, `optimizer.judge`, `codegen`, `publisher`, `metabase`, `worker` **không import** `app.agents` (trừ `app.agents.schemas`).
- `app.agents` chỉ nhận `DataProfile`; không bao giờ nhận đường dẫn file hay dòng dữ liệu.
- `app.graph.builder.build_graph` không import FastAPI; test, worker và eval có thể dựng graph với `InMemorySaver`.
- Chỉ `worker/publisher_main.py` dùng `PublisherSettings`.

## 3. Ba file `schemas.py`

| File | Vai trò | Ai dùng |
|---|---|---|
| `app/api/schemas.py` | Hợp đồng HTTP (request/response DTO) | Router và frontend (`src/api/types.ts` phải khớp) |
| `app/agents/schemas.py` | Structured output của LLM, gồm `DataDesign` được duyệt ở Cổng 1 | Agent, codegen, graph |
| `app/profiler/schemas.py` | Hồ sơ dữ liệu nội bộ, thứ duy nhất về dữ liệu được gửi cho LLM | Profiler, Modeler |

Không import chéo DTO HTTP vào agent hay ngược lại. Khi cần chuyển đổi, viết hàm map ở `services/`.

## 4. Chủ sở hữu schema của từng database

Một instance Postgres, mỗi database chỉ có **một** chủ sở hữu schema:

| Database | Chủ sở hữu | Cách migrate |
|---|---|---|
| `dataforge_app` (bảng ứng dụng) | Alembic | `backend/migrations/`; `app/db/models.py` là nguồn |
| `dataforge_app` (bảng `checkpoint*`) | LangGraph | `AsyncPostgresSaver.setup()`; `migrations/env.py` bỏ qua qua `include_name` |
| `airflow` | Airflow | `airflow db migrate` (service `airflow-init`) |
| `metabase` | Metabase | Tự migrate khi khởi động |
| `dataforge_warehouse` | Publisher | Schema sinh động theo phiên bản; không dùng Alembic |

## 5. Mạng Compose

- `default`: mọi service.
- `sandbox` (`internal: true`): chỉ `postgres` và `sandbox-worker`. Sandbox worker không có đường ra Internet và không thấy Qdrant, Metabase, Airflow.
