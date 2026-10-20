# Kiểm chứng quyền truy cập lượt chạy theo dự án

Bộ [test_runs.py](../../backend/tests/integration/test_runs.py) kiểm chứng C1 của Tú: xác thực, role trong project và liên kết project → batch/run. Ngày thực hiện: **20/10/2026**.

## Cách chạy trong Bash WSL

Tại thư mục backend, PostgreSQL test cần đang hoạt động:

~~~bash
set -a
source .env.upload-checks
set +a

.venv/bin/python -m pytest tests/integration/test_runs.py -q -rs
~~~

Chạy cùng các test dependency xác thực có sẵn:

~~~bash
.venv/bin/python -m pytest \
  tests/integration/test_runs.py \
  tests/integration/test_deps.py \
  -q -rs
~~~

Đọc chi tiết một nhóm quan trọng:

~~~bash
.venv/bin/python -m pytest tests/integration/test_runs.py \
  -k foreign_resources -vv
~~~

Không có DATAFORGE_TEST_DATABASE_URL thì các integration test được skip theo quy ước dự án. Skip vì thiếu DB không phải bằng chứng quyền đã đạt.

## Fixture và ranh giới kiểm thử

Fixture tạo ba user, hai project, mỗi project một batch và một run. UUID/email/slug riêng từng test:

| User | Project A | Project B |
|---|---|---|
| Engineer | Engineer | Engineer |
| Reviewer | Reviewer | Engineer |
| Outsider | Không có membership | Không có membership |

Reviewer đồng thời là Engineer ở B để chứng minh role không áp dụng toàn hệ thống. Engineer có quyền ở cả hai project để chứng minh membership không cho phép trộn project A với batch/run của B.

Test dựng FastAPI với router runs thật dưới /api. Chỉ override get_session để dùng db_session trong transaction rollback của fixture chung; không override get_current_user, require_role hoặc require_project_member. JWT có chữ ký thật, secret ngẫu nhiên chỉ dùng trong test. Không mở lifespan graph, gọi LLM hoặc worker.

Fixture này phù hợp kiểm tra quyền trong một session. Chưa dùng nó để chứng minh commit qua process khác hoặc khôi phục sau restart. Sau mỗi test transaction ngoài rollback, không giữ lại user/project demo.

## Các nhóm kiểm chứng

| Nhóm | Điều được kiểm tra |
|---|---|
| Xác thực | Cả bốn endpoint từ chối thiếu token, token sai, hết hạn và user không tồn tại; trả 401 cùng WWW-Authenticate: Bearer |
| Membership | Outsider bị từ chối ở create/status/clarifications/design-decision |
| Role theo project | Reviewer ở A không được tạo run/trả lời/duyệt Cổng 1 của A dù là Engineer ở B |
| Liên kết tài nguyên | Batch/run của B dưới URL A trả 404; thử cả hai chiều, user có quyền ở cả hai |
| Reviewer đọc trạng thái | Membership của Reviewer đi qua bước phân quyền tới lookup; run thuộc project khác vẫn bị chặn |
| Tài nguyên không tồn tại | Batch/run ngẫu nhiên trả 404 khi user có quyền trong project |
| Project không tồn tại | Trả 403 qua membership, không lộ tài nguyên của project khác |
| Validation | Project/run/batch UUID sai, body thiếu trường, answers sai kiểu và decision sai giá trị trả 422 |
| Thu hồi quyền | Xóa membership hiện tại làm token còn hạn bị từ chối ở cả bốn endpoint |
| Lookup hợp lệ | Hai helper trả đúng bản ghi hiện có trong từng project |
| Không có tác dụng phụ | Request bị từ chối không đổi status/pending/error/updated_at của run, không tăng batch/run/job/design/approval và không trả dữ liệu riêng |

## Phạm vi kết luận

Khi viết C1, các route nghiệp vụ còn NotImplementedError sau lớp kiểm soát truy cập. Endpoint tạo run hiện đã được nối và kiểm chứng riêng trong [run-creation.md](run-creation.md). Bộ test C1 không coi HTTP 500 hoặc NotImplementedError là ca thành công.

Hai test helper kiểm tra lookup hợp lệ trực tiếp. Test membership polling dùng run không tồn tại: phản hồi 404 đúng từ lookup chứng minh Engineer và Reviewer đã qua lớp membership, chưa chứng minh API polling trả RunOut.

Các ca HTTP tạo run thành công đã được bổ sung ở C2; đọc trạng thái, clarification và quyết định Cổng 1 thành công tiếp tục ở C3/C4. Lỗi 409 theo trạng thái/interrupt cũng thuộc các bước đó. Bộ test này chưa nghiệm thu READY khi tạo run, graph/checkpoint, actor approval, chống resume trùng, Cổng 2 hoặc FR-21.

## Thay đổi đi kèm

Đã dọn import trùng và format [routes/runs.py](../../backend/app/api/routes/runs.py) sau khi ghép hướng dẫn C1. Giữ nguyên phần phân quyền/lookup đã viết và các stub nghiệp vụ. Không thay model, migration, dependency hoặc dữ liệu golden.

## Kết quả thực tế

Kết quả ở bảng dưới là lần kiểm chứng C1 trước khi nối C2. Kết quả regression mới nhất được ghi trong [run-creation.md](run-creation.md).

| Kiểm chứng | Kết quả |
|---|---|
| Test mới trong test_runs.py | **65 passed**, không skip; trích từ JUnit của toàn bộ regression |
| Toàn bộ backend | **665 passed, 17 skipped**, 173,75 giây |
| Ruff check | Qua trên backend, airflow, scripts |
| Ruff format check | Qua, 112 file |
| mypy strict | Qua, 104 source file |
| check_conventions.py | Qua |

17 skip gồm 16 TODO có sẵn ngoài phạm vi và test OULAD cần opt-in. Không có test C1 nào bị skip vì thiếu PostgreSQL.

Regression chạy trên dataforge_test. Log và JUnit local được Git bỏ qua:

- backend/data/upload-checks/run-access-regression.log.
- backend/data/upload-checks/run-access-regression.xml.

Lệnh regression đã chạy, từ backend:

~~~bash
.venv/bin/python -m pytest -q -rs \
  --junitxml=data/upload-checks/run-access-regression.xml
~~~

