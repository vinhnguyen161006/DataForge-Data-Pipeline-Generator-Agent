# Diễn tập khôi phục backend bằng Docker Compose

Bài diễn tập dừng process backend thật tại Cổng 1, giữ PostgreSQL, sandbox worker và volume, rồi mở lại backend để đọc đúng checkpoint và tiếp nhận quyết định Engineer. Hai trường hợp dùng run riêng: shutdown sạch bằng stop/start và shutdown đột ngột bằng SIGKILL/start.

## Chạy một lệnh

Từ root repository trong Bash Linux hoặc WSL, sau khi đã cài dependency backend bằng lockfile và chuẩn bị `.env` cho Compose:

```bash
backend/.venv/bin/python backend/scripts/check_backend_recovery.py
```

Script dùng Docker Compose và Python/httpx đã có trong dependency backend. Không cần jq, thao tác Swagger hoặc chép token vào terminal. Script tạo tài khoản và project diễn tập qua API; mật khẩu và token chỉ giữ trong bộ nhớ.

Cần Docker daemon hoạt động, Compose hỗ trợ `up --wait`, các cổng 5432/8000/6333 của stack DataForge khả dụng và quyền khởi động các container DataForge. Nếu image đã được build từ code hiện tại, có thể dùng `--skip-build`.

Kết quả nằm trong thư mục mới dưới `data/restart-checks/`, được in cuối lệnh. Khi thành công sẽ có hai dòng PASS và `summary.json` có cả `passed: true` lẫn `restored_default_backend: true`.

## Các file triển khai

| File | Vai trò |
|---|---|
| `docker-compose.recovery.yml` | Override backend, migrate và worker sang database/storage diễn tập |
| `backend/scripts/recovery_app.py` | App factory kiểm thử, Modeler xác định, codegen probe và đọc snapshot |
| `backend/scripts/check_backend_recovery.py` | Orchestrate Compose, upload thật, so sánh bằng chứng và khôi phục cấu hình |
| `backend/app/main.py` | Cho phép truyền graph/context builder tường minh vào lifespan |
| `backend/tests/unit/test_recovery_app.py` | Chặn cấu hình nhầm DB/storage và kiểm tra hợp đồng Modeler xác định |
| `backend/tests/unit/test_app.py` | Kiểm tra factory được truyền vào lifespan và default không bị thay đổi |

App production tiếp tục dùng `app.main:create_app`. Override gọi riêng `recovery_app:create_app`. Factory diễn tập chỉ chấp nhận flag `DATAFORGE_RECOVERY_DRILL=true`, database APP/CHECKPOINT cùng tên `dataforge_recovery`, storage có thư mục cuối `recovery-drill` và delivery được bật.

## Dữ liệu và ranh giới

- Tạo database `dataforge_recovery` trên chính service Postgres DataForge, owner `dataforge`; database có sẵn được giữ lại.
- Alembic và checkpoint setup chạy bằng service migrate với URL diễn tập.
- Backend và worker dùng cùng database này và storage `/data/recovery-drill` trên volume hiện có.
- Hai CSV lấy từ `backend/tests/fixtures/upload/complete/`; mỗi case tạo batch và run mới.
- Giữ nguyên dữ liệu `dataforge_app`. Không reset DB, không xóa volume và không thao tác container của dự án khác.
- Override đặt Gemini API key và GitHub token rỗng. Modeler trả DataDesign hợp lệ xác định cho hai CSV mẫu; không gọi dịch vụ LLM.
- Các node profile, clarification, design gate, queue, worker sandbox, delivery, PostgreSQL checkpoint và API phân quyền đều là code thật.

Modeler thật trong `app/agents/modeler.py` hiện còn stub. Cấu hình này dành riêng cho kiểm chứng recovery; hoàn thành bài diễn tập không đồng nghĩa đã triển khai Modeler Gemini.

## Luồng mỗi trường hợp

1. Đăng ký Engineer và tạo project qua HTTP. Khai báo hai file, upload, kiểm tra preview và confirm cấu hình đọc.
2. Chốt batch READY rồi tạo run qua HTTP.
3. Chờ worker thật xử lý profile. Kiểm tra đúng hai bảng, mỗi bảng ba dòng; một job, một attempt, SUCCEEDED và delivered.
4. Chờ API ở `waiting_design_approval`. Kiểm tra checkpoint có đúng interrupt đang trình bày, cùng thread/run ID và design version.
5. Lưu snapshot API, checkpoint values/next/interrupt, batch manifest/marker, jobs/results, design version/hash/content, approvals và resume intents.
6. Lưu số lần Modeler/codegen probe từ nhật ký quan sát bền vững trên volume. Trước quyết định phải có một lần Modeler và chưa có codegen.
7. Dừng duy nhất backend bằng stop hoặc SIGKILL. Kiểm tra process đã thoát, API ngừng phục vụ; exit code lần lượt là 0 hoặc 137.
8. Start lại chính container backend và chờ health. ID container/mount giữ nguyên, thời điểm process start thay đổi. PostgreSQL và worker giữ nguyên container, process start, PID và mount.
9. GET cùng run và đọc checkpoint bằng kết nối mới. So sánh toàn bộ bằng chứng trước/sau; API bỏ `updated_at` khỏi phép so sánh.
10. Gửi approve qua HTTP bằng Engineer. Kiểm tra một approval gắn đúng actor, version và hash, một resume intent đã delivered; codegen probe chạy đúng một lần trong boot mới, profile và Modeler không lặp.
11. Gửi lại cùng quyết định: phải nhận HTTP 409 và snapshot không đổi.

Sau hai case, script lưu log backend/worker và tự áp dụng lại Compose mặc định. Backend được kiểm tra đã quay về command `app.main:create_app` và health thành công. Database diễn tập cùng bằng chứng được giữ lại để đọc lại.

## Đọc bằng chứng

| File trong thư mục mỗi case | Nội dung |
|---|---|
| `before-api.json`, `after-api.json` | Projection phục vụ polling, phải bằng nhau |
| `before-state.json`, `after-state.json` | Bản ghi DB và checkpoint, phải bằng nhau |
| `before-processes.json` | Backend, PostgreSQL, worker và mount trước khi dừng |
| `stopped-process.json`, `after-process.json` | Bằng chứng process dừng và được mở lại |
| `decision-response.json`, `after-decision.json` | Quyết định được chấp nhận và kết quả tiếp tục |
| `duplicate-response.json` | HTTP 409 khi gửi lại |
| `result.json` | Identity, hash, số đếm và kết quả case |

Thư mục gốc có `summary.json`, `compose-output.log`, `backend.log` và `sandbox-worker.log`. Tên thư mục dùng thời gian UTC cùng hậu tố ngẫu nhiên. Các artifact không chứa password, JWT hoặc giá trị secret từ Compose config.

Nếu một bước thất bại, script trả lỗi, ghi summary và cố gắng thu log/khôi phục cấu hình mặc định. Xem artifact của lần chạy lỗi trước khi chạy lại; mỗi lần chạy mới dùng project và run mới. Nếu cần khôi phục thủ công cấu hình dev, chạy từ root:

```bash
docker compose up -d backend sandbox-worker
```

## Giới hạn nghiệm thu

Probe sau duyệt chỉ kiểm tra approval trong DB và ghi nhận đã tới bước codegen. Nó nối tới END trong graph kiểm thử; nhãn kết thúc graph không chứng minh có mã dbt, warehouse hoặc dashboard được xuất bản.

Bài này nghiệm thu khôi phục Cổng 1 qua restart process thật. Các ranh giới race/fault injection, Cổng 2, worker reclaim và nghiệm thu toàn bộ FR-21 cần các bài kiểm tra tương ứng.

Xem [run-recovery.md](run-recovery.md) cho hai vòng đời ASGI trong pytest và [application-recovery.md](application-recovery.md) cho startup readiness.

## Kết quả đã kiểm chứng

Đã chạy thành công ngày 25/10/2026. [Báo cáo có thể đưa lên Git](backend-restart-results.json) ghi run/thread/batch, design version/hash, thời điểm process start, exit code và các số đếm cho hai trường hợp.

- Shutdown sạch: exit code 0; giữ nguyên API projection, checkpoint, thiết kế, job và các process PostgreSQL/worker.
- SIGKILL: exit code 137; sau start vẫn đúng điểm chờ, cùng identity và thiết kế.
- Mỗi run có một job profile, một attempt, một lần Modeler, một approval và một lần codegen probe sau restart.
- Gửi lại quyết định nhận HTTP 409 và không đổi snapshot.
- Backend/worker đã được khôi phục về cấu hình Compose mặc định, health thành công.
- Lượt full suite backend: 1210 passed, 16 skipped; nhóm test liên quan cuối cùng: 37 passed, gồm regression về thứ tự mount được bổ sung sau khi full suite đã collect.
- Ruff format/check, mypy và kiểm tra quy ước repository đều qua.

Artifact đầy đủ của lần chạy cuối nằm tại thư mục data/restart-checks/20261025T050700Z-cb32f4c9/. Các artifact cục bộ được giữ trong thư mục ignored; báo cáo JSON ở tài liệu giữ kết quả để reviewer đọc được trên Git.
