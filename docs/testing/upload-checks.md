# Chuẩn bị dữ liệu CSV và kiểm chứng phân quyền theo dự án

Đã thực hiện ngày **2026-10-19**, múi giờ Asia/Bangkok. Commit nền: **034b401**. Python WSL: **3.11.14**. Các dependency backend/dev đang cài khớp toàn bộ phiên bản trong pyproject.toml; không nâng hoặc thêm dependency.

## Những gì đã chuẩn bị

- Bộ [CSV tổng hợp](../../backend/tests/fixtures/upload/README.md): complete, missing, semicolon và đáp án [expected.json](../../backend/tests/fixtures/upload/expected.json).
- Bản làm việc local: backend/data/upload-checks/input; storage: backend/data/upload-checks/storage. Không thay đổi raw golden dataset.
- PostgreSQL DataForge: container dataforge-postgres-1, database riêng dataforge_test, role dataforge. Chỉ khởi động container đã có; không dùng Postgres của dự án khác.
- Đã chạy migration hiện có, alembic check, setup bảng checkpoint và alembic check lần nữa trên đúng DB test. Không tạo migration hoặc đổi schema nguồn.
- Cấu hình local backend/.env.upload-checks chứa APP/TEST/CHECKPOINT cùng trỏ dataforge_test; APP/TEST dùng asyncpg, CHECKPOINT dùng URL postgresql. File được Git bỏ qua và có quyền 0600.
- Script [prepare_upload_checks.py](../../backend/scripts/prepare_upload_checks.py) seed qua API auth/projects có sẵn, kiểm tra bằng session mới và chạy lại từ process khác.

## Kết quả thực tế

| Kiểm chứng | Kết quả |
|---|---|
| Toàn bộ pytest trước khi seed demo | 509 passed, 0 failed, 0 errors, 16 skipped |
| Lý do skip | Tất cả 16 là TODO; không skip vì thiếu DB |
| Phiên bản dependency | 0 lệch so với pyproject.toml |
| Alembic và checkpointer setup | Qua; không phát hiện schema drift |
| Quyền qua API auth/projects | 9/9 kiểm tra đạt |
| Dữ liệu commit | Session mới đọc được 3 user và 4 membership trên 2 project |
| Process độc lập | PID khác nhau; đọc lại cùng project ID và membership đã lưu |
| CSV | 3 customer, 3 order, tổng 225.00, không orphan; mã có số 0 đầu được giữ |
| Config sai/đúng | Dấu phẩy đọc fixture semicolon thành 1 cột; sniff đúng dấu ; được 3 cột; NA thay đổi theo null config |
| Ruff format/check | Qua trên backend, airflow và scripts |
| mypy | Qua 100 source file, gồm script kiểm chứng upload |
| check_conventions.py | Qua |

Log và dữ liệu máy đọc nằm trong backend/data/upload-checks, được Git bỏ qua:

- baseline.log và baseline.xml: kết quả pytest đầy đủ.
- checks.json: lần seed/kiểm tra.
- checks-verify.json: process khác kiểm tra dữ liệu có sẵn trước các request quyền.
- summary.json: tóm tắt baseline và phạm vi.
- accounts.json: namespace và mật khẩu local cho 3 tài khoản; quyền 0600, không commit và không đưa vào báo cáo chia sẻ.

## Ma trận user/project đã lưu

Email thực có namespace riêng để không đụng tài khoản trước đó; xem memberships trong checks.json. Token được tạo khi chạy, không ghi vào báo cáo.

| User | Project A | Project B |
|---|---|---|
| Tú | Engineer | Reviewer |
| Vinh | Reviewer | Engineer |
| Outsider | Không thuộc | Không thuộc |

Đã thử: Engineer thêm Reviewer thành công (204); Reviewer và Outsider không được thêm thành viên (403); Engineer/Reviewer được đọc history (200); Outsider bị chặn (403); thiếu token trả 401. Kiểm tra quyền gọi router thật với bearer token và dependency thật, dùng ASGITransport trong process, không cần server HTTP ngoài.

Các account/project được giữ lại trong DB test để dùng ở bước B. Script chỉ thao tác namespace local của bộ kiểm chứng upload, không xóa dữ liệu khác.

## Chạy lại trong Bash WSL

Từ thư mục backend:

~~~bash
set -a
source .env.upload-checks
set +a
.venv/bin/python -m scripts.prepare_upload_checks --verify-only
~~~

Bỏ --verify-only để chuẩn bị lại cùng namespace; script không nhân user/project và từ chối ghi đè CSV local đã sửa.

Để dùng tài khoản qua Swagger, giữ các biến trên trong terminal rồi chạy:

~~~bash
.venv/bin/python -m uvicorn --factory app.main:create_app --reload
~~~

Mở http://localhost:8000/docs. Email lấy từ checks.json, mật khẩu local lấy từ accounts.json. API batches/runs còn stub nên chưa thể nghiệm thu upload/READY qua UI.

Lệnh baseline đã chạy, và có thể chạy lại:

~~~bash
.venv/bin/python -m pytest -q -rs --junitxml=data/upload-checks/baseline.xml
~~~

Môi trường WSL hiện không có uv trên PATH; đã dùng virtualenv sẵn có sau khi đối chiếu toàn bộ phiên bản dependency. Không sửa lockfile.

## Cách hiểu fixture và phạm vi bằng chứng

db_session hiện mở transaction ngoài và dùng create_savepoint. Commit của endpoint khi được override bằng fixture đó chưa làm dữ liệu nhìn thấy từ connection độc lập; cuối test transaction ngoài rollback.

session_factory.begin() commit khi block thành công, phù hợp worker/delivery mở session khác. Dữ liệu commit cần cleanup theo ID tạo bởi test. Bộ kiểm chứng upload cố ý giữ các account/project của namespace riêng để dùng tiếp; không sửa fixture chung tuần 1.

pytest có autouse fixture tắt background delivery; app fixture mặc định dùng InMemorySaver. Graph test có mock Modeler/job. Baseline xanh và phép kiểm tra process kiểm chứng upload không phải bằng chứng FR-21 hoặc worker/sandbox đã hoàn tất; các phần đó vẫn ở chặng D/E.

Các điều kiện chuẩn bị đã đạt: CSV nhỏ và đáp án, storage riêng, DB test/checkpointer, session mới thấy dữ liệu commit, hai project có Engineer/Reviewer và baseline được ghi.
