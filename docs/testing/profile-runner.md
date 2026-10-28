# Profile runner: từ snapshot READY đến DataProfile

Runner thực thi một job profile bằng Python child có giới hạn tài nguyên, giới hạn filesystem và DuckDB riêng. Kết quả là thống kê thực từ module profiler dùng chung.

## Đọc code theo từng lớp

| Thứ tự | File | Điều cần hiểu |
|---|---|---|
| 1 | `app/jobs/profile.py` | Payload queue chỉ mang project/batch/digest/version |
| 2 | `worker/profile_preparation.py` | Xác minh job đang RUNNING, owner/attempt/lease, run và READY trong DB |
| 3 | `app/ingest/snapshot.py` | Kiểm tra manifest, marker, bộ file, hash và kích thước |
| 4 | `worker/profile_protocol.py` | Context đã kiểm chứng và request/response JSON có version |
| 5 | `worker/runner.py` | Workspace, staging, chạy child, xử lý lỗi và kết quả |
| 6 | `worker/profile_child.py` | Entrypoint cố định, không khởi tạo settings đọc .env |
| 7 | `worker/filesystem.py` | Hạn chế filesystem trước khi import DuckDB/tạo thread |
| 8 | `worker/duckdb_runtime.py` | Load CSV → materialize → lockdown → close |
| 9 | `app/profiler/profile.py` | Thống kê cột, khóa và quan hệ trên connection được cấp |

Các đường dẫn trong bảng tính từ `backend/`.

## Luồng và quyền sở hữu

```text
claim_next() commit owner và tăng attempt
  → prepare_profile_job() trong parent
  → xác minh run/project/batch, READY và snapshot
  → đóng session chuẩn bị
  → run_profile() ngoài event loop
  → workspace mới + bản sao CSV riêng + request.json
  → run_sandboxed() chạy profile_child.py tuyệt đối bằng Python -I
  → child áp dụng filesystem policy
  → child kiểm tra hash staging, load bảng và khóa DuckDB
  → profile_files() tạo DataProfile
  → parent kiểm tra response version/identity/bảng/schema/hash raw
  → parent lưu profile.json và trả dict DataProfile
  → caller complete/fail bằng owner và attempt
```

Runner không tự claim, complete, retry hoặc gọi Modeler. Worker loop quản lý lease và lifecycle; API giao kết quả theo checkpoint. Xem [worker-lifecycle.md](worker-lifecycle.md).

`prepare_profile_job()` kiểm tra queue SANDBOX, kind profile, RUNNING, worker_id, attempt và lease còn hạn theo đồng hồ PostgreSQL. Identity lấy từ Job → PipelineRun, rồi so với payload và manifest. UUID hợp lệ về cú pháp không đủ chứng minh quan hệ giữa các tài nguyên.

Một context chuẩn bị không giữ quyền sở hữu vô thời hạn. Caller phải tiếp tục heartbeat, truyền stop_event khi cần dừng và để queue kiểm tra quyền lần nữa khi complete/fail. Không giữ transaction DB suốt thời gian chạy child.

## Payload và tương thích job cũ

Payload version 1 chỉ có `schema_version`, `project_id`, `batch_id` và `manifest_sha256`. Manifest là nguồn danh sách file/config, không nhận executable hoặc đường dẫn storage tùy ý từ payload.

Job cũ chưa có version được đọc bằng schema legacy riêng trong parent. Chỉ chuyển sang contract mới sau khi từng filename, config và storage_path khớp snapshot READY đã kiểm chứng. Không ghi lại Job.payload hoặc dùng path legacy để mở file. Legacy sai hoặc version không hỗ trợ bị từ chối.

Producer `profile_job_payload()` trong graph đọc metadata READY đã commit. Worker tiếp tục kiểm chứng file thực tế khi chuẩn bị và trước staging. Việc node replay không tự tạo job thứ hai: vẫn dùng idempotency key của queue.

## Workspace và staging

```text
projects/<project>/runs/<run>/workspaces/<job>/
  attempt-0001/
    input/
      customers.csv
      orders.csv
    request.json
    profile.duckdb
    profile.json
    duckdb-tmp/
```

Tạo attempt bằng `exist_ok=False`, quyền thư mục 0700. Runner kiểm tra containment và symlink trước khi tạo. Một attempt đã tồn tại không được ghi đè. Retry dùng số attempt sau claim mới, không tái sử dụng database hoặc artifact của lần trước.

CSV staging là bản sao có inode riêng. Runner giới hạn tổng input mặc định 2 GiB, kiểm tra hash/kích thước khi sao chép và kiểm tra lại raw trước khi nhận kết quả. Snapshot hashing có giới hạn theo kích thước đã ghi nhận. Đây không phải quota tổng volume, tổng mọi attempt hoặc tổng mọi artifact.

Request chứa manifest/config cùng identity, không có credential. Request/response mỗi document tối đa 4 MiB; output của subprocess còn chịu ngân sách tổng stdout/stderr trong Limits, mặc định nhỏ hơn mức này.

## Bảo vệ raw bằng filesystem policy

Child áp dụng [Landlock của Linux](https://docs.kernel.org/userspace-api/landlock.html) trước khi import DuckDB và tạo thread. Policy chỉ cấp ghi trong workspace của attempt, cấp đọc cho workspace và các cây runtime/code tin cậy cần chạy Python. Quyền execute và các thao tác filesystem được xử lý khác mặc định bị từ chối.

Điều kiện chạy: Linux x86_64/aarch64/riscv64, Landlock ABI >= 3 và môi trường cho phép các syscall tương ứng. Thiếu hỗ trợ, nhiều thread đã tồn tại hoặc áp dụng policy lỗi thì child thất bại; không có chế độ bỏ bảo vệ.

Các test thật chứng minh child không đọc/ghi raw bên ngoài workspace qua đường dẫn tuyệt đối, không rename/unlink/hardlink hoặc ghi qua symlink. Staging giúp tách inode; Landlock mới là lớp ngăn truy cập raw ở đường dẫn gốc.

Policy không thu hồi descriptor đã mở từ trước và không xử lý mọi metadata operation như chmod. Entrypoint cố định áp dụng policy khi còn một thread; subprocess đóng các descriptor không cần thiết. Cây code/runtime được cấp đọc phải chứa code/runtime tin cậy. Policy này không thay network isolation, cgroup, quota, kiểm soát process hoặc nguyên tắc không truyền credential.

Không thay cấu trúc volume Compose ở thay đổi này. Cần chủ hạ tầng review Landlock và quyền mount/network khi triển khai môi trường khác.

## Hợp đồng child và xử lý lỗi

Parent ghi xong `request.json` rồi chạy executable/entrypoint tuyệt đối do code chọn, với argv list. Stdin không dùng. Child bootstrap import từ vị trí code tin cậy, không phụ thuộc PYTHONPATH/cwd để tìm package và tắt ghi bytecode tường minh.

Stdout chỉ chứa một `ProfileChildResponse`; stderr chỉ báo loại lỗi, không in request, env hoặc dữ liệu thô. Parent kiểm tra cancellation, timeout, output limit và exit code trước parse JSON.

Các mã lỗi runner chính: `cancelled`, `timeout`, `output_too_large`, `child_failed`, `input_too_large`, `invalid_response`, `response_identity_mismatch`, `response_tables_mismatch` và `source_changed`.

Kết quả phải khớp đúng project/batch/run/job/attempt và mapping bảng/file của manifest. Schema profile từ chối trường lạ, count âm, ratio ngoài [0,1] và số không hữu hạn. Raw rows không được thêm vào response.

Runner trả `response.profile.model_dump(mode="json")` để Job.result giữ đúng contract DataProfile của graph; không lưu envelope vào Job.result. `profile.json` là artifact đã validate để đọc/debug. DB/checkpoint là nguồn trạng thái; artifact dở dang ở attempt chết không phải kết quả thành công.

## Thống kê profiler

Profiler dùng đúng connection đã khóa của runtime, không mở database hoặc đọc CSV lại. Bảng nguồn giữ VARCHAR và mã có số 0 đầu. Suy kiểu kiểm tra biểu diễn số nguyên để tránh việc TRY_CAST làm tròn số thập phân; số nguyên lớn có thể dùng HUGEINT. Min/max theo kiểu suy ra và sample có thứ tự xác định.

Mỗi cột có count/null ratio/distinct/min/max, tối đa 5 sample, mỗi sample tối đa 160 ký tự. Khóa đơn chỉ là quan sát unique và nonnull trong batch; khi không có khóa đơn, thử cặp trong tối đa 12 cột nonnull đầu tiên, kèm note khi giới hạn phạm vi.

Quan hệ được dò theo tên *_id/id_* tương ứng, parent id theo tên bảng và các khóa ghép quan sát được. Ratio/orphan bỏ qua dòng child có thành phần join NULL. Parent được group trước join để đếm child đúng ngay cả khi khóa cha trùng; kết quả có parent_key_unique, max_parent_matches và fanout_warning. Đây là ứng viên có bằng chứng, chưa phải ràng buộc được duyệt hoặc thuật toán tìm mọi quan hệ có thể có.

Tên bảng chuẩn hóa có hash khi biến đổi mất thông tin; identifier SQL được quote tập trung. Ngoại lệ Ruff S608 chỉ áp dụng module profiler và có test header chứa SQL để kiểm chứng escaping.

## Chạy test

Trong Bash WSL, tại `backend/`:

```bash
.venv/bin/python -m pytest tests/unit/test_profile_protocol.py tests/unit/test_profiler.py tests/unit/test_runner.py -q -rs
```

Integration cần đặt DATAFORGE_TEST_DATABASE_URL; nếu chưa có biến này pytest sẽ skip. Chỉ trỏ APP/TEST/CHECKPOINT vào database test đã migrate/setup, ví dụ dataforge_test, không dùng database ứng dụng đang làm việc.

```bash
.venv/bin/python -m pytest tests/integration/test_worker_profile.py -q -rs
.venv/bin/python -m pytest tests/integration/test_graph_design_gate.py tests/integration/test_run_creation.py -q -rs
.venv/bin/python -m pytest tests/unit/test_duckdb_lockdown.py tests/unit/test_sandbox.py tests/unit/test_sandbox_limits.py -q -rs
```

Test worker profile dùng schema PostgreSQL riêng và chứng minh claim → prepare → child thật → queue.complete. Test graph còn dùng Modeler/profile fixture xác định để tập trung vào gating/replay; chúng không thay bằng chứng profiler thật.

## Bằng chứng đã chạy

Ngày 24/10/2026: **86 test mới đạt** (71 unit và 15 integration), không skip. Hồi quy toàn backend trên dataforge_test đạt **1107 passed, 16 skipped** trong 383,43 giây. Skip gồm 15 TODO có sẵn và một OULAD opt-in. Ruff check/format (140 file), mypy strict (131 source file) và conventions đạt. Log/JUnit cục bộ: backend/data/upload-checks/profile-runner-regression.log và profile-runner-regression.xml.

Probe container dùng image Python 3.11.14 cùng digest trong backend/Dockerfile, user 10001, network none, rootfs read-only, cap-drop ALL, no-new-privileges, cgroup 3 GiB/2 CPU/256 pids. Runner tạo profile customers=2, orders=3; sáu thao tác truy cập raw ngoài workspace đều bị chặn và không có credential trong env child. Log local: `backend/data/upload-checks/profile-runner-container.json`.

Sizing OULAD/TPC-H đầy đủ, quota tổng và worker loop/heartbeat/delivery vẫn cần kiểm chứng ở các phần tích hợp tiếp theo.
