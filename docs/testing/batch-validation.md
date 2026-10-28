# Kiểm chứng upload, manifest và READY

Thực hiện ngày **19/10/2026**, trên Python 3.11.14 trong WSL Ubuntu và PostgreSQL 16.15. Đây là bằng chứng cho **B5 của Tú** trong [kế hoạch tuần 2](../../PLAN%20WEEK/PLAN%20WEEK%202.md). Không thêm dependency hoặc thay đổi lockfile.

## Kết quả đã chạy

| Kiểm tra | Kết quả thực tế |
|---|---|
| Toàn bộ backend, có PostgreSQL | **600 passed, 17 skipped**, 157,41 giây |
| Test mới trong bộ mặc định | **82 integration + 9 unit**, đều đạt |
| OULAD riêng, đủ 7 CSV thật | **1 passed**, 31,76 giây |
| Ruff check và format | Qua trên backend, airflow, scripts |
| mypy strict | Qua, 104 source file |
| Quy ước ASCII/không comment | Qua |
| Alembic check trên dataforge_test | Qua, không có schema drift |
| Frontend npm run ci | Qua Biome, TypeScript và Vite build |

17 skip gồm **16 TODO có sẵn ngoài phạm vi batches** và **1 test OULAD cần bật riêng**. OULAD đã chạy riêng thành công; không có integration test batches nào bị bỏ qua vì thiếu PostgreSQL.

Log và JUnit được giữ local, Git bỏ qua:

- backend/data/upload-checks/backend-tests.log và backend-tests.xml.
- backend/data/upload-checks/oulad-batch-tests.log và oulad-batch-tests.xml.

Không chạy các job GitHub Actions images/security; kết quả trên là kiểm chứng local.

## Code đã hoàn thiện để test được hành vi thật

Khi bắt đầu B5, routes/services batches vẫn là stub. Đã triển khai phần nền cần thiết của B1–B4 để test gọi API thật, thay vì mock ra kết quả READY:

| Thành phần | Vai trò |
|---|---|
| [routes/batches.py](../../backend/app/api/routes/batches.py) | Quyền Engineer, gọi service, commit/rollback và HTTP error |
| [services/batches.py](../../backend/app/services/batches.py) | Khóa batch, upload, confirm, chuẩn bị/publish snapshot và kiểm tra READY |
| [filenames.py](../../backend/app/ingest/filenames.py) | Tên CSV portable và tập tên không trùng sau casefold |
| [manifest.py](../../backend/app/ingest/manifest.py) | Pydantic manifest v1, serialize ổn định và SHA-256 |
| [storage.py](../../backend/app/ingest/storage.py) | Raw không ghi đè, file tạm riêng, atomic replace, fsync và marker mang hash |
| [sniff.py](../../backend/app/ingest/sniff.py) | Validate config, preview theo config gửi lên, đọc encoding theo stream |
| [test_batches.py](../../backend/tests/integration/test_batches.py) | API, PostgreSQL, storage, quyền, race và fault injection |
| [test_batch_manifest.py](../../backend/tests/unit/test_batch_manifest.py) | Hash canonical, schema manifest, quoting và atomic storage |

Frontend được cập nhật theo contract tạo batch: chọn đủ file trong lần chọn đầu, gửi required_files, không xóa file khỏi một batch đã bắt đầu. Muốn đổi tập file thì bỏ draft và tạo batch mới. Chỉ thay đổi phần tương thích upload; không thay thiết kế giao diện.

### Contract API

Mọi endpoint dưới /projects/{project_id}/batches yêu cầu Engineer của project đó.

1. POST /batches nhận {"required_files":["customers.csv","orders.csv"]}, lưu UPLOADING và tập tên khai báo.
2. POST /batches/{batch_id}/files nhận multipart file. Tên phải đúng khai báo; raw được hash và lưu nguyên vẹn; response có preview và read_config_confirmed=false.
3. PUT /batches/{batch_id}/files/{file_id}/read-config nhận {"read_config":{...}}. Render bằng config gửi lên, chỉ confirmed sau khi đọc preview thành công.
4. POST /batches/{batch_id}/ready chốt snapshot. Đúng tập tên, mọi file confirmed, đúng hash/size và không có file lạ hoặc .part mới đủ điều kiện.

Sai token trả 401; thiếu quyền 403; batch/file không thuộc URL 404; sai trạng thái/snapshot 409; cấu hình hoặc tên không hợp lệ 422; quá giới hạn raw 413; lỗi storage có thể retry 503.

DATAFORGE_MAX_UPLOAD_BYTES mặc định **1 GiB/file**, cấu hình trong backend/.env.example. Giới hạn áp dụng khi stream vào raw storage, sau khi framework tiếp nhận multipart; chưa phải giới hạn body ở reverse proxy.

### Vì sao cần ba bước publish?

Luồng dưới khóa hàng batch:

~~~text
kiểm tra raw/config
  → ghi manifest nguyên tử
  → commit DB: status=READY + manifest_sha256
  → publish _READY chứa đúng hash manifest
~~~

DB và filesystem không cùng transaction. DB READY chưa đủ: consumer phải dùng assert_batch_ready để kiểm tra **DB + manifest + marker + raw** nhất quán.

- Lỗi trước commit READY: DB còn UPLOADING, chưa có marker hợp lệ.
- Commit READY xong nhưng marker lỗi: DB có snapshot đã chốt; consumer từ chối tới khi retry READY publish xong.
- Marker đã ghi nhưng response lỗi: retry giữ cùng hash, không tạo snapshot khác.
- Manifest/marker bị sửa: từ chối, không âm thầm ghi đè bản đã publish.
- Upload đã ghi raw nhưng commit lỗi: giữ raw. Retry chỉ nhận lại file mồ côi khi bytes giống hệt; không xóa raw dựa vào giả định commit chưa xảy ra.
- Snapshot READY chặn upload/config mới; muốn đổi dữ liệu tạo batch khác.

Các thao tác filesystem nặng chạy qua thread pool. Raw dùng tên .part riêng từng writer rồi hard link chống overwrite; manifest/marker dùng replace nguyên tử cùng thư mục, fsync file và directory trên Linux. Đây không phải mô phỏng cắt điện phần cứng hoặc bảo đảm cho mọi filesystem mạng.

## Ma trận test để đọc cùng code

| Điều cần hiểu | Test tiêu biểu |
|---|---|
| Đủ tên khác với đủ số lượng | test_ready_requires_every_file_and_confirmation; test_ready_rejects_wrong_names_even_when_file_count_matches |
| Confirm khác với upload thành công | test_invalid_config_preserves_previous_state; test_submitted_config_controls_preview_without_changing_raw |
| Quyền và chuỗi project → batch → file | test_mutations_require_project_engineer; test_cross_project_batch_and_cross_batch_file_are_rejected |
| Tên an toàn và raw bất biến | test_create_rejects_invalid_declarations; test_duplicate_upload_never_overwrites_raw |
| READY lặp lại an toàn | test_ready_is_idempotent_and_blocks_further_mutation |
| Từ chối snapshot hỏng/thiếu | test_consumer_fails_closed_for_damaged_snapshot; test_ready_retry_rejects_a_corrupt_marker |
| File đã ghi nhưng commit không rõ kết quả | test_upload_commit_failure_preserves_raw_and_safe_retry; test_orphan_retry_with_different_bytes_is_rejected |
| Lỗi giữa manifest/DB/marker | test_ready_retries_filesystem_failure_without_changing_snapshot; test_failed_ready_commit_does_not_publish_marker; test_failure_after_marker_publish_can_be_retried |
| Upload/confirm/READY đồng thời | test_concurrent_duplicate_upload_creates_one_source_file; test_upload_racing_ready_cannot_skip_confirmation; test_ready_waits_for_confirmed_configuration; test_two_ready_requests_publish_one_snapshot |
| Canonical hash và atomic write | test_manifest_hash_ignores_only_file_order; test_failed_manifest_replace_keeps_previous_bytes; test_concurrent_raw_writers_never_replace_each_other |

Integration fixture tạo user/project có UUID riêng và commit setup để request/session độc lập nhìn thấy. Observer session đọc lại DB sau request. Cleanup chỉ xóa dữ liệu đúng ID fixture đã tạo; storage dùng thư mục tạm. Không sửa fixture rollback chung của dự án hoặc account demo đã chuẩn bị trước.

Race test dùng PostgreSQL row lock và quan sát pg_blocking_pids để biết request thực sự đang đợi khóa, có deadline; không dựa vào sleep may rủi.

Test OULAD stream đủ assessments.csv, courses.csv, studentAssessment.csv, studentInfo.csv, studentRegistration.csv, studentVle.csv và vle.csv qua upload API, confirm rồi READY. So sánh SHA-256 nguồn/raw/manifest và kiểm tra snapshot bằng session mới. Thư mục upload lớn tự dọn sau test; không sửa golden raw.

## Chạy lại trong Bash WSL

Từ thư mục backend, dùng cấu hình DB test riêng đã chuẩn bị theo [upload-checks.md](upload-checks.md):

~~~bash
set -a
source .env.upload-checks
set +a

.venv/bin/python -m alembic upgrade head
.venv/bin/python -m alembic check
.venv/bin/python -m pytest tests/integration/test_batches.py tests/unit/test_batch_manifest.py tests/unit/test_ingest.py -q -rs
.venv/bin/python -m pytest -q -rs --junitxml=data/upload-checks/backend-tests.xml

DATAFORGE_OULAD_RAW_DIR="$PWD/../eval/golden/oulad/raw" \
  .venv/bin/python -m pytest tests/integration/test_batches.py -k oulad -q -rs \
  --junitxml=data/upload-checks/oulad-batch-tests.xml
~~~

Nếu chưa có virtualenv, dùng uv sync --locked theo hướng dẫn repository. Không trỏ các lệnh test/migration này sang database ứng dụng đang dùng.

Kiểm tra tĩnh và frontend:

~~~bash
.venv/bin/ruff check . ../airflow ../scripts
.venv/bin/ruff format --check . ../airflow ../scripts
.venv/bin/mypy app worker tests ../scripts/check_conventions.py
.venv/bin/python ../scripts/check_conventions.py
cd ../frontend
npm run ci
~~~

### Migration cần review khi tích hợp

Migration [25810a2b5deb](../../backend/migrations/versions/20261019_25810a2b5deb_add_batch_readiness_snapshot.py) đã được autogenerate, rà tay và **chỉ áp dụng vào dataforge_test**:

- Thêm batches.required_files và batches.manifest_sha256, nullable để giữ bản ghi cũ.
- Thêm unique (batch_id, filename) cho source_files.
- Nếu dữ liệu cũ trùng tên, migration dừng để xử lý có chủ đích, không tự xóa.
- Batch cũ chưa có khai báo/hash không tự được suy ra là hợp lệ; cần tạo batch mới theo contract.
- Chưa migrate database dev/application. Nhờ chủ schema review trước khi áp dụng vào môi trường dùng chung.

## Phạm vi còn lại

**B5 đã chứng minh phần batches và hàm guard cho consumer.** routes/runs.py và worker chưa nối assert_batch_ready; kiểm chứng từ HTTP tạo run thật và worker thật tiếp tục ở **C2/D4**. Vì vậy kết quả này chưa chứng minh hệ thống hoàn chỉnh không thể tạo run từ batch hỏng.

Preview là text và chỉ đọc mẫu hữu hạn. date_format/timestamp_format được lưu cùng config nhưng chưa kiểm chứng chuyển kiểu ngày bằng DuckDB trên toàn file; profiler ở chặng D cần xác nhận hợp đồng đó. Confirm không thay thế kiểm thử/profile toàn dataset.

schema_fingerprint/check_schema_unchanged (FR-17), chạy pipeline/Airflow (FR-16 đầy đủ), sandbox, Cổng 1 và restart FR-21 vẫn ngoài B5. Không đánh dấu các mục tuần 2 đó hoàn thành từ kết quả này.
