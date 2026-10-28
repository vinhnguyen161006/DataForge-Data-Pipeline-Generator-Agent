# Kiểm chứng clarification và quyết định Cổng 1

Hoàn thiện ngày **23/10/2026**, cho C4 của Tú. API nhận một quyết định cho đúng điểm chờ, lưu quyết định vào PostgreSQL rồi tiếp tục LangGraph trên thread của run.

## Đọc code theo luồng

1. [schemas.py](../../backend/app/api/schemas.py): body có interrupt_id, quyết định thiết kế có thêm design_version_id; từ chối actor tự khai, câu trả lời rỗng và return thiếu feedback.
2. [routes/runs.py](../../backend/app/api/routes/runs.py): xác thực Engineer theo project, lookup run theo project URL, lấy actor từ token và gọi service.
3. [services/runs.py](../../backend/app/services/runs.py): kiểm tra trạng thái và checkpoint, nhận quyết định, lưu RunResumeIntent cùng thay đổi PipelineRun trong một transaction.
4. [run_lock.py](../../backend/app/services/run_lock.py): khóa advisory PostgreSQL theo run, dùng chung giữa API, drive, recovery và delivery.
5. [nodes.py](../../backend/app/graph/nodes.py): clarification quay về Modeler; Cổng 1 tạo phiên bản sửa/approval hoặc trả feedback về Modeler.
6. [run_views.py](../../backend/app/api/run_views.py): GET chỉ đọc projection đã lưu, gồm interrupt_id; không gọi graph để lấy ID trong mỗi request.

RunResumeIntent là biên nhận bền vững của một reply đã được chấp nhận. Nó khác Approval: clarification có biên nhận nhưng không tạo approval.

## Contract HTTP

Hai endpoint giữ response HTTP 200 với RunOut ở trạng thái RUNNING khi nhận thành công. Graph tiếp tục sau response; GET trả kết quả của bước tiếp theo khi projection đã được đồng bộ.

Từ GET hiện tại, lấy interrupt_id ở cấp RunOut. Với thiết kế, lấy thêm pending.design_version_id.

Clarification:

~~~json
{
  "interrupt_id": "<current-interrupt-id>",
  "answers": [
    {
      "question": "Include withdrawn registrations?",
      "answer": "Exclude withdrawals"
    }
  ]
}
~~~

Mỗi câu hỏi hiện tại phải có đúng một câu trả lời. Không thiếu, thừa, lặp hoặc đổi nội dung câu hỏi. Modeler không được tạo hai câu hỏi cùng text vì contract hiện dùng text để ghép câu trả lời.

Approve:

~~~json
{
  "interrupt_id": "<current-interrupt-id>",
  "design_version_id": "<presented-design-version-uuid>",
  "decision": "approve"
}
~~~

Để approve có sửa, thêm edited_design chứa DataDesign đầy đủ, hợp lệ. design_version_id vẫn là phiên bản đang được hiển thị; graph tự tạo phiên bản mới và gắn approval vào ID/hash của phiên bản mới.

Return:

~~~json
{
  "interrupt_id": "<current-interrupt-id>",
  "design_version_id": "<presented-design-version-uuid>",
  "decision": "return",
  "comment": "Exclude withdrawn registrations from this metric"
}
~~~

Return không nhận edited_design. Nếu cần sửa rồi duyệt, dùng approve kèm edited_design.

Không gửi user_id, approver_id hoặc actor_id. Route tạo ClarificationReply/DesignGateReply bằng engineer.id lấy từ xác thực.

| Tình huống | Kết quả |
|---|---|
| Thiếu/sai token | 401 |
| Reviewer hoặc ngoài project | 403 |
| Run không thuộc project URL | 404 |
| Sai cổng, interrupt/version cũ hoặc run đang được xử lý | 409 |
| Body, câu trả lời hoặc thiết kế sửa không hợp lệ | 422 |
| Hai request cùng interrupt | Một request được nhận; request còn lại 409 |

Sau 409, frontend tải lại run và để người dùng xem quyết định mới. Không tự thay ID rồi phát lại quyết định cũ. Draft clarification được phân biệt theo interrupt_id.

## Transaction, khóa và recovery

Luồng nhận:

~~~text
Engineer + project/run
→ khóa run
→ đọc trạng thái hiện hành và checkpoint
→ đối chiếu interrupt/version, validate reply
→ INSERT RunResumeIntent
→ UPDATE run: RUNNING, pending=None, interrupt_id=None
→ flush + refresh các giá trị do DB sinh
→ commit
→ trả response và lên lịch delivery sớm
~~~

Unique (run_id, interrupt_id) chặn nhận hai quyết định cho cùng một lần chờ. PostgreSQL session advisory lock giữ quyền điều phối qua các transaction của graph. Lượt chờ khóa dùng pg_try_advisory_lock và trả connection giữa các lần thử; lỗi/hủy lúc lấy hoặc nhả khóa làm connection không chắc chắn bị invalidated.

Background task chỉ giúp xử lý sớm. Vòng delivery hiện có quét các intent chưa delivered ở mỗi tick; startup recovery cũng xử lý các intent đã commit. Khi gọi graph, service chỉ định đúng interrupt bằng Command(resume={interrupt_id: reply}).

| Điểm dừng | Dữ liệu còn lại | Cách tiếp tục |
|---|---|---|
| Trước commit nhận reply | Chưa có biên nhận; run vẫn chờ | Người dùng gửi lại |
| Sau commit, trước gọi graph | Reply và actor ở RunResumeIntent | Backend mới delivery từ DB |
| Sau approval/edit commit, trước checkpoint node | Biên nhận chưa delivered; checkpoint còn bước cần tiếp tục | Replay dùng lại phiên bản/approval tương ứng |
| Sau graph tiến lên, trước delivered=True | Checkpoint đã qua interrupt cũ | Đồng bộ/tiếp tục từ checkpoint; không gửi reply cũ vào cổng mới |
| Restart khi chưa ai quyết định | Checkpoint và interrupt vẫn chờ | Giữ nguyên thiết kế/câu hỏi; không tự approve |

Node Cổng 1 kiểm tra quyết định đã lưu khi replay; không âm thầm thay actor, quyết định, hash, phiên bản hoặc comment bằng reply khác.

Validation nghiệp vụ dùng validate_design/validate_modeler_output thật. canonical_json_hash dùng JSON có thứ tự key ổn định, UTF-8 và không nhận NaN/Infinity. Các helper versioning khác ngoài nhu cầu Cổng 1 vẫn thuộc công việc tiếp theo.

## Migration

Migration [persist_human_run_resume_intents](../../backend/migrations/versions/20261020_ab8185d99a95_persist_human_run_resume_intents.py) thêm:

- PipelineRun.interrupt_id nullable.
- Bảng run_resume_intents, FK tới run và actor.
- Unique cho run_id/interrupt_id và index delivered.

Đã rà soát migration và chỉ áp dụng trên dataforge_test. Không chạy migration vào dataforge_app trong lượt này. Bảng checkpoint tiếp tục do LangGraph quản lý.

Sau khi môi trường khác được migrate, recovery đồng bộ interrupt_id cho các run đang chờ có checkpoint cũ.

## Chạy lại

Trong backend, Bash WSL, với PostgreSQL test đang chạy:

~~~bash
set -a
source .env.upload-checks
set +a

.venv/bin/python -m pytest   tests/integration/test_run_decisions.py   tests/unit/test_design_validation.py   -q -rs
~~~

Chạy cùng các phần runs trước:

~~~bash
.venv/bin/python -m pytest   tests/integration/test_runs.py   tests/integration/test_run_creation.py   tests/integration/test_run_polling.py   tests/integration/test_graph_design_gate.py   tests/integration/test_run_decisions.py   tests/unit/test_design_validation.py   -q -rs
~~~

Nếu chuẩn bị một DB test mới, làm theo hướng dẫn setup DB/checkpointer của repository và chạy alembic upgrade head với APP/TEST/CHECKPOINT cùng trỏ DB test. Thiếu DATAFORGE_TEST_DATABASE_URL làm test integration skip; không tính skip vì thiếu DB là đạt.

## Test và giới hạn bằng chứng

test_run_decisions.py dùng HTTP/auth thật, batch READY từ API, queue và PostgreSQL checkpoint thật. Mỗi test có application schema riêng; cleanup đúng schema/thread đã tạo. Backend mới dùng engine, saver, graph và HTTP client mới.

Các nhóm chính:

- Quyền Engineer, actor từ token và tài nguyên theo project.
- Approve, approve có sửa, return và clarification; kiểm tra ID/hash thiết kế được duyệt.
- Sai cổng, chờ worker, stale interrupt/version, câu trả lời thiếu/thừa/trùng và validation thiết kế.
- Hai backend cùng nhận/delivery một quyết định; chỉ có một intent/approval.
- Đóng backend sau nhận quyết định, trước delivery; mở backend khác và recovery.
- Crash sau approval đã commit nhưng node chưa checkpoint, gồm cả chỉnh sửa.
- Crash sau graph tiến lên nhưng chưa đánh dấu biên nhận delivered.
- Hủy tác vụ giữ/chờ khóa, không để lại chủ khóa cũ.
- GET polling tiếp tục bị chặn gọi điều phối, gồm deliver_resume_intents.

Modeler là fixture xác định. Codegen sau Cổng 1 là probe, có kiểm tra approval thật; chưa triển khai sinh mã tuần sau. Không cần Gemini hoặc worker thật để chạy bộ này. Approve trên graph production sẽ tới codegen còn stub cho đến khi phần đó được triển khai.

Test restart này đóng các tài nguyên backend và mở lại bằng kết nối mới; chưa thay thế diễn tập stop/SIGKILL backend process trong Compose ở E3. Worker, sandbox và toàn bộ FR-21 vẫn cần các bước D/E.

## Kết quả kiểm chứng

| Kiểm tra | Kết quả |
|---|---|
| test_run_decisions.py | **59 passed**, không skip |
| test_design_validation.py | **11 passed**, không skip |
| C1/C2/C3 + graph Cổng 1 + C4 + validation | **250 passed**, không skip |
| Toàn bộ backend | **841 passed, 17 skipped**, 353,31 giây |
| Ruff check / format | Qua; 119 file được kiểm tra format |
| mypy strict | Qua, 110 source file |
| check_conventions.py | Qua |
| Alembic check trên dataforge_test | Qua, không có schema drift |
| Frontend Biome / TypeScript / production build | Qua |

17 skip gồm 16 TODO có sẵn ngoài C4 và test OULAD cần bật riêng. Không có test C4 bị skip vì thiếu PostgreSQL.

Frontend CI dùng Node Linux và đúng package-lock.json trong bản sao tạm tại backend/data/upload-checks/frontend-ci vì công cụ Windows gặp lỗi đường dẫn UNC. Không thay dependency hoặc node_modules của frontend gốc.

Log và JUnit local được Git bỏ qua:

- backend/data/upload-checks/run-decisions-regression.log.
- backend/data/upload-checks/run-decisions-regression.xml.
- backend/data/upload-checks/run-decisions-frontend.log.
