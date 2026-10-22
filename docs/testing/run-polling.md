# Kiểm chứng GET trạng thái lượt chạy và polling

Thực hiện ngày **20/10/2026**, cho bước 5 của C3. Bộ test gọi router thật, xác thực JWT và membership thật, dùng PostgreSQL với session request/observer độc lập.

## File và cách chạy

- [test_run_polling.py](../../backend/tests/integration/test_run_polling.py): **70 test** về quyền, trạng thái, pending, lỗi công khai và tính chỉ đọc.
- [test_run_creation.py](../../backend/tests/integration/test_run_creation.py): thêm **1 test nối C2 → C3**, tên test_created_run_can_be_polled_without_advancing_its_job_or_checkpoint.

Tại thư mục backend trong Bash WSL:

~~~bash
set -a
source .env.upload-checks
set +a

.venv/bin/python -m pytest tests/integration/test_run_polling.py -q -rs
~~~

Chạy đủ 71 test C3, gồm ca nối C2:

~~~bash
.venv/bin/python -m pytest \
  tests/integration/test_run_polling.py \
  tests/integration/test_run_creation.py::test_created_run_can_be_polled_without_advancing_its_job_or_checkpoint \
  -q -rs
~~~

Chỉ chạy nhóm chứng minh GET không ghi DB:

~~~bash
.venv/bin/python -m pytest tests/integration/test_run_polling.py -k repeated_polling -vv
~~~

PostgreSQL test cần đang chạy. Bảng checkpoint cần setup cho ca nối C2 theo hướng dẫn repository. Thiếu DATAFORGE_TEST_DATABASE_URL sẽ làm integration test skip; skip vì thiếu DB không tính là đạt.

## Đối chiếu các nhóm đã yêu cầu

| Yêu cầu C3 | Bằng chứng |
|---|---|
| Engineer và Reviewer đọc được | test_members_can_poll_each_public_run_status: cả hai role trên mọi giá trị RunStatus |
| Không token hoặc ngoài project | test_polling_requires_authentication_and_project_membership |
| Run B dưới URL A | test_polling_rejects_a_run_under_the_wrong_project_even_with_both_memberships: hai chiều, cả Engineer và Reviewer đều có membership trong A và B |
| Run không tồn tại / UUID sai / thu hồi membership | Các test unknown_run, validates_url_identifiers và rechecks_membership |
| Đúng status và pending | WAITING_JOB → job; WAITING_CLARIFICATION → clarification; WAITING_DESIGN_APPROVAL → design_gate |
| Pending hỏng hoặc sai loại | test_invalid_persisted_pending_returns_a_fixed_server_error: 13 biến thể trả 500 với detail cố định, giữ nguyên dữ liệu DB |
| Không lộ trường nội bộ | test_polling_removes_undeclared_internal_fields_from_nested_pending: kiểm tra root và các model câu hỏi/thiết kế lồng nhau |
| Không lộ exception | test_failed_run_exposes_only_the_public_error_message: 6 biến thể, gồm traceback, DSN, đường dẫn, token giả và lỗi rỗng |
| Không lộ lỗi/pending cũ | Các test nonfailed_run và hides_stale_pending |
| Không lộ tên node ngoài contract | test_polling_does_not_expose_unknown_internal_step_names |
| GET nhiều lần không làm pipeline tiến | test_repeated_polling_preserves_database_rows_and_only_executes_selects |
| Đọc thay đổi đã commit | test_polling_observes_changes_committed_by_another_session |
| API mới đọc cùng dữ liệu | test_a_fresh_api_instance_reads_the_same_persisted_pending |
| GET đồng thời | test_concurrent_polling_reads_the_same_snapshot_without_writes |
| Đọc run thật đã tạo ở C2 | Ca nối C2 kiểm tra cùng run/job/interrupt/checkpoint trước và sau GET |

## Fixture hoạt động thế nào?

RunPollingScenario tạo ba user, hai project, mỗi project một batch/run/job/design version riêng. Engineer và Reviewer có role tương ứng trong cả hai project; Outsider không có membership.

Setup được commit trước request. Router dùng get_session thật từ app.state.sessionmaker; không override get_current_user, role hoặc membership. Helper persisted mở session observer mới để so sánh toàn bộ các hàng run/job/design/approval thuộc fixture.

Fixture trạng thái dùng dữ liệu tổng hợp để kiểm tra projection API. Batch ở đây không đại diện cho luồng tạo run hợp lệ qua C2. Ca nối C2 riêng dùng upload/confirm/READY thật, graph thật, queue thật và Postgres checkpoint thật.

Timestamp setup được ghi tường minh bằng UPDATE để tránh SQLAlchemy onupdate thay mốc thời gian khi tạo tình huống test. Test xác nhận GET trả timestamp đã lưu và không đổi nó thành thời điểm đọc.

Design dùng minimal_design từ tests/designs.py; hash metadata được tính riêng trong fixture bằng thư viện chuẩn, không gọi helper versioning còn stub. Bộ này không nghiệm thu thuật toán fingerprint/versioning.

Cleanup chỉ xóa đúng UUID user/project/run của fixture, không đụng dữ liệu demo hoặc dữ liệu khác. Ca nối C2 dùng cơ chế schema/storage/checkpoint tạm của fixture C2 có sẵn.

## Chứng minh GET chỉ đọc

Trong toàn bộ module polling, test chặn các hàm sau bằng AsyncMock và assert chúng không bị gọi:

- start_run, drive_run, resume_run, sync_run.
- deliver_finished_jobs, recover_pending_runs.
- queue.enqueue và modeler.propose_design.

Nhóm GET lặp lại còn thực hiện:

1. Ghi snapshot đầy đủ các hàng run/job/design/approval trước request.
2. Gọi GET năm lần, so sánh toàn bộ response và updated_at.
3. Theo dõi before_cursor_execute của SQLAlchemy: mọi câu SQL trong request phải là SELECT.
4. Chặn AsyncSession.commit để phát hiện commit trong endpoint.
5. Mở session mới và so sánh dữ liệu sau GET với snapshot ban đầu.

Ca nối C2 chặn thêm graph.ainvoke và graph.aget_state trong thời gian GET. Sau đó kiểm tra checkpoint config/values/interrupt, job ID, số hàng và updated_at vẫn giữ nguyên. Vì vậy polling không phụ thuộc vào việc gọi graph hoặc đồng bộ checkpoint ngay trong request.

## Phạm vi kết luận

GET trả dữ liệu từ PipelineRun; đồng bộ checkpoint/projection thuộc service điều phối và recovery. Không sửa nghiệp vụ runs hoặc run_views trong lượt bổ sung test này.

Test trường nội bộ tập trung vào các key ngoài schema và error exception. Pydantic không tự phân loại thông tin nhạy cảm nằm trong một chuỗi nghiệp vụ hợp lệ; nguồn tạo câu hỏi/thiết kế vẫn phải giữ hợp đồng không đưa raw rows hoặc secret vào pending.

WAITING_CODE_APPROVAL được kiểm tra như một giá trị trạng thái với pending=None. Nội dung pending và luồng Cổng 2 chưa được nghiệm thu.

API instance mới trong test đọc DB qua session mới, nhưng không phải diễn tập tắt process/Compose. Resume Cổng 1, frontend tự polling trong trình duyệt, worker/sandbox và FR-21 đầy đủ tiếp tục ở các bước tương ứng.

## Kết quả thực tế

Nhóm tập trung: **71 passed trong 24,48 giây**, không skip.

| Kiểm chứng | Kết quả |
|---|---|
| Nhóm C3 tập trung | **71 passed**, không skip |
| C1 + C2 + C3 trong regression | **171 passed**, không skip |
| Toàn bộ backend | **771 passed, 17 skipped**, 238,62 giây |
| Ruff check / format | Qua, 115 file được kiểm tra format |
| mypy strict | Qua, 107 source file |
| check_conventions.py | Qua |

17 skip gồm 16 TODO có sẵn ngoài phạm vi và test OULAD cần bật riêng. Không có test C1/C2/C3 nào bị skip vì thiếu PostgreSQL.

Lệnh regression đã chạy sau khi nạp cấu hình DB test:

~~~bash
.venv/bin/python -m pytest -q -rs --junitxml=data/upload-checks/run-polling-regression.xml
~~~

Không có thay đổi dependency, model hoặc migration trong bước này.


Log và JUnit local được Git bỏ qua:

- backend/data/upload-checks/run-polling-tests.log và run-polling-tests.xml.
- backend/data/upload-checks/run-polling-regression.log và run-polling-regression.xml.

Bổ sung C4: [Kiểm chứng clarification và quyết định Cổng 1](run-decisions.md) ghi contract mới, migration, cách chạy test và bằng chứng recovery.
