# Khôi phục Cổng 1 qua hai vòng đời backend

Bộ test tạo lượt chạy bằng HTTP, thực thi job profile thật, đóng ứng dụng đang chờ duyệt rồi mở ứng dụng mới trên cùng PostgreSQL và storage. Ứng dụng mới phải giữ nguyên điểm chờ và nhận được quyết định từ Engineer.

## Các file cần đọc

| File tính từ root repository | Vai trò |
|---|---|
| `backend/tests/integration/test_run_recovery.py` | Các tình huống quyết định sau khởi động lại |
| `backend/tests/recovery_backend.py` | Dữ liệu đã commit, hai lifespan độc lập, worker và bằng chứng trước/sau |
| `backend/app/main.py` | Lifespan thật, startup recovery, đóng tài nguyên |
| `backend/app/services/runs.py` | Đọc checkpoint, đồng bộ polling, giao kết quả job và quyết định |
| `backend/tests/integration/test_run_decisions.py` | Graph nhỏ với các node thật đến Cổng 1 và probe sau duyệt |

## Luồng kiểm chứng

1. Tạo schema PostgreSQL riêng cho mỗi test. Commit user, quyền Engineer, project, batch READY và source file; ghi manifest cùng dữ liệu CSV nhỏ vào storage tạm. Đóng engine chuẩn bị dữ liệu.
2. Mở ứng dụng A bằng `create_app()` và lifespan thật. Tạo mới engine, checkpoint pool, graph, context và delivery task; bật recovery/delivery như khi chạy API.
3. Gửi HTTP tạo run. Claim job qua queue, chạy `execute_job()` với sandbox Linux, DuckDB và CSV thật; kiểm tra job SUCCEEDED, profile có ba dòng. Delivery thật đưa kết quả vào graph; Modeler trả thiết kế xác định, không gọi Gemini.
4. Poll có deadline đến `waiting_design_approval`. Chụp run/thread/project/batch ID, checkpoint values, interrupt, pending, nội dung/hash/version thiết kế, job, approval và resume intent. Kiểm tra chưa gọi codegen.
5. Đóng client A, dừng và join delivery task, đóng checkpoint pool, dispose engine. Kiểm tra không còn kết nối engine được checkout lúc dispose. Helper bỏ tham chiếu tới app/client A; chỉ giữ dữ liệu bằng chứng và số đếm.
6. Mở ứng dụng B với toàn bộ tài nguyên mới trên cùng DB/storage. Để lifespan tự chạy recovery trước khi ready; không gọi hàm sửa trạng thái riêng từ test. GET cùng run và so sánh bằng chứng. Cho phép `updated_at` thay đổi; các identity, điểm chờ và dữ liệu còn lại phải giữ nguyên. Profile và Modeler không chạy lại.
7. Engineer gửi quyết định qua HTTP của B. Kiểm tra approval, phiên bản thiết kế, fingerprint, resume intent và số lần bước tiếp theo được gọi. Đóng và kiểm tra tài nguyên B.

Modeler của B không có output mặc định: nếu startup vô tình gọi lại Modeler, bộ test sẽ thất bại. Các số đếm đi qua hai vòng đời chỉ là dữ liệu quan sát; không giữ app, graph, saver, session hoặc kết nối của A để dùng ở B.

## Các tình huống

| Tình huống | Kết quả |
|---|---|
| Approve sau khởi động lại | Duyệt đúng hash/version cũ, bước codegen được gọi một lần |
| Sửa thiết kế rồi approve | Giữ nguyên phiên bản đã trình bày; tạo bản mới và fingerprint gắn bản được duyệt |
| Return kèm nhận xét | Modeler nhận thiết kế cũ và nhận xét; tạo version/interrupt mới; chưa gọi codegen |
| Gửi lại approve hoặc return | HTTP 409, không đổi checkpoint hay tạo thêm approval/intent/công việc |
| Dùng interrupt cũ, version cũ hoặc cả hai sau return | HTTP 409, giữ nguyên điểm chờ mới |

Tổng cộng tám trường hợp nhờ tham số hóa các request trùng và identity cũ.

## Chạy test

Chạy trong Bash trên Linux hoặc WSL, từ `backend/`. Cần môi trường Python và PostgreSQL test đã được chuẩn bị theo [upload-checks.md](upload-checks.md); dùng database riêng cho kiểm thử.

```bash
export DATAFORGE_TEST_DATABASE_URL="postgresql+asyncpg://dataforge:dataforge@localhost:5432/dataforge_test"

.venv/bin/python -m pytest tests/integration/test_run_recovery.py -q -rs
```

Không đặt URL test sẽ khiến integration test bị skip. Hệ điều hành khác Linux cũng skip vì job sử dụng sandbox native. Không cần khóa Gemini hoặc một worker process chạy riêng; test gọi lifecycle thực thi job và vẫn đi qua queue, lease, sandbox và delivery thật.

Mỗi test dọn schema riêng và checkpoint thread của các run do test tạo. Các pool/engine dùng để chuẩn bị và dọn dữ liệu nằm ngoài hai vòng đời API và cũng được đóng.

## Kết quả kiểm tra

Kiểm tra trên Linux/WSL với PostgreSQL test:

- Bộ test khôi phục: **8 passed**.
- Toàn bộ backend: **1200 passed, 16 skipped**. Các trường hợp skip gồm 15 bài TODO có sẵn và một bài OULAD cần bật đường dẫn raw riêng.
- Ruff check, Ruff format, mypy và kiểm tra quy ước repository đều qua.

## Phạm vi bằng chứng

Đây là hai vòng đời ứng dụng ASGI trong cùng process pytest, sử dụng PostgreSQL checkpoint saver thật. Bài test kiểm tra việc bỏ tài nguyên A và đọc lại dữ liệu qua kết nối mới của B.

Graph giữ các node thật từ profile đến Cổng 1, thay Modeler bằng output xác định và thay phần sau duyệt bằng codegen probe có kiểm tra approval trong DB. Probe nối tới END; trạng thái kết thúc của graph nhỏ không chứng minh pipeline đã sinh mã hoặc publish thật.

Diễn tập dừng process backend bằng Compose và SIGKILL đã được kiểm chứng riêng trong [backend-restart.md](backend-restart.md), dùng database/storage diễn tập cùng Modeler xác định. Các bài này nghiệm thu khôi phục Cổng 1; các ranh giới lỗi và Cổng 2 của FR-21 cần kiểm thử tương ứng. Xem [application-recovery.md](application-recovery.md) về startup và [worker-lifecycle.md](worker-lifecycle.md) về worker, lease và delivery sau crash.
