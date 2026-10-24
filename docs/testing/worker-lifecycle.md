# Worker lifecycle và giao kết quả qua checkpoint

Worker tự nhận job từ queue PostgreSQL, giữ lease trong khi runner thực thi và ghi kết quả trước khi API resume graph. Runner và các giới hạn sandbox được mô tả trong [profile-runner.md](profile-runner.md).

## Đọc code theo thứ tự

Các đường dẫn dưới đây tính từ `backend/`.

| File | Trách nhiệm |
|---|---|
| `app/core/config.py` | Validate worker ID, khoảng heartbeat và ngân sách tài nguyên |
| `worker/main.py` | Engine/session factory, reclaim, claim, polling, SIGINT/SIGTERM và dispose |
| `worker/lifecycle.py` | Giám sát một attempt, heartbeat, thread runner và cập nhật cuối job |
| `worker/profile_preparation.py` | Kiểm tra quyền sở hữu còn hiệu lực và snapshot READY |
| `app/jobs/queue.py` | Transaction claim/heartbeat/complete/fail, retry và reclaim |
| `app/graph/nodes.py` | Enqueue idempotent, nhận đúng outcome và checkpoint receipt |
| `app/services/runs.py` | Giao kết quả vào đúng interrupt dưới PostgreSQL advisory lock |
| `app/main.py` | Khởi chạy delivery loop trong lifespan của API |

## Quyền sở hữu và heartbeat

Mỗi cập nhật queue kiểm tra đồng thời job ID, worker ID, attempt, trạng thái RUNNING và lease còn hạn theo đồng hồ PostgreSQL. Claim tăng attempt; fail và reclaim không tự tăng attempt.

Worker bắt đầu heartbeat ngay sau claim, trước khi chuẩn bị snapshot. Chuẩn bị có thể kiểm tra file lớn; runner chạy bằng `asyncio.to_thread()`, nên event loop vẫn gia hạn lease. Không giữ transaction hoặc chia sẻ AsyncSession giữa các task trong suốt thời gian subprocess chạy.

Ví dụ mặc định: lease 300 giây, heartbeat 60 giây, timeout thao tác queue 10 giây, subprocess timeout 900 giây. Heartbeat và timeout DB phải nằm trong lease. Subprocess timeout không thay thế heartbeat.

Heartbeat và complete/fail dùng một khóa asyncio trong attempt. Sau khi commit trạng thái cuối thành công, heartbeat được dừng trước lần gia hạn tiếp theo. Nhờ vậy, worker không báo mất quyền do chính lần complete vừa thực hiện.

## Dừng runner và retry

Runner nhận `threading.Event`; coroutine nhận các `asyncio.Event` riêng. Hủy task bọc `to_thread()` không tự kết thúc thread hoặc child.

Khi shutdown hoặc mất quyền, supervisor đặt stop event, chờ runner thu hồi subprocess rồi mới kết thúc lifecycle. Workspace theo job/attempt tránh việc attempt cũ ghi đè artifact của attempt mới.

| Tình huống | Xử lý |
|---|---|
| Thành công | Complete bằng đúng owner/attempt, lưu dictionary DataProfile trực tiếp |
| Kind chưa hỗ trợ | Fail với `unsupported_job_kind`, không retry |
| Payload, batch, snapshot hoặc protocol sai | Fail bằng mã lỗi, không retry tự động |
| I/O tạm thời EAGAIN, EBUSY, ETIMEDOUT | Fail retryable, queue áp dụng backoff và max_attempts |
| Timeout hoặc child_failed | Không mặc định retry vì cùng dữ liệu/ngân sách có thể tiếp tục lỗi |
| Mất quyền | Dừng runner, bỏ kết quả, không complete/fail attempt cũ |
| Heartbeat/ghi cuối lỗi DB hoặc timeout | Dừng runner, để lease/recovery xử lý; không đoán commit thất bại rồi gọi fail |
| SIGINT/SIGTERM | Ngừng claim, dừng runner, fail retryable nếu còn quyền, đóng engine |
| Hủy task ngoài lifecycle hoặc SIGKILL | Không đảm bảo ghi trạng thái cuối; lease hết hạn để reclaim |

Không có vòng retry runner độc lập. Mã lỗi và định danh job/run/worker/attempt được ghi log; không ghi toàn bộ payload, environment, dòng dữ liệu hoặc chuỗi lỗi DB có credential.

## Delivery sau crash

API đã có một delivery loop trong lifespan. Recovery lúc khởi động được thử lại ở tick kế tiếp nếu lỗi, cho đến khi thành công. Worker không chạy graph hoặc gọi Modeler.

Profile node dùng idempotency key `profile:<run_id>`, kiểm tra outcome khớp job đang chờ, validate DataProfile và lưu `consumed_job_ids` cùng output của node vào checkpoint. Job thất bại cũng có receipt cùng trạng thái lỗi.

Delivery lấy lại job từ DB sau khi có `run_lock`, rồi đối chiếu checkpoint:

1. Chưa có checkpoint đúng run: giữ kết quả chưa giao để recovery xử lý.
2. Có bước graph chưa hoàn tất và không có interrupt: tiếp tục checkpoint bằng input `None`.
3. Có receipt: đồng bộ projection khi cần và đánh dấu delivered, không đưa outcome vào interrupt kế tiếp.
4. Đang chờ đúng job ID và kind: validate result, cập nhật projection RUNNING, resume bằng ID interrupt cụ thể.
5. Chỉ đánh dấu delivered sau khi đọc lại checkpoint và thấy receipt.

Do đó, crash sau cập nhật PipelineRun nhưng trước resume vẫn giao lại được. Crash sau checkpoint nhưng trước sync/delivered không gửi profile vào Cổng 1 hoặc gọi lại Modeler đã hoàn tất và được checkpoint.

Checkpoint cũ có profile nhưng chưa có receipt được nhận diện bằng profile đã lưu và idempotency key duy nhất của run. Checkpoint chưa chứng minh đã nhận kết quả thì không được đánh dấu delivered chỉ vì PipelineRun đang RUNNING.

Kết quả profile sai schema được giữ undelivered và ghi log để điều tra, không resume graph. Delivery phân trang theo job ID, nên một trang đầy các job chưa giao được không chặn job hợp lệ phía sau.

PostgreSQL advisory lock tuần tự hóa nhiều API process. Receipt và checkpoint giải quyết cửa sổ crash sau khi process nhả khóa. Việc gọi LLM bị ngắt trước khi output được checkpoint vẫn có thể phải thực hiện lại khi khôi phục; không có bảo đảm gọi dịch vụ ngoài đúng một lần ở cửa sổ đó.

## Chạy worker

Trong terminal WSL/Linux, từ thư mục `backend/`, dùng `.env` với app database và storage giống API:

```bash
DATAFORGE_WORKER_ID=sandbox-local-1 .venv/bin/python -m worker.main
```

Mỗi worker đang chạy cần ID riêng. Child chỉ nhận env allowlist từ sandbox; không chuyển app DB, warehouse, JWT hoặc khóa LLM vào child.

Các cấu hình mới nằm trong `backend/.env.example`. DuckDB memory 256 MiB nằm trong giới hạn address space của child 2048 MiB. RLIMIT_NPROC mặc định 4096 tính theo UID Linux, không phải tổng process trong container; Compose vẫn giới hạn cả container bằng `pids_limit: 256`.

Compose đặt `stop_grace_period: 30s` cho worker. Khi tăng timeout DB, cần điều chỉnh grace period để đủ thời gian dừng child, ghi trạng thái và dọn heartbeat.

## Kiểm thử

Dùng database test riêng đã chạy migration và setup checkpointer. Từ `backend/`:

```bash
.venv/bin/python -m pytest \
  tests/unit/test_worker_lifecycle.py \
  tests/unit/test_job_delivery_loop.py -q

export DATAFORGE_TEST_DATABASE_URL="postgresql+asyncpg://dataforge:dataforge@localhost:5432/dataforge_test"

.venv/bin/python -m pytest \
  tests/integration/test_worker_loop.py \
  tests/integration/test_job_delivery.py -q -rs
```

Fixture ứng dụng mặc định tắt background delivery. Test delivery chủ động gọi service; test toàn luồng tự khởi chạy worker polling và API delivery loop.

Test bao phủ: giữ lease qua hạn ban đầu, mất quyền, complete không rõ commit, shutdown/cancel, thu hồi child thật, reclaim sang workspace attempt mới, hai API pool, schema sai, enqueue replay, crash tại các điểm commit/checkpoint/acknowledgement và profile thật đến Cổng 1. Các test crash dùng checkpointer PostgreSQL và mở pool/checkpointer mới để đọc lại trạng thái bền vững.
