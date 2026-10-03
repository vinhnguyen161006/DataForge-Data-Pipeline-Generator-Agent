# WORKLOG — DataForge

Kế hoạch và nhật ký công việc 6 tuần, từ **2026-10-02** đến **2026-11-12**. Giao task theo tuần, **họp chốt vào cuối mỗi tuần**; kết quả họp ghi vào mục "Chốt tuần" của đúng tuần đó.

Vì dự án bắt đầu thứ Sáu 02/10, mỗi "tuần" tính từ **thứ Sáu đến thứ Năm**; buổi họp chốt diễn ra vào **thứ Năm cuối mỗi tuần**. Nếu nhóm muốn họp cuối tuần theo lịch thường, dịch cả sáu mốc lên hai ngày và cập nhật lại các ngày trong file này.

Nguồn yêu cầu: [docs/đặc tả.md](docs/đặc tả.md). Quy ước code và nguyên tắc bất biến: [CLAUDE.md](CLAUDE.md). Ranh giới module: [ARCHITECT.md](ARCHITECT.md).

---

## 1. Đội ngũ và vùng sở hữu

| Thành viên | Vai trò | Vùng sở hữu chính |
|---|---|---|
| **Vinh** | Full stack, AI | Điều phối LangGraph (`graph/`, `services/runs`), vòng sửa lỗi Codegen, `compare/multiset` (đối chiếu tương đương), toàn bộ frontend, tích hợp end-to-end, triển khai demo |
| **Tuấn Anh** | AI | Agent LLM (`agents/`: llm, modeler, codegen, prompts), `optimizer/rules.py`, `compare/benchmark`, retrieval Qdrant, ablation, gói xuất ZIP/PR |
| **Tú** | Backend, AI | Auth/phân quyền, hàng đợi job, sandbox worker, `agents/optimizer` (đề xuất rewrite), `services/approvals` + `versioning`, API routes, tích hợp Airflow (chạy lại theo lịch) |
| **Tuấn** | BA, Data | Golden dataset, bản thiết kế chuẩn, bảng kết quả chuẩn, kịch bản nghiệm thu, danh mục lỗi tiêm, báo cáo và tài liệu |
| **Ánh** | Data | `ingest/`, `profiler/` (hồ sơ, dò khóa và quan hệ), `codegen/bronze`, chuẩn hóa golden dataset, chạy bộ eval và tổng hợp số liệu |
| **Trí** | Backend, AI | Hạ tầng Compose/CI, khóa phiên bản, `codegen/guard` + `codegen/project` + `codegen/tests`, `optimizer/judge` (phán xét xác định), DAG template, `publisher/`, `metabase/`, nghiệm thu ZIP |

Mỗi module có một chủ sở hữu để tránh giẫm chân; người khác muốn sửa thì mở PR và nhờ chủ sở hữu review.

Bốn người có kĩ năng AI (Vinh, Tuấn Anh, Tú, Trí) đều giữ một phần của vòng LLM; Ánh làm thuần Data. Hai cặp sau **bắt buộc khác người** để giữ nguyên tắc bất biến 1 (LLM đề xuất, công cụ xác định phán xét — không ai tự chấm mình):

| Bên đề xuất (LLM) | Bên phán xét (xác định) |
|---|---|
| Tú — `agents/optimizer.py` đề xuất rewrite | Trí — `optimizer/judge.py` quyết định giữ/loại |
| Tuấn Anh — `agents/codegen.py` sinh silver/mart | Trí — `codegen/tests.py` sinh test từ ràng buộc đã duyệt; Vinh — `compare/multiset` đối chiếu |

## 2. Quy ước chung cho mọi task

- Mỗi task xong khi: code theo quy ước [CLAUDE.md](CLAUDE.md) mục 10, **bỏ `TODO:` khỏi docstring và thay `skip` bằng test thật**, và CI xanh (`conventions`, `backend-lint`, `backend-test`, `frontend`).
- Code, docstring, chuỗi lỗi, prompt viết bằng **tiếng Anh**; **không comment** trong code. Tài liệu `*.md` được dùng tiếng Việt.
- Dependency mới ghim phiên bản chính xác; không dùng `latest`; không nâng lẻ dbt-core / dbt-duckdb / duckdb.
- Task đụng tới một trong 12 nguyên tắc bất biến (CLAUDE.md mục 2): dừng lại, hỏi cả nhóm trước khi làm.
- Đổi `app/db/models.py` thì kèm migration Alembic đã review tay và `alembic check` xanh.
- Mã `FR-xx` trong ngoặc là yêu cầu chức năng tương ứng trong đặc tả.
- Đánh dấu `[x]` khi xong; việc không kịp thì **không xóa**, chuyển sang "Chuyển tuần sau" ở mục Chốt tuần.

## 3. Tổng quan 6 tuần

| Tuần | Thời gian | Chủ đề | Mốc kết thúc tuần (demo được) |
|---|---|---|---|
| 1 | 02/10 – 08/10 | Nền móng, khóa phiên bản, dữ liệu chuẩn | `docker compose up` sạch; CI xanh; đăng nhập được; nạp CSV đoán đúng cấu hình; queue chạy |
| 2 | 09/10 – 15/10 | Nạp → Profiler → Modeler → **Cổng 1** | Upload OULAD → hồ sơ → bản thiết kế đủ 6 nội dung → duyệt/trả lại trên UI |
| 3 | 16/10 – 22/10 | Codegen + chạy cách ly + đo | Sau Cổng 1, sinh dbt 3 tầng, `dbt compile` + build trong sandbox, có số đo từng model |
| 4 | 23/10 – 29/10 | Optimizer + **Cổng 2** + Publisher | Rewrite sai bị loại; sửa mã sau duyệt làm mất hiệu lực; mart nạp được vào Postgres |
| 5 | 30/10 – 05/11 | Metabase + Airflow + Xuất mã + E2E | Chạy trọn luồng OULAD trên UI tới link dashboard; tải ZIP; mở PR; chạy lại theo lịch |
| 6 | 06/11 – 12/11 | Eval, nghiệm thu 4 tình huống, triển khai, bàn giao | Bảng eval đủ 8 nhóm chỉ số; ZIP dựng lại trên máy sạch; demo chạy ổn trên bản triển khai |

Tuần 5 và 6 là nơi rủi ro tích hợp dồn lại. Nếu tuần 3–4 trượt, **cắt phạm vi ở tuần 6 (ablation, baseline người, bộ eval thứ ba) trước, không cắt 4 tình huống nghiệm thu bắt buộc**.

---

## Tuần 1 — Nền móng, khóa phiên bản, dữ liệu chuẩn (02/10 – 08/10)

**Mục tiêu:** môi trường dev chạy ổn cho cả 6 người; khóa tổ hợp phiên bản Airflow + dbt-core + dbt-duckdb + DuckDB (đặc tả yêu cầu chốt trong tuần đầu); có golden dataset; hoàn thành các phần nền (auth, queue, ingest, LLM client).
**FR liên quan:** FR-01, FR-20 (phần 1).

### Vinh
- [ ] Rà skeleton toàn repo, viết ghi chú ngắn "cách chạy local" cho cả nhóm (uv sync, pytest, compose, frontend) và xác nhận mọi người chạy được.
- [ ] Chốt quy trình nhánh: nhánh `develop`, PR vào `develop`, tối thiểu 1 review, CI xanh mới merge; bật bảo vệ nhánh `main`/`develop`.
- [ ] `app/main.py`: hoàn thiện `lifespan` (khởi tạo checkpointer, engine, đóng tài nguyên khi tắt); `core/logging.py`.
- [ ] Frontend: `api/client.ts`, `api/types.ts` khớp `app/api/schemas.py`; routing trong `App.tsx`; `LoginPage`, `ProjectsPage` (danh sách + tạo dự án).
- [ ] Chốt luồng state của LangGraph cùng Tú và Tuấn Anh: review `graph/state.py` và `graph/builder.py`, ghi các điểm interrupt (Cổng 1, Cổng 2, hỏi lại).

### Tuấn Anh
- [ ] `agents/llm.py`: client Gemini (`gemini-3.5-flash-lite`), structured output validate bằng Pydantic v2, retry có giới hạn, ghi số token mỗi lần gọi (phục vụ chỉ số chi phí token ở eval). Test bằng mock, không gọi API thật trong CI.
- [ ] Review `agents/schemas.py` (`DataDesign`) cùng Tuấn: đủ **sáu nội dung** (grain, khóa và quan hệ, định nghĩa chỉ số, quy tắc làm sạch, quy tắc cập nhật, yêu cầu dashboard), mỗi mục có trường lý giải và danh sách câu hỏi mở.
- [ ] Spike Modeler: thử prompt với một `DataProfile` OULAD viết tay, ghi nhận Gemini trả gì, thiếu gì.
- [ ] Spike embedding `gemini-embedding-001` và kiểm tra khả năng kết nối Qdrant v1.19.1 trong Compose.

### Tú
- [ ] `core/security.py` (băm mật khẩu, token), `api/deps.py` (xác thực, `require_role`), `routes/auth.py`, `routes/projects.py` (FR-20: phân quyền theo dự án, hai vai trò Engineer/Reviewer).
- [ ] `jobs/queue.py`: enqueue, claim bằng `FOR UPDATE SKIP LOCKED`, lease, retry, phục hồi job treo, `serial_key`. Integration test (cần `DATAFORGE_TEST_DATABASE_URL`).
- [ ] Xác nhận bảng nào còn thiếu trong `db/models.py` cho approvals, batches, runs; nếu thiếu, tạo migration.
- [ ] Spike DuckDB profiling: chạy `EXPLAIN ANALYZE` trên một query mẫu, xác định lấy được **thời gian chạy, số dòng quét, bộ nhớ đỉnh** ở đâu — nền cho `agents/optimizer.py` tuần 4 và đo hiệu năng tuần 3.

### Tuấn
- [ ] Thu thập và chuẩn hóa **OULAD** (7 CSV) vào `eval/golden/oulad/`, kèm data dictionary tiếng Việt cho từng cột.
- [ ] Chọn **hai bộ công khai còn lại** cho golden set. Tiêu chí đề xuất: nhiều bảng, có khóa ghép, có quan hệ một–nhiều, kích thước chạy được trên máy dev; ít nhất một bộ có cột mơ hồ kiểu `amount` để thử hỏi lại (FR-05). Chốt với nhóm cuối tuần.
- [ ] Viết bộ **user story + checklist nghiệm thu** cho 21 FR (một dòng "xong khi" mỗi FR, bám cột tiêu chí trong đặc tả) làm cơ sở nghiệm thu các tuần sau.
- [ ] Bắt đầu viết **bản thiết kế chuẩn OULAD** (grain, khóa, quan hệ, chỉ số, làm sạch, dashboard).

### Ánh
- [ ] `ingest/sniff.py` (FR-01): đoán encoding, dấu phân cách, ký hiệu null, định dạng ngày; trả preview vài dòng. Unit test với CSV khó (BOM, `;`, quote lẫn xuống dòng, null là `NA`/`?`/rỗng).
- [ ] `ingest/storage.py`: bố cục volume (file gốc nguyên vẹn + cấu hình đọc + manifest lô), kiểm tra không ghi đè file gốc.
- [ ] Chạy thử sniff trên toàn bộ file golden Tuấn đã chuẩn bị, lập danh sách file nào đoán sai.

### Trí
- [ ] **Khóa tổ hợp phiên bản** Airflow 3.3.2 + dbt-core + dbt-duckdb + DuckDB: dựng thử, chạy `dbt --version` trong `/opt/dbt-venv`, chạy một dbt project mẫu bằng DuckDB, biên dịch lại `airflow/dbt/requirements.txt` có hash; ghi kết quả vào mục Chốt tuần.
- [ ] Chạy toàn stack `docker compose up -d --build` trên máy sạch; xác nhận `migrate` xong thì backend, worker, publisher mới lên; mạng `sandbox` đúng `internal: true`.
- [ ] Xác nhận `infra/postgres/init.sh` tạo đủ 4 database + role (publisher ghi, `metabase_reader` chỉ đọc); khởi động Metabase v0.63.18.4 và tạo kết nối chỉ đọc tới warehouse.
- [ ] Đưa job CI `images` và `security` chạy xanh trên `develop`.
- [ ] Cùng Vinh chốt **hợp đồng giữa `compare/` và `optimizer/judge.py`** (ai trả gì, kiểu dữ liệu nào) để tuần 4 hai người làm song song không chặn nhau.

### Chốt tuần 1
- Kết quả đạt:
- Tổ hợp phiên bản đã khóa (ghi cụ thể):
- Hai bộ dữ liệu công khai đã chọn:
- Vấn đề / rủi ro:
- Quyết định của cuộc họp:
- Chuyển tuần sau:

---

## Tuần 2 — Nạp → Profiler → Modeler → Cổng 1 (09/10 – 15/10)

**Mục tiêu:** Engineer upload CSV + yêu cầu, hệ thống lập hồ sơ, Modeler đề xuất thiết kế (hỏi lại khi mơ hồ), Engineer duyệt/sửa/trả lại ở Cổng 1; chưa có mã nào được sinh khi chưa duyệt.
**FR liên quan:** FR-01, FR-02, FR-03, FR-04, FR-05, FR-06, FR-20, FR-21 (nền).

### Vinh
- [ ] `graph/nodes.py`: node `profile`, `model`, `ask_user`, `design_gate` (interrupt); `graph/builder.py` nối vòng "hỏi lại → Modeler" và "trả lại → Modeler". Test bằng `InMemorySaver`, không cần FastAPI.
- [ ] `services/runs.py`: `start`, `resume` cho Cổng 1; đảm bảo không sinh mã khi chưa có xác nhận (FR-06).
- [ ] Frontend `UploadPage`: tải nhiều CSV, hiển thị preview + cấu hình đọc để xác nhận/sửa, nhập yêu cầu (FR-01).
- [ ] Frontend `DesignGatePage`: hiển thị đủ 6 nội dung kèm lý giải, các câu hỏi cần trả lời, nút Duyệt / Sửa trực tiếp / Trả lại. `hooks/useRunPolling.ts` (polling thay WebSocket).

### Tuấn Anh
- [ ] `agents/modeler.py` + `agents/prompts/modeler.md`: sinh `DataDesign` đủ 6 nội dung, mỗi lựa chọn kèm lý giải (FR-04); **hỏi lại thay vì đoán** khi grain/nghiệp vụ mơ hồ (FR-05).
- [ ] Test chứng minh `agents` chỉ nhận `DataProfile`, không nhận đường dẫn file hay dòng dữ liệu (nguyên tắc 2).
- [ ] Chạy Modeler trên 3 dataset golden, so với bản thiết kế chuẩn của Tuấn; ghi các lỗi hay gặp và chỉnh prompt.

### Tú
- [ ] `routes/batches.py` + `services/batches.py`: upload lô, lưu manifest, đánh dấu "sẵn sàng" khi bộ file đủ (nền cho FR-16).
- [ ] `routes/runs.py`: tạo lượt chạy, đọc trạng thái (cho polling), resume Cổng 1; kiểm tra quyền theo dự án.
- [ ] `worker/main.py` + `worker/runner.py` job `profile`; `worker/sandbox.py`: env allowlist, rlimit, timeout, `DUCKDB_LOCKDOWN_SETTINGS`; mỗi lượt một workspace + một file DuckDB riêng.
- [ ] Test khôi phục (FR-21): dừng backend khi đang chờ Cổng 1, khởi động lại, lượt chạy vẫn ở đúng điểm dừng.

### Tuấn
- [ ] Hoàn tất **bản thiết kế chuẩn** (6 nội dung) cho cả 3 dataset, ở dạng dữ liệu có cấu trúc khớp `DataDesign`, đặt trong `eval/golden/`.
- [ ] Soạn danh sách **câu hỏi mơ hồ** mà Modeler đáng lẽ phải hỏi (ví dụ `amount` là đơn giá hay thành tiền) cho từng dataset, làm đáp án chuẩn của FR-05.
- [ ] Viết **rubric chấm chất lượng thiết kế** (grain, khóa, quan hệ; chấp nhận nhiều thiết kế hợp lệ) và đưa cho Ánh/Tuấn Anh dùng ở `eval/`.
- [ ] Chấm thủ công vòng 1 đầu ra của Modeler theo rubric, báo lại Tuấn Anh.

### Ánh
- [ ] `profiler/profile.py` (FR-02): kiểu suy ra, tỉ lệ null, số giá trị phân biệt, min/max, mẫu giá trị; **không đưa dữ liệu thô vào `DataProfile`**.
- [ ] Dò **khóa chính ứng viên** kể cả khóa ghép và **quan hệ ứng viên** giữa các file (FR-03): tỉ lệ khớp khóa, số bản ghi không tìm thấy cha, **cảnh báo fan-out khi join**.
- [ ] Hoàn thiện `profiler/schemas.py`; unit test bằng CSV nhỏ có khóa ghép và orphan có chủ đích.
- [ ] Đo thời gian profile trên bảng lớn nhất của OULAD (khoảng 10,6 triệu dòng); nếu chậm, tối ưu truy vấn DuckDB.

### Trí
- [ ] `codegen/guard.py`: allowlist cho SQL/macro/Python do LLM sinh (chặn đọc/ghi file tùy ý, `ATTACH`, `INSTALL`, `COPY ... TO`, gọi hệ thống…); unit test các mẫu tấn công.
- [ ] Rà lại Compose: volume bền vững dùng chung worker ↔ Airflow, sandbox worker không thấy Qdrant/Metabase/Airflow/Internet, worker không nhận biến môi trường chứa DSN warehouse (kiểm tra bằng test).
- [ ] Spike Metabase REST API: đăng nhập, đồng bộ metadata, tạo một card + dashboard mẫu bằng script, ghi lại các điểm cần coi chừng (độ trễ sync, ID).
- [ ] Rà `.env.example` (root và backend), bảo đảm không có secret thật; chạy `gitleaks` cục bộ.

### Chốt tuần 2
- Kết quả đạt:
- Điểm Modeler so với thiết kế chuẩn (sơ bộ):
- Vấn đề / rủi ro:
- Quyết định của cuộc họp:
- Chuyển tuần sau:

---

## Tuần 3 — Codegen, chạy cách ly, đo hiệu năng (16/10 – 22/10)

**Mục tiêu:** sau Cổng 1, hệ thống sinh dbt project ba tầng + test + DAG config, chạy trong sandbox và ghi đo từng model. `dbt compile` thành công.
**FR liên quan:** FR-07, FR-08, FR-09, FR-10, FR-11.

### Vinh
- [ ] `graph/nodes.py`: node `codegen`, `run_sandbox` và **vòng sửa lỗi** (compile/test fail → Codegen sửa) có ngân sách số lần tối đa; không tự chấm kết quả bằng LLM (nguyên tắc 1).
- [ ] `services/runs.py`: enqueue job `dbt_build`, nhận kết quả từ worker qua bảng job.
- [ ] Frontend `RunPage`: tiến trình theo bước, log, bảng đo từng model (thời gian, số dòng quét, bộ nhớ đỉnh), trạng thái test.
- [ ] Bắt đầu `compare/multiset.py` (schema khớp + multiset có đếm số lần xuất hiện từng dòng), hoàn thiện ở tuần 4.
- [ ] Review chéo PR của Tuấn Anh/Tú về ranh giới `graph` ↔ `agents` ↔ `jobs`.

### Tuấn Anh
- [ ] `agents/codegen.py` + `agents/prompts/codegen.md`: **chỉ sinh** `models/silver/*.sql` và `models/mart/*.sql` (bronze, schema test, `dag_config.json` sinh xác định); output validate bằng Pydantic.
- [ ] `retrieval/store.py`: index kho mẫu (mô tả yêu cầu, dbt model) vào Qdrant bằng `gemini-embedding-001`, truy xuất vài mẫu gần nhất đưa vào ngữ cảnh Codegen.
- [ ] **Chống rò rỉ**: kho mẫu tách khỏi tập đo, cả biến thể cùng tác vụ và cùng dataset; viết test kiểm tra loại trừ.
- [ ] Nạp kho mẫu từ dự án dbt mã nguồn mở (kiểm tra giấy phép); Tuấn hỗ trợ chọn mẫu và viết mô tả yêu cầu.

### Tú
- [ ] `worker/runner.py` job `dbt_build`: chạy dbt + DuckDB trong sandbox, thu **thời gian chạy, số dòng quét, bộ nhớ đỉnh, kết quả test từng model** (FR-11) từ DuckDB profiling và `run_results.json`.
- [ ] Bảo đảm giới hạn RAM, CPU, thời gian, dung lượng thực sự có hiệu lực (test với model cố tình ăn tài nguyên) và worker không có đường ra warehouse (FR-10).
- [ ] `versioning.py` (`VersionParts`, fingerprint, `StaleApprovalError`) và `services/approvals.py`: phê duyệt gắn với thiết kế + mã + test + lô + lượt chạy + báo cáo (nguyên tắc 8). Unit test: đổi một byte mã → fingerprint đổi → phê duyệt cũ không dùng được.
- [ ] Lưu báo cáo kiểm chứng của từng phiên bản dạng dữ liệu có cấu trúc, có version.

### Tuấn
- [ ] Viết **bảng kết quả chuẩn** (đáp án viết tay) cho từng tác vụ của 3 dataset: bảng mart/chỉ số nào, bao nhiêu dòng, giá trị mẫu; lưu trong `eval/golden/`.
- [ ] Soạn **danh mục lỗi tiêm có chủ đích** theo tầng: bronze (bản ghi lỗi vẫn được nhận), silver (null khóa, trùng lặp, sai kiểu), mart (khóa mồ côi, vi phạm ràng buộc); mô tả để Ánh cài vào `eval/fault_injection.py`.
- [ ] Review SQL silver/mart do Codegen sinh trên OULAD dưới góc BA: định nghĩa chỉ số có đúng như đã duyệt ở Cổng 1 không; ghi lại sai lệch.
- [ ] Kiểm tra bộ test sinh ra có thực sự từ **ràng buộc đã duyệt**, không phải từ quan sát thống kê (nguyên tắc 9).

### Ánh
- [ ] `codegen/bronze.py` (FR-07): bronze giữ biểu diễn nguồn, **không ép kiểu nghiệp vụ** (`00123` giữ nguyên), mỗi dòng có `batch_id`, tên file, định danh dòng, thời điểm nạp, chấp nhận bản ghi lỗi.
- [ ] Chuẩn bị dữ liệu silver/mart mẫu để Vinh và Trí có đầu vào test `compare/` và `codegen/tests.py`: bảng nhỏ có NULL, float, timestamp, dòng trùng.
- [ ] Rà kết quả bronze trên 3 dataset golden: đếm bản ghi lỗi từng file, xác nhận `00123` không bị ép kiểu, báo số liệu cho Tuấn.

### Trí
- [ ] `codegen/tests.py` (FR-08): sinh test **chỉ từ ràng buộc đã duyệt ở Cổng 1**, áp đúng tầng (bronze chấp nhận lỗi, silver cách ly kèm lý do và đếm, mart đạt ràng buộc); macro `dataforge_*` trong `templates/dbt_project/macros/`. Unit test: ràng buộc chưa duyệt → **không** sinh test bắt buộc; quan sát thống kê chỉ ra cảnh báo (nguyên tắc 9).
- [ ] `codegen/project.py` + `templates/dbt_project/` (`dbt_project.yml.j2`, `profiles.yml.j2`): lắp ráp dbt project từ bronze/silver/mart/test; `dbt compile` phải thành công (FR-07).
- [ ] Sinh `dag_config.json` xác định và hoàn thiện `airflow/dags/dataforge_pipelines.py` (template cố định, chỉ đọc cấu hình, không nạp Python tùy ý) (FR-09).
- [ ] `airflow/tests/`: test DagBag integrity (DAG import được); thêm vào CI job `images`.
- [ ] `metabase/client.py`: đăng nhập, đồng bộ metadata, tạo/cập nhật card và dashboard qua REST API (dựa trên spike tuần 2), có retry.

### Chốt tuần 3
- Kết quả đạt (OULAD sinh được mã? `dbt compile` thành công?):
- Số đo mẫu (thời gian / dòng quét / bộ nhớ đỉnh):
- Vấn đề / rủi ro:
- Quyết định của cuộc họp:
- Chuyển tuần sau:

---

## Tuần 4 — Optimizer, Cổng 2, Publisher (23/10 – 29/10)

**Mục tiêu:** vòng tối ưu có kiểm chứng (loại rewrite sai, giữ bản hợp lệ tốt nhất); Cổng 2 gắn với một phiên bản cụ thể; mart được nạp vào Postgres qua staging mà không phá phiên bản đang phục vụ.
**FR liên quan:** FR-12, FR-13, FR-14, FR-20, FR-21. **Tình huống bắt buộc:** #1 (rewrite nhanh hơn nhưng đổi kết quả), #2 (sửa mã sau duyệt), #3 (một lô chạy hai lần).

### Vinh
- [ ] `graph/nodes.py`: node `optimize` (xếp hạng query → đề xuất → chạy lại → đối chiếu, trong ngân sách), `code_gate` (interrupt Cổng 2) và nhánh "trả lại → Codegen".
- [ ] Frontend `CodeGatePage`: Monaco diff mã, kết quả test, **bảng so sánh hiệu năng trước/sau**, nhật ký rewrite bị loại kèm 4 loại lý do, cấu hình dashboard; nút duyệt chỉ hiện với Reviewer.
- [ ] UI báo rõ khi phê duyệt cũ mất hiệu lực (`StaleApprovalError`) và yêu cầu chạy lại.
- [ ] `compare/multiset.py` (hoàn thiện — tiêu chí **TƯƠNG ĐƯƠNG**): schema đầu ra khớp; so sánh **multiset có đếm số lần xuất hiện từng dòng**, không chỉ row count; quy tắc rõ cho NULL, số thực (dung sai) và timestamp; cố định giá trị phụ thuộc thời gian (`now()`, `current_date`, random) qua tham số. Unit test bằng bộ ca của Ánh.
- [ ] Giữ **hai phép kiểm chứng tách biệt**, không gộp: (1) đầu ra vs đáp án chuẩn, (2) sau rewrite vs trước rewrite.
- [ ] Ghi chú trên UI: đây là tối ưu **thời gian dựng dữ liệu trên DuckDB**, không tuyên bố dashboard Postgres nhanh hơn.

### Tuấn Anh
- [ ] `optimizer/rules.py`: các rewrite theo quy tắc bằng **sqlglot** trên SQL đã compile (đẩy filter xuống, bỏ subquery/CTE thừa, tránh join làm tăng dòng); mỗi rule có unit test giữ nguyên ngữ nghĩa.
- [ ] `compare/benchmark.py` (tiêu chí **NHANH HƠN**): chạy lặp, lấy **median**, ước lượng biên độ nhiễu; "nhanh hơn" chỉ khi cải thiện vượt nhiễu; đo cả từng model và toàn pipeline. Cùng dữ liệu, cùng phiên bản engine, cùng cấu hình tài nguyên.
- [ ] Phối hợp Tú: `rules.py` và `agents/optimizer.py` dùng chung một kiểu ứng viên rewrite (Pydantic) để `judge` của Trí xử lý được cả hai nguồn.
- [ ] Chỉnh prompt Codegen theo lỗi compile/test thu được từ vòng sửa lỗi tuần 3 của Vinh.
- [ ] Ghi token mỗi lần gọi agent cho toàn bộ luồng (chỉ số chi phí ở eval).

### Tú
- [ ] `routes/runs.py`: endpoint duyệt Cổng 1/Cổng 2, `require_role` (chỉ Reviewer duyệt Cổng 2); chế độ nhóm Reviewer ≠ Engineer; chế độ cá nhân **ghi rõ "không có review độc lập" vào nhật ký**; lịch sử duyệt gắn với dự án (FR-20).
- [ ] `agents/optimizer.py` + `agents/prompts/optimizer.md`: xếp hạng query theo thời gian chạy rồi **đề xuất rewrite** cho các query chậm nhất; output validate bằng Pydantic v2. Chỉ đề xuất — không tự kết luận giữ/loại (nguyên tắc 1).
- [ ] **Ngân sách vòng lặp** optimizer: số ứng viên tối đa, số lần sửa lỗi tối đa, thời gian tối đa, điều kiện dừng; ghi thời gian tìm rewrite mỗi lượt.
- [ ] `worker/runner.py` job `rewrite_benchmark`: chạy lặp, cùng dữ liệu/engine/tài nguyên, trả số đo thô cho `judge` của Trí.
- [ ] Integration test **tình huống #2**: duyệt xong rồi sửa mã → phê duyệt cũ mất hiệu lực, không công bố được bằng phê duyệt cũ, phải chạy lại và duyệt lại (FR-13).
- [ ] Integration test FR-21 với Cổng 2 và job đang chạy: restart backend/worker, lease hết hạn thì job được nhận lại, không chạy trùng.

### Tuấn
- [ ] Soạn kịch bản + dữ liệu nghiệm thu cho **4 tình huống bắt buộc** (các bước, đầu vào, kết quả mong đợi, cách kiểm tra); đặc biệt tạo một rewrite **cố ý nhanh hơn nhưng sai kết quả** (ví dụ đổi `LEFT JOIN` thành `INNER JOIN`, bỏ `DISTINCT` cần thiết) cho tình huống #1.
- [ ] Review UI Cổng 2 dưới góc nhìn Reviewer: đủ bằng chứng để quyết định chưa, thiếu gì; ghi issue cho Vinh.
- [ ] Bắt đầu hướng dẫn sử dụng cho Engineer và Reviewer (nháp).
- [ ] Chuẩn bị mẫu bảng nhập kết quả eval 8 nhóm chỉ số cùng Ánh.

### Ánh
- [ ] Dựng **bộ ca kiểm thử dữ liệu** cho `compare/`: cặp bảng giống/khác nhau ở NULL, sai số float, thứ tự dòng, dòng trùng lặp, timestamp lệch múi giờ; ghi rõ cặp nào phải kết luận "tương đương", cặp nào "khác". Giao cho Vinh và Trí dùng làm đầu vào test.
- [ ] Kiểm chứng đầu ra mart sau publish khớp số liệu profile đã lập ở tuần 2 (số dòng, phân bố khóa); phát hiện sai lệch thì báo chủ sở hữu module.
- [ ] Cùng Tuấn chốt mẫu bảng nhập kết quả eval 8 nhóm chỉ số; chuẩn hóa đơn vị đo (giây, số dòng, MB) để tuần 5–6 chỉ việc điền.
- [ ] Chuẩn bị dữ liệu cho `eval/fault_injection.py` theo danh mục lỗi của Tuấn: sinh sẵn các biến thể CSV đã tiêm lỗi, mỗi biến thể ghi rõ lỗi gì và tầng nào phải bắt được.

### Trí
- [ ] `optimizer/judge.py` (FR-12): **phán xét xác định** giữ/loại dựa trên `compare/` của Vinh — không dùng LLM để chấm (nguyên tắc 1); phân loại bị loại theo 4 lý do: **sai dữ liệu / lỗi chạy / không nhanh hơn / quá thời gian**; mọi rewrite bị loại thì giữ bản hợp lệ tốt nhất trước đó; query vốn đã tốt là kết quả hợp lệ.
- [ ] Unit test `judge` với rewrite mẫu **cố ý nhanh hơn nhưng sai kết quả** của Tuấn (tình huống bắt buộc #1): phải bị loại, lý do "sai dữ liệu".
- [ ] `publisher/postgres.py` (FR-14): nạp mart vào **staging** bằng psycopg `COPY` → đối chiếu (số dòng, tổng kiểm) → công bố nguyên tử (swap schema/view). Hỏng giữa chừng thì dashboard vẫn phục vụ phiên bản trước.
- [ ] `worker/publisher_main.py`: chỉ tiến trình này giữ `PublisherSettings`; không bao giờ chạy mã LLM sinh.
- [ ] Integration test **tình huống #3**: cùng một lô chạy hai lần → thay thế, **không nhân đôi dữ liệu**; test lỗi giữa chừng khi nạp.
- [ ] Test fail → không công bố (nguyên tắc 11); tài khoản `metabase_reader` chỉ đọc được (kiểm tra ghi bị từ chối).

### Chốt tuần 4
- Kết quả đạt (tình huống #1, #2, #3 đã pass chưa?):
- Số rewrite đã đề xuất / giữ / loại theo từng lý do:
- Vấn đề / rủi ro:
- Quyết định của cuộc họp:
- Chuyển tuần sau:

---

## Tuần 5 — Metabase, Airflow, Xuất mã, End-to-end (30/10 – 05/11)

**Mục tiêu:** chạy trọn luồng từ CSV tới link dashboard trên UI; pipeline đã duyệt chạy lại theo lịch trên Airflow; xuất ZIP và mở PR cùng một phiên bản đã duyệt; bộ eval chạy được.
**FR liên quan:** FR-15, FR-16, FR-17, FR-18, FR-19. **Tình huống bắt buộc:** #4 (ZIP trên máy sạch) bắt đầu.

### Vinh
- [ ] `graph/nodes.py`: node `publish`, `dashboard`; `services/runs.deliver`: sau Cổng 2 → enqueue publisher → dựng dashboard → trả link.
- [ ] **Chạy E2E OULAD** từ UI trên Compose đầy đủ; ghi mọi lỗi tích hợp vào backlog, sửa phần của mình, giao phần còn lại đúng chủ sở hữu.
- [ ] Frontend `ExportPage`: tải ZIP, mở PR (nhập repo đích), sao chép từng file trong editor; hiển thị link dashboard và trạng thái từng bước; xử lý lỗi/retry.
- [ ] `eval/run_eval.py`: dựng graph bằng `InMemorySaver` chạy pipeline offline cho từng tác vụ của Ánh (không qua FastAPI), thu kết quả dạng có cấu trúc.
- [ ] Sửa trong editor sau bàn giao → tạo **phiên bản mới**, bắt chạy test lại (không dùng lại phê duyệt cũ).

### Tuấn Anh
- [ ] `export/bundle.py`: ZIP **xác định** (cùng phiên bản → cùng nội dung) gồm `models/`, `dbt_project.yml`, `profiles.yml` mẫu, `schema.yml` + macro, loader CSV + manifest nguồn, script chuyển mart sang Postgres, cấu hình dashboard + script dựng lại, Dockerfile/Compose/dependency ghim, file DAG, manifest phiên bản + báo cáo kiểm chứng (FR-18).
- [ ] `export/github_pr.py`: mở PR bằng GitHub API vào repo chỉ định, **không tự merge**; test bằng mock; ZIP và PR chứa cùng phiên bản đã duyệt (FR-19).
- [ ] Gói xuất giữ đúng kiến trúc **DuckDB → Postgres → Metabase**; không transpile sang warehouse khác.
- [ ] Chuẩn bị khung so sánh với **baseline người** (OULAD viết tay): chuẩn hóa engine, phần cứng, phạm vi đo; nếu không chuẩn hóa được thì ghi rõ là "so sánh giữa hai hệ thống".
- [ ] Chỉnh prompt Modeler/Codegen theo lỗi thực tế thấy trong E2E (nhận log từ Vinh/Tuấn).

### Tú
- [ ] Tích hợp Airflow (FR-16/17): đăng ký DAG từ phiên bản đã duyệt (ghi `dag_config.json` + mã lên volume dùng chung), **bản đầu chỉ snapshot thay thế toàn bộ**.
- [ ] Hành vi bắt buộc: lô nhiều file chỉ chạy khi đủ file và đã đánh dấu sẵn sàng; lô mới **đổi schema thì dừng và hỏi Engineer**, không tự áp dụng; hai lượt trùng thời điểm thì khóa theo pipeline (`serial_key`) và xếp hàng.
- [ ] Mỗi lượt chạy lại vẫn chạy **bộ test đã duyệt**; fail → dừng và báo, không công bố.
- [ ] `routes/exports.py`: endpoint tải ZIP và mở PR, kiểm tra quyền và phiên bản đã duyệt.

### Tuấn
- [ ] **Nghiệm thu E2E** trên 3 dataset theo checklist FR đã viết tuần 1; ghi bug có bước tái hiện rõ.
- [ ] Đối chiếu số liệu trên dashboard Metabase với **bảng kết quả chuẩn** viết tay (chỉ số có đúng định nghĩa đã duyệt).
- [ ] Hoàn thiện hướng dẫn sử dụng Engineer/Reviewer; soạn tài liệu "cách dựng lại từ ZIP trên máy sạch" để Trí nghiệm thu bám theo.
- [ ] Chuẩn bị dàn ý báo cáo cuối và danh sách số liệu cần từ eval.

### Ánh
- [ ] `eval/tasks.py`: nạp golden (3 dataset) + đáp án chuẩn của Tuấn thành các tác vụ eval chạy được; bảo đảm **offline, tách khỏi web app**.
- [ ] `eval/fault_injection.py`: cài danh mục lỗi của Tuấn vào dữ liệu đã chuẩn bị ở tuần 4; đo tỉ lệ pass trên dữ liệu sạch và tỉ lệ bắt được lỗi tiêm.
- [ ] Chạy eval vòng đầu trên 3 dataset, lập danh sách tác vụ nào fail và fail ở nhóm chỉ số nào; giao bug về đúng chủ sở hữu module.
- [ ] Số dòng quét và bộ nhớ đỉnh báo cáo là chỉ số tài nguyên, **không quy đổi thành tiền**.

### Trí
- [ ] `metabase/builder.py`: đồng bộ metadata → tạo/cập nhật card **ba loại cố định (KPI số, đường, cột)** → gom vào dashboard → **kiểm tra truy vấn từng card** trước khi trả link (FR-15).
- [ ] **Idempotent theo `logical_key`**: lưu ID card và dashboard, retry không tạo bản trùng, chạy lại riêng bước này không cần nạp lại dữ liệu; integration test với Metabase thật trong Compose.
- [ ] Script dựng lại Metabase cho gói xuất (không gọi API nền tảng), phối hợp Tuấn Anh.
- [ ] `eval/metrics.py`: tính 8 nhóm chỉ số (hợp lệ kỹ thuật, đúng dữ liệu, chất lượng thiết kế theo rubric của Tuấn, chất lượng test, hiệu năng, rewrite bị loại theo 4 lý do, khả dụng, ablation) + **baseline nội bộ** (output trước khi Optimizer can thiệp); tái dùng `compare/` của Vinh và `judge` của mình, không viết lại logic đối chiếu.
- [ ] Bắt đầu nghiệm thu ZIP trên máy sạch (VM hoặc container trống) theo tài liệu của Tuấn; ghi lỗi gói xuất cho Tuấn Anh sửa.

### Chốt tuần 5
- Kết quả đạt (E2E OULAD tới link dashboard? ZIP? PR? chạy lại theo lịch?):
- Danh sách bug còn mở theo mức độ:
- Vấn đề / rủi ro:
- Quyết định của cuộc họp (cắt gì khỏi tuần 6 nếu cần):
- Chuyển tuần sau:

---

## Tuần 6 — Eval, nghiệm thu, triển khai, bàn giao (06/11 – 12/11)

**Mục tiêu:** có số liệu eval đầy đủ; **4 tình huống nghiệm thu bắt buộc đều pass**; bản triển khai demo chạy ổn; báo cáo và tài liệu hoàn tất. Tuần này không thêm tính năng mới, chỉ sửa lỗi, đo và đóng gói.
**FR liên quan:** toàn bộ FR-01 → FR-21 (nghiệm thu).

### Vinh
- [ ] **Triển khai demo**: SPA tĩnh lên Vercel (không dùng serverless function); FastAPI + worker trong container có volume bền vững; cấu hình CORS và biến môi trường.
- [ ] Viết tài liệu triển khai nêu rõ **worker, scheduler, volume, kết nối mạng, cách phục hồi job** (đặc tả yêu cầu); kiểm tra bằng cách restart từng thành phần.
- [ ] Bug bash toàn hệ thống cùng cả nhóm (1 buổi); phân loại bug, sửa phần frontend và tích hợp.
- [ ] Đóng băng code (code freeze) cuối ngày 10/11; chuẩn bị và tập demo (kịch bản do Tuấn viết).

### Tuấn Anh
- [ ] **Ablation**: chạy eval có/không retrieval, có/không optimizer, có/không sinh test; ghi kết quả vào bảng.
- [ ] Tổng hợp **chi phí token và thời gian tìm rewrite** (chỉ ghi nhận, không quy đổi tiền).
- [ ] Sửa prompt/rule theo lỗi từ kết quả eval trong giới hạn thời gian (không đụng tập đo để tránh rò rỉ).
- [ ] Sửa lỗi gói xuất ZIP/PR phát hiện khi nghiệm thu.

### Tú
- [ ] Chạy lại và đóng **tình huống #1, #2, #3** thành test tự động nằm trong CI (`tests/integration/acceptance_*`).
- [ ] Test các tình huống còn lại nếu còn thời gian: lỗi giữa chừng khi nạp Postgres, retry Metabase, lô đổi schema, hai lượt trùng giờ.
- [ ] Rà bảo mật: sandbox thoát file/ mạng (thử SQL/macro độc hại), worker không có thông tin warehouse, `pip-audit`, `npm audit`, `gitleaks`.
- [ ] Sửa backlog lỗi backend, chốt migration cuối và chạy `alembic check`.

### Tuấn
- [ ] Viết **báo cáo cuối**: bài toán, kiến trúc, kết quả eval 8 nhóm chỉ số, bốn tình huống nghiệm thu, **hạn chế** (chỉ snapshot, chỉ rewrite DuckDB, kết luận giới hạn ở bộ dữ liệu thử, không tuyên bố dashboard Postgres nhanh hơn).
- [ ] So sánh với baseline người (OULAD viết tay) và ghi đúng điều kiện so sánh.
- [ ] Hoàn thiện tài liệu người dùng và kịch bản demo; chuẩn bị slide.
- [ ] Nghiệm thu lần cuối bản triển khai theo checklist FR-01 → FR-21, đánh dấu từng FR đạt/chưa đạt.

### Ánh
- [ ] Chạy **eval đầy đủ** trên 3 dataset (offline): bảng 8 nhóm chỉ số, kèm baseline nội bộ; lưu kết quả dạng có cấu trúc để báo cáo trích.
- [ ] Kiểm chứng tỉ lệ bắt lỗi khi tiêm lỗi trên cả 3 dataset; đối chiếu bảng phân loại rewrite bị loại của Trí với dữ liệu thật.
- [ ] Chạy lại eval sau mỗi lần sửa lớn để bảo đảm không hồi quy; chốt số liệu cuối trước code freeze.
- [ ] Phối hợp Tuấn để số liệu trong báo cáo khớp kết quả chạy (ghi commit và phiên bản dữ liệu kèm theo).

### Trí
- [ ] **Nghiệm thu tình huống #4**: máy sạch tải ZIP, điền cấu hình, cung cấp CSV → dựng lại mart và dashboard **không gọi API của nền tảng**; lặp lại đến khi ổn định.
- [ ] Thử mở PR thật vào repo thử, xác nhận hệ thống không tự merge.
- [ ] Xuất **bảng phân loại toàn bộ rewrite bị loại** theo 4 lý do từ nhật ký `judge`; đối chiếu với Ánh để số trong báo cáo khớp lần chạy thật.
- [ ] CI toàn bộ xanh (6 job), build lại image Airflow và backend, `dbt --version` và import DAG trong image.
- [ ] Rà lại **mọi phiên bản đã ghim** (không còn `latest`), digest image trong Dockerfile, Dependabot nhóm dbt-core + dbt-duckdb + duckdb.

### Chốt tuần 6 (nghiệm thu cuối)
- 4 tình huống bắt buộc: #1 [ ]  #2 [ ]  #3 [ ]  #4 [ ]
- FR đạt / tổng (21):
- Số liệu eval chính:
- Việc tồn đọng và chủ sở hữu sau bàn giao:

---

## 4. Ma trận FR theo tuần

| FR | Nội dung ngắn | Làm chính | Tuần xong |
|---|---|---|---|
| FR-01 | Nạp CSV, preview, lưu file gốc | Ánh, Vinh | 2 |
| FR-02 | Hồ sơ thống kê | Ánh | 2 |
| FR-03 | Khóa/quan hệ ứng viên, cảnh báo fan-out | Ánh | 2 |
| FR-04 | Thiết kế đủ 6 nội dung | Tuấn Anh, Tuấn | 2 |
| FR-05 | Hỏi lại khi mơ hồ | Tuấn Anh, Tuấn | 2 |
| FR-06 | Cổng 1 | Vinh, Tú | 2 |
| FR-07 | dbt 3 tầng, `dbt compile` | Ánh (bronze), Tuấn Anh (silver/mart), Trí (lắp ráp) | 3 |
| FR-08 | Test từ ràng buộc đã duyệt | Trí | 3 |
| FR-09 | DAG từ template | Trí | 3 |
| FR-10 | Worker cách ly | Tú, Trí | 3 |
| FR-11 | Đo từng model | Tú | 3 |
| FR-12 | Rewrite có kiểm chứng | Tú (đề xuất), Tuấn Anh (rules), Vinh (`compare/`), Trí (judge) | 4 |
| FR-13 | Cổng 2, phê duyệt gắn phiên bản | Tú, Vinh | 4 |
| FR-14 | Công bố Postgres | Trí | 4 |
| FR-15 | Card/dashboard Metabase idempotent | Trí | 5 |
| FR-16 | Chạy lại theo lịch, không nhân đôi | Tú | 5 |
| FR-17 | Dừng khi đổi schema | Tú | 5 |
| FR-18 | Xuất ZIP | Tuấn Anh, Trí | 5 (nghiệm thu tuần 6) |
| FR-19 | Mở PR | Tuấn Anh | 5 |
| FR-20 | Xác thực, phân quyền theo dự án | Tú | 4 |
| FR-21 | Khôi phục lượt đang chờ | Tú, Vinh | 4 |

## 5. Rủi ro đã thấy trước

| Rủi ro | Ảnh hưởng | Phòng ngừa |
|---|---|---|
| Tổ hợp Airflow + dbt-core + dbt-duckdb + DuckDB không tương thích | Chặn Airflow và gói xuất | Trí khóa trong tuần 1; không ai nâng lẻ một thành phần |
| Gemini sinh SQL silver/mart sai hoặc không compile | Trễ tuần 3 và E2E | Vòng sửa lỗi có ngân sách; retrieval few-shot; Tuấn review sớm trên OULAD |
| Modeler đoán thay vì hỏi lại | Vi phạm nguyên tắc 10, thiết kế sai grain | Tuấn dựng sẵn câu hỏi chuẩn; chấm bằng rubric từ tuần 2 |
| Đo hiệu năng nhiễu nên "nhanh hơn" không đáng tin | Optimizer giữ nhầm rewrite | Median + so với biên độ nhiễu (Vinh); cùng engine và tài nguyên |
| Tích hợp E2E dồn vào tuần 5 | Trượt toàn kế hoạch | Mỗi tuần có mốc demo được; chạy E2E một phần từ tuần 3 |
| Rò rỉ đáp án từ retrieval sang tập đo | Số liệu eval sai | Tách kho mẫu khỏi golden (Tuấn Anh + test) |
| Vòng optimizer chia cho 4 người (Tú đề xuất, Tuấn Anh rules, Vinh compare, Trí judge) | Lệch hợp đồng dữ liệu, chặn nhau ở tuần 4 | Chốt kiểu ứng viên rewrite và hợp đồng `compare/` ↔ `judge` ngay tuần 1; Ánh cấp sẵn bộ ca kiểm thử ở tuần 4 |
| Nhiều người sửa chung `graph/` và `app/db/models.py` | Xung đột, migration lệch | Chủ sở hữu rõ ràng; Alembic `alembic check` trong CI |
| Máy sạch dựng lại ZIP thất bại | Rớt tiêu chí nghiệm thu #4 | Trí bắt đầu thử từ tuần 5, không để dồn tuần 6 |
