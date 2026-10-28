# Rà schema và bằng chứng kiểm chứng Tuần 1

- **Người thực hiện:** Tú.
- **Ngày đối chiếu mã và tài liệu:** 16/10/2026.
- **Phạm vi:** các bảng ứng dụng phục vụ auth/project roles, batch, run, approval, phiên bản mã, execution report và queue.
- **Cách thực hiện lần này:** đọc mã, đối chiếu ORM với baseline, đọc artifact có sẵn và tổng hợp log Tú đã cung cấp trong phần F1. Không chạy lại pytest, Alembic, benchmark hoặc CI; không kết nối hay thay đổi database.

## 1. Kết luận

**Không cần migration mới để bổ sung bảng/cột cho phạm vi rà schema Tuần 1.** `batches`, `pipeline_runs` và `approvals` cùng các bảng liên quan đã được khai báo trong [models.py](../../backend/app/db/models.py) và được tạo bởi [baseline e41abe5a02f9](../../backend/migrations/versions/20260929_e41abe5a02f9_baseline.py).

Đối chiếu tĩnh bằng AST cho thấy ORM và baseline cùng có **14 bảng**, không có tên bảng/cột chỉ xuất hiện ở một phía. Các khóa, kiểu dữ liệu và index liên quan dưới đây đã được đọc đối chiếu. Đây là kết luận về khai báo và nhu cầu migration trong phạm vi hiện tại; không phải chứng nhận mọi quy tắc nghiệp vụ đã được thực thi.

Auth và queue **đã có triển khai và test tích hợp PostgreSQL**. Phần cần xác minh lại khi đổi code hoặc database là kết quả chạy ở môi trường đích, không được ghi thành thiếu code. Log F1 đã có kết quả pytest và Alembic ở mục 5; chưa có log mới gắn với commit hiện tại hoặc kết quả CI.

## 2. Bảng đối chiếu ORM và baseline

Số cột dưới đây đã tính cả `created_at` từ `TimestampMixin`. Mọi bảng trong bảng đối chiếu đều tồn tại ở cả ORM và baseline.

| Bảng | Cột đã có | Khóa / ràng buộc đã có | Kết luận Tuần 1 |
|---|---|---|---|
| `batches` — 5 cột | `id`, `project_id`, `status`, `schema_fingerprint`, `created_at` | PK `id`; FK đến projects; enum status `uploading/ready`; fingerprint cho phép null | Có trạng thái lô và nơi lưu fingerprint; không thiếu bảng batch |
| `source_files` — 9 cột | `id`, `batch_id`, `filename`, `storage_path`, `sha256`, `size_bytes`, `read_config`, `read_config_confirmed`, `created_at` | PK; FK đến batches; read config dạng JSONB trên PostgreSQL; các trường mô tả file và xác nhận không null | Có cấu hình đọc đã xác nhận và định danh file nguồn; không cần thêm cột read config vào batches |
| `pipeline_runs` — 10 cột | `id`, `project_id`, `batch_id`, `request_text`, `status`, `current_step`, `pending`, `error`, `updated_at`, `created_at` | PK; FK project/batch; enum có running, các trạng thái chờ, published và failed; pending dạng JSONB | Có định danh lượt chạy, trạng thái chờ, lỗi và timestamps; không thiếu bảng runs |
| `approvals` — 11 cột | `id`, `project_id`, `run_id`, `gate`, `fingerprint`, `fingerprint_parts`, `decision`, `approver_id`, `independent_review`, `comment`, `created_at` | PK; FK đến project/run/user; enum gate `design/code`, decision `approved/returned`; fingerprint và snapshot parts không null | Có nơi lưu người duyệt, dự án, cổng và phiên bản được duyệt; không cần thêm bảng approvals |
| `design_versions` — 7 cột | `id`, `run_id`, `version`, `content`, `content_hash`, `edited_by_user`, `created_at` | PK; FK đến run; UNIQUE `(run_id, version)`; content dạng JSONB | Có nội dung và hash của phiên bản thiết kế |
| `code_versions` — 9 cột | `id`, `run_id`, `design_version_id`, `version`, `storage_path`, `code_hash`, `tests_hash`, `origin`, `created_at` | PK; FK run/design version; UNIQUE `(run_id, version)`; enum origin | Có liên kết thiết kế và hash mã/test của phiên bản |
| `execution_reports` — 7 cột | `id`, `code_version_id`, `batch_id`, `job_id`, `report`, `report_hash`, `created_at` | PK; FK code version/batch/job; report dạng JSONB | Có bằng chứng gắn với mã, dữ liệu và job thực thi |
| `jobs` — 18 cột | `id`, `queue`, `kind`, `payload`, `serial_key`, `idempotency_key`, `status`, `attempts`, `max_attempts`, `run_after`, `locked_by`, `lease_expires_at`, `result`, `last_error`, `delivered`, `run_id`, `finished_at`, `created_at` | PK; FK run; UNIQUE idempotency key; index status/serial key; unique partial index `uq_jobs_running_serial_key` khi running và key không null | Có dữ liệu cho enqueue, claim, lease, retry, recovery và serial key; index quan trọng đã có trong baseline |

Các bảng auth/project `users`, `projects`, `project_members` cũng có trong cả hai phía. Email và project slug có unique constraint. Membership có PK ghép `(project_id, user_id, role)`, nên một role được gắn theo đúng project.

## 3. Những hợp đồng không được suy ra chỉ từ schema

### Batch và manifest

[services/batches.py](../../backend/app/services/batches.py) dự kiến chỉ đánh dấu READY khi đủ file bắt buộc và cấu hình đọc đã xác nhận; các hàm nghiệp vụ ở module này vẫn là stub tại thời điểm rà.

Danh sách `required_files` nằm trong `DataDesign.update_policy` ở [agents/schemas.py](../../backend/app/agents/schemas.py), và thiết kế được lưu trong `design_versions.content`. [Storage](../../backend/app/ingest/storage.py) quy định file raw và marker `_READY` trên volume. Vì vậy, chưa có căn cứ yêu cầu thêm bảng manifest hoặc cột `required_files` vào batch chỉ để lặp lại hợp đồng hiện có.

Cần kiểm chứng khi triển khai dịch vụ: đủ file thuộc đúng batch, xác nhận cấu hình đọc, tính fingerprint, tính nhất quán giữa trạng thái DB và marker. Enum READY không tự bảo đảm các điều kiện này.

### Run và checkpoint

`pipeline_runs` lưu trạng thái nghiệp vụ; [PipelineState](../../backend/app/graph/state.py) và checkpointer lưu trạng thái thực thi đồ thị. Hai phần có phạm vi khác nhau; checkpoint không thay thế bảng run.

[migrations/env.py](../../backend/migrations/env.py) chỉ phản chiếu các bảng được khai báo trong ORM. Các bảng checkpoint do LangGraph quản lý bị loại khỏi phạm vi Alembic; sự tồn tại của chúng không phải lý do tạo migration ứng dụng mới.

### Approval và phiên bản cụ thể

[VersionParts](../../backend/app/versioning.py) đã khai báo `design_hash`, `code_hash`, `tests_hash`, `batch_id`, `execution_job_id` và `report_hash`. `approvals.fingerprint_parts` có nơi lưu snapshot này; fingerprint có nơi lưu giá trị hash chung.

Việc tính fingerprint, ghi snapshot, kiểm tra quyền duyệt, independent review và vô hiệu hóa approval khi phiên bản thay đổi vẫn cần triển khai/kiểm chứng trong [services/approvals.py](../../backend/app/services/approvals.py) và versioning; các hàm này hiện còn stub. Đây là phần nghiệp vụ chưa hoàn thành, không phải thiếu bảng approvals. JSONB không tự kiểm tra hợp đồng VersionParts; các FK riêng cũng không tự bảo đảm mọi project/run/version trong yêu cầu thuộc cùng một chuỗi nghiệp vụ.

### Role theo project và ownership của queue

PK membership cho phép một user có hai role, phục vụ SOLO. [add_member()](../../backend/app/api/routes/projects.py) khóa hàng project và từ chối role đối lập trong TEAM. Không thêm UNIQUE `(project_id, user_id)` chung cho mọi project, vì sẽ chặn trường hợp SOLO đã thiết kế.

Với queue, unique partial index là bảo vệ ở DB cho running serial key. Các điều kiện lease, attempt, trạng thái, worker sở hữu và thời điểm kiểm tra thuộc logic [jobs/queue.py](../../backend/app/jobs/queue.py); phải được kiểm chứng bằng transaction PostgreSQL thật.

## 4. Trạng thái lịch sử migration

Migration hoạt động hiện tại là baseline `e41abe5a02f9`, có `down_revision = None`.

Scaffold `39e652e87810` chỉ có `pass` trong upgrade/downgrade và trỏ đến revision `dac54733a09a` không có trong repo. File đã được giữ dưới đuôi `.py.disabled`, nên Alembic không nạp nó. Đây là cách tạm loại scaffold lỗi khỏi chuỗi; cần thống nhất với nhóm cách xử lý file này trước bàn giao.

Trong quá trình F1, Tú đã cung cấp kết quả đọc trực tiếp:

```text
Database revisions: ('dac54733a09a',)
Schema differences: []
```

Sau hướng dẫn đồng bộ dấu revision, log tiếp theo ghi `e41abe5a02f9 (head)` và `No new upgrade operations detected.` Việc cập nhật dấu revision không tạo lại schema; không dùng kết quả này để khẳng định migration đã được chạy từ database trống.

**Quyết định cho lần rà này:** không sửa baseline, không tạo migration rỗng mới, không cập nhật schema hoặc dấu revision của bất kỳ database nào. Nếu hợp đồng dữ liệu đổi hoặc xuất hiện schema drift thực tế, cần revision mới có thay đổi cụ thể, review và kiểm chứng trên DB thử nghiệm.

## 5. Bằng chứng auth/queue và kiểm chứng đã nhận

| Nội dung | Bằng chứng | Kết luận và giới hạn |
|---|---|---|
| Auth và phân quyền theo project | Các hàm trong security, deps, routes/auth.py và routes/projects.py đã có thân hàm thực tế; có test_auth.py, test_deps.py, test_projects.py, test_session_dependency.py | Đã triển khai và có test tích hợp; không phân loại là thiếu code |
| Queue | enqueue, claim_next, heartbeat, complete, fail, reclaim_expired đã triển khai; có test_queue.py kiểm tra concurrency/lease/serial key/stale owner | Đã có code và test tích hợp; hiệu lực kiểm chứng phụ thuộc kết quả chạy thật |
| PostgreSQL fixture | [tests/conftest.py](../../backend/tests/conftest.py) đọc DATAFORGE_TEST_DATABASE_URL; [fixture tích hợp](../../backend/tests/integration/conftest.py) tạo async engine/session thật; test queue dùng nhiều transaction và session độc lập | Không thay PostgreSQL bằng SQLite/mock để chứng minh khóa hàng |
| Full suite do Tú chạy ở F1 | `458 passed, 16 skipped in 38.46s`; 16 skip đều là TODO ở acceptance_pipeline, acceptance_rules, compare và guards | Có bằng chứng lần chạy trước đã thực thi auth/project/session/deps/queue; các placeholder bị skip không được tính hoàn thành |
| Ruff và mypy trong log F1 | `88 files already formatted`; `All checks passed!`; mypy sạch 83 source files và script profiling 1 file | Kết quả của lần chạy đã cung cấp; không phải lần chạy mới ngày 16/10 |
| Alembic trong log F1 | `e41abe5a02f9 (head)`; `No new upgrade operations detected.` | Database ứng dụng lúc đó ở head, không có drift được autogenerate phát hiện trong phạm vi cấu hình |
| Conventions | Log trước báo một comment ở test_security.py:56; comment đã được bỏ sau đó | Chưa có log chạy lại conventions trong thông tin đã nhận |
| Database mới / CI | Chưa có log CI hoặc kết quả tạo lại schema từ database trống trong lần rà này | Không kết luận là chưa làm; cần log để xác nhận |

Các kết quả trên lấy từ log Tú gửi trong phiên hướng dẫn F1 trước lần rà này. Log chưa kèm commit ID và định danh database đã che thông tin nhạy cảm. Vì vậy, không suy ra rằng code hiện tại ngày 16/10/2026 hoặc mọi database đều đã đạt kiểm tra.

`alembic check` sử dụng `DATAFORGE_APP_DATABASE_URL`; integration test sử dụng `DATAFORGE_TEST_DATABASE_URL`. Kết quả ở một database không chứng minh schema của database còn lại. Cấu hình so sánh có `compare_type=True` và bộ lọc bảng ORM, không bật `compare_server_default`; log sạch không thay việc rà enum, defaults, ràng buộc nghiệp vụ và hành vi dữ liệu.

## 6. Lệnh xác minh lại khi bàn giao

Tú chạy từ `backend/` khi cần log mới gắn với phiên bản bàn giao; báo cáo này không tự chạy các lệnh:

```bash
git rev-parse HEAD
uv run --locked --env-file ../.env pytest tests/unit/test_security.py tests/integration/test_session_dependency.py tests/integration/test_deps.py tests/integration/test_auth.py tests/integration/test_projects.py tests/integration/test_queue.py -q -rs --tb=short
uv run --locked --env-file ../.env pytest -q -rs --tb=short
uv run --locked --env-file ../.env alembic heads
uv run --locked --env-file ../.env alembic current
uv run --locked --env-file ../.env alembic check
uv run --locked python ../scripts/check_conventions.py
```

Ghi kèm thời điểm, commit, môi trường PostgreSQL, pass/fail/skip và nguyên nhân; không ghi secret hoặc URL chứa mật khẩu. Kiểm chứng migration từ DB trống và PR/CI được ghi riêng khi có bằng chứng. Không tự áp dụng schema hoặc reset database để hoàn thành checklist.

Kết quả profiling liên quan được cập nhật từ artifact E4 tại [báo cáo DuckDB](../spikes/duckdb-profiling.md).
