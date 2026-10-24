# Khôi phục ứng dụng trước khi API sẵn sàng

Lifespan tạo engine, checkpoint pool, graph và context, rồi chờ recovery cùng lượt delivery đầu tiên thành công trước khi nhận request. Khi shutdown, delivery task được cancel và await trước khi đóng checkpoint pool và dispose engine.

## Đọc code

Các đường dẫn tính từ `backend/`.

| File | Vai trò |
|---|---|
| `app/main.py` | Tạo tài nguyên, một delivery task, chờ startup và dọn tài nguyên |
| `app/services/runs.py` | Recovery, đồng bộ projection, giao quyết định và kết quả job |
| `app/services/delivery_lifecycle.py` | Chờ ready/task exit/timeout, ghi nhận lỗi và join task |
| `app/core/readiness.py` | Trạng thái của delivery task trong một vòng đời API |
| `app/api/routes/health.py` | HTTP 503 nếu delivery đã bật nhưng không còn hoạt động sẵn sàng |
| `app/db/checkpointer.py` | Mở/đóng pool, kể cả khi mở kết nối ban đầu thất bại |

## Startup

```text
Tạo engine và mở checkpoint pool
  → tạo session factory, graph và context
  → tạo delivery task với startup_ready event
  → recover_pending_runs
  → deliver_resume_intents
  → deliver_finished_jobs
  → set startup_ready sau một chu kỳ thành công
  → lifespan xác nhận task còn chạy
  → log api resources ready và yield
  → delivery tiếp tục theo chu kỳ
```

`create_task()` chỉ lên lịch coroutine. `wait_for_delivery_startup()` chờ đồng thời event ready và task: task dừng sớm thì startup thất bại ngay; quá deadline thì báo timeout. Task chờ event luôn được dọn.

Recovery lỗi sẽ được thử lại ở tick tiếp theo. Recovery thành công chỉ chạy một lần trong mỗi delivery loop; quyết định và job được giao định kỳ. Một bước delivery lỗi trước khi ready sẽ giữ startup chưa sẵn sàng cho đến khi một chu kỳ thành công.

Không mở thêm loop từ router. Khi `job_delivery_enabled=false`, lifespan chủ động bỏ qua recovery/delivery và bước chờ; cấu hình này cũng được fixture test mặc định sử dụng.

## Checkpoint và projection

Mở saver không tự khôi phục `PipelineRun`. Checkpoint lưu điểm thực thi, còn `PipelineRun.status/current_step/pending/interrupt_id` là projection phục vụ polling.

| Trạng thái | Recovery xử lý |
|---|---|
| Run đã commit, chưa có checkpoint | Khởi động graph cho chính run đó |
| Chờ job chưa hoàn thành | Khôi phục WAITING_JOB, giữ job ID |
| Job hoàn thành khi API tắt | Lượt delivery đầu tiên giao đúng interrupt trước khi API ready |
| Chờ duyệt thiết kế hoặc trả lời câu hỏi | Đồng bộ pending/interrupt, giữ điểm chờ |
| Graph có bước dang dở, không có interrupt | Tiếp tục checkpoint bằng input None |
| Quyết định đã được chấp nhận nhưng chưa giao | Giao lại receipt đã commit vào đúng interrupt |

Run chờ Cổng 1 chưa có quyết định được chấp nhận sẽ không tự duyệt hoặc tạo approval. Recovery không gọi Modeler lại khi checkpoint đã giữ điểm chờ.

`run_lock` dùng PostgreSQL advisory lock để tuần tự hóa nhiều API process trên cùng run. Enqueue profile dùng idempotency key ổn định; delivery kiểm tra receipt trong checkpoint. Khôi phục lặp lại không tạo job, design version hoặc approval trùng.

## Lỗi runtime và shutdown

Delivery task kết thúc bất thường sau startup sẽ ghi log CRITICAL, giữ trạng thái failed và làm `GET /api/health` trả HTTP 503 với `{"status":"unavailable"}`. Health probe không tự khởi động lại process.

Shutdown có chủ đích không tạo log lỗi giả. Lỗi từ task đúng lúc shutdown hoặc trong cleanup được ghi nhận; task vẫn được join trước khi pool đóng. Log giám sát task ghi loại lỗi, không ghi chuỗi exception có thể chứa credential.

Nếu checkpoint pool không mở được, pool vẫn được đóng và engine vẫn được dispose.

## Cấu hình

| Biến môi trường | Mặc định | Ý nghĩa |
|---|---|---|
| DATAFORGE_JOB_DELIVERY_ENABLED | true | Bật recovery/delivery trong API |
| DATAFORGE_JOB_DELIVERY_INTERVAL_SECONDS | 2 | Khoảng chờ giữa các tick |
| DATAFORGE_JOB_DELIVERY_STARTUP_TIMEOUT_SECONDS | 120 | Ngân sách chờ recovery và lượt delivery ban đầu |

Hai khoảng thời gian phải hữu hạn và lớn hơn 0. Ngân sách startup cần đủ cho số run dang dở và công việc graph phải tiếp tục. Quá ngân sách sẽ làm startup thất bại và dọn tài nguyên.

Compose truyền các biến này riêng cho backend. `healthcheck.start_period` dùng cùng ngân sách startup để probe có thời gian chờ ứng dụng khôi phục.

## Kiểm thử

Chạy từ `backend/`:

```bash
.venv/bin/python -m pytest \
  tests/unit/test_app.py \
  tests/unit/test_application_lifespan.py \
  tests/unit/test_job_delivery_loop.py -q

export DATAFORGE_TEST_DATABASE_URL="postgresql+asyncpg://dataforge:dataforge@localhost:5432/dataforge_test"

.venv/bin/python -m pytest \
  tests/integration/test_application_recovery.py \
  tests/integration/test_job_delivery.py -q -rs
```

Unit test kiểm tra readiness, retry startup, timeout, cancellation, task exit trước/sau ready, health và thứ tự đóng tài nguyên bằng event/barrier.

Integration test tạo app mới với engine, graph và PostgreSQL checkpoint pool mới; đi qua lifespan và HTTP polling qua ASGI. Các trường hợp gồm run chưa khởi động, chờ job, kết quả hoàn thành khi API tắt, Cổng 1, clarification và hai startup đồng thời. Modeler dùng output xác định, không gọi dịch vụ LLM.

Bộ [run-recovery.md](run-recovery.md) đóng toàn bộ ứng dụng A đang chờ Cổng 1, mở ứng dụng B với tài nguyên mới, so sánh điểm chờ và gửi quyết định qua HTTP. Các trường hợp gồm approve, sửa rồi approve, return, request trùng và identity cũ. Diễn tập dừng process Compose và SIGKILL vẫn cần thực hiện riêng. Xem thêm [worker-lifecycle.md](worker-lifecycle.md) về giao kết quả sau crash.
