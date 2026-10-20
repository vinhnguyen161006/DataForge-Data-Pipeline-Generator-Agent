# Kiểm chứng tạo lượt chạy từ batch READY

Thực hiện ngày **20/10/2026**, cho mục C2 của Tú. Bộ [test_run_creation.py](../../backend/tests/integration/test_run_creation.py) dùng API batches/runs thật, PostgreSQL thật và LangGraph Postgres checkpointer thật.

## Chạy test

Tại thư mục backend trong Bash WSL:

~~~bash
set -a
source .env.upload-checks
set +a

.venv/bin/python -m pytest tests/integration/test_run_creation.py -q -rs
~~~

Chạy chung quyền C1 và tạo run C2:

~~~bash
.venv/bin/python -m pytest \
  tests/integration/test_runs.py \
  tests/integration/test_run_creation.py \
  -q -rs
~~~

Chỉ xem nhóm recovery:

~~~bash
.venv/bin/python -m pytest tests/integration/test_run_creation.py -k recovery -vv
~~~

DB test cần có application schema và bảng checkpoint đã setup theo hướng dẫn repository. Không đặt DATAFORGE_TEST_DATABASE_URL thì integration test sẽ skip; skip vì thiếu DB không tính là đạt. Không cần Gemini API hoặc worker để chạy bộ này.

## Phạm vi code đi kèm

Endpoint tạo run và validation còn thiếu khi bắt đầu viết test. Đã nối đúng phần hướng dẫn C2:

- RunCreate trim request_text và từ chối chuỗi rỗng/khoảng trắng.
- Engineer đúng project mới được tạo run.
- assert_batch_ready kiểm tra DB/manifest/marker/raw trước khi ghi PipelineRun.
- start_run tạo run và tự commit; route đọc RunOut, rồi giao drive_run cho BackgroundTasks.
- Background task nhận session factory và tài nguyên graph từ app.state, không giữ request session.
- Giữ contract HTTP hiện tại: POST tạo run trả 200; mỗi POST hợp lệ là một run độc lập.

Đã giữ một bản của import/validator bị ghép trùng. Không thêm dependency, migration hoặc thay model. Không thay service recovery, queue hoặc profiler để làm test xanh.

## Fixture và dữ liệu

RunCreationScenario tạo ba user: Engineer, Reviewer và Outsider; một project cùng batch hai CSV customers.csv/orders.csv. Batch được tạo, upload, confirm config và READY qua API thật. Raw/manifest/marker nằm trong thư mục tạm.

Mỗi test tạo một schema PostgreSQL tên run_creation_<UUID> trong DB test. SQLAlchemy schema_translate_map áp dụng cho toàn bộ application model, giúp recover_pending_runs quét đúng dữ liệu test đó và không xử lý run có sẵn trong public.

Application tables của schema tạm được tạo từ ORM metadata; CI vẫn kiểm chứng migration riêng. Fixture dọn đúng schema tự tạo bằng DropSchema và xóa đúng các thread checkpoint theo run ID của test. Không xóa database, schema public hoặc checkpoint của run khác.

Mỗi request và observer dùng session riêng với setup đã commit. Các test không dựa vào db_session rollback để chứng minh dữ liệu commit nhìn thấy từ connection khác.

Postgres saver dùng bảng checkpoint chung nhưng thread ID là UUID của run riêng từng test. Test recovery mở engine, graph, context và saver mới; test giữ interrupt đóng tài nguyên thực thi A trước khi mở B.

UnexpectedModeler ghi số lần bị gọi và báo lỗi nếu chạm tới Modeler. Tạo run phải dừng tại interrupt chờ job profile; chưa chạy profiler thật hoặc gửi dữ liệu vào LLM.

## Những test quan trọng nên đọc

| Test/nhóm | Điều được chứng minh |
|---|---|
| test_ready_batch_creates_committed_run_job_and_checkpoint | Session mới thấy run; job queue sandbox gắn đúng run; payload file/config đúng; checkpoint dùng thread_id=run_id và chờ đúng job |
| test_creation_rejects_empty_or_invalid_requirements_without_side_effects | 6 biến thể yêu cầu không hợp lệ trả 422, không thêm run/job/design/approval |
| test_creation_requires_project_engineer_even_for_a_valid_ready_batch | Thiếu token, Reviewer hoặc Outsider không tạo được run từ batch hợp lệ |
| test_creation_rejects_an_uploading_batch | File đủ và confirmed nhưng batch chưa READY vẫn bị từ chối |
| test_creation_rejects_inconsistent_ready_snapshots_without_creating_a_run | 13 biến thể manifest/marker/raw/metadata hỏng hoặc thiếu trả 409 trước khi tạo run |
| test_creation_reports_storage_outage_without_creating_a_run | Lỗi đọc manifest thật trả 503, không ghi run |
| test_http_response_and_committed_run_precede_background_graph_execution | Bắt sự kiện ASGI để chứng minh response đã gửi và session riêng thấy run trước khi graph bắt đầu |
| test_repeated_http_creation_intentionally_creates_independent_runs | Hai POST giống nhau tạo hai run/job riêng; API chưa có HTTP idempotency key |
| test_concurrent_http_creation_keeps_run_job_and_checkpoint_identities_separate | Hai POST đồng thời không lẫn run, yêu cầu phân tích, job hoặc checkpoint |
| test_profile_node_replay_reuses_the_original_job | Resume làm node profile chạy lại từ đầu nhưng giữ nguyên job_id và idempotency_key |
| test_recovery_starts_the_same_committed_run_when_background_kickoff_was_lost | Bỏ kickoff sau commit, mở tài nguyên mới và recovery tiếp tục đúng run đã lưu |
| test_recovery_reads_the_same_job_interrupt_after_closing_execution_resources | Đóng A, mở B: đọc cùng checkpoint/interrupt; recovery không enqueue lại hoặc gọi Modeler |
| test_recovery_reuses_a_job_committed_before_its_first_checkpoint | Có job bền vững nhưng chưa có checkpoint: recovery dùng lại job đó |
| test_failed_run_commit_does_not_schedule_graph_or_create_records | Commit thất bại trước khi ghi xong không chạy graph và không để lại run/job |
| test_ambiguous_successful_commit_preserves_a_recoverable_run | Commit đã thành công nhưng mất acknowledgement: run còn đó và recovery tiếp tục cùng ID |
| test_graph_kickoff_failure_marks_the_committed_run_failed | Enqueue lỗi được ghi thành FAILED; không để run RUNNING vô hạn trong ca lỗi này |

Fault injection chỉ thay kickoff/commit/enqueue hoặc thao tác đọc file tại ranh giới được kiểm tra. Test thành công và recovery dùng graph, queue, session và checkpointer thật.

## Điều chỉnh fixture C1

Khi endpoint bắt đầu rollback thật, một test C1 gửi nhiều request trong cùng db_session cần giữ setup qua các rollback đó. Đã đổi lần flush cuối setup thành commit.

db_session dùng join_transaction_mode=create_savepoint trong transaction ngoài của fixture. Commit này release savepoint setup, không commit transaction ngoài ra toàn database. Các request sau có savepoint mới để rollback; cuối test transaction ngoài vẫn rollback và dọn toàn bộ setup.

## Giới hạn bằng chứng

Đã kiểm chứng khoảng trống commit → kickoff và checkpoint chờ profile bằng các tài nguyên thực thi mới. Đây chưa phải diễn tập tắt backend process/Compose hoặc khôi phục Cổng 1 đầy đủ của FR-21.

BackgroundTasks vẫn là đường khởi động sớm. Recovery hiện chạy lúc startup; bộ test chưa chứng minh dispatcher retry liên tục hoặc hai backend cùng recovery/resume an toàn. Cần cơ chế serialize theo run và test nhiều backend ở phần điều phối tiếp theo.

Worker phải tự kiểm tra snapshot/payload khi thực thi ở D4. Test C2 chưa chứng minh worker profile/sandbox đã chạy hoặc đã khóa DuckDB.

Polling đã được kiểm chứng trong [run-polling.md](run-polling.md); clarifications/design-decision thành công và 409 theo trạng thái/interrupt tiếp tục ở C4. Không đánh dấu toàn bộ tuần 2 hoàn thành từ bộ test này.

## Kết quả chạy

| Kiểm chứng | Kết quả |
|---|---|
| Test C2 mới | **35 passed**, không skip |
| C1 + C2 trong toàn bộ regression | **100 passed**, không skip |
| Toàn bộ backend | **700 passed, 17 skipped**, 210,81 giây |
| Ruff check / format | Qua; 113 file được kiểm tra format |
| mypy strict | Qua, 105 source file |
| check_conventions.py | Qua |
| Alembic check trên DB test | Qua, không có schema drift |

17 skip gồm 16 TODO có sẵn ngoài phạm vi và test OULAD cần bật riêng. Không có test C1/C2 nào bị skip vì thiếu PostgreSQL.

Log và JUnit của lần regression cuối nằm local, được Git bỏ qua:

- backend/data/upload-checks/run-creation-regression.log.
- backend/data/upload-checks/run-creation-regression.xml.

Lệnh regression, từ backend sau khi nạp cấu hình DB test:

~~~bash
.venv/bin/python -m pytest -q -rs --junitxml=data/upload-checks/run-creation-regression.xml
~~~

Không chạy CI images/security hoặc nghiệm thu worker/FR-21 trong bước này.

Bổ sung C3: [Kiểm chứng GET trạng thái và polling](run-polling.md) ghi kết quả mới nhất và test tính chỉ đọc.
