# CLAUDE.md

Hướng dẫn cho Claude Code khi làm việc trong repo **DataForge** — agent sinh pipeline ETL và dashboard từ CSV.

Nguồn sự thật về yêu cầu: [docs/đặc tả.md](docs/đặc tả.md) (bản PDF: `docs/đặc tả.pdf`, sơ đồ: `docs/diagram.png`). Khi đặc tả và file này mâu thuẫn, **đặc tả thắng** — hãy cập nhật file này.

> **Trạng thái repo (2026-09-29):** đã có **khung code (skeleton)**. Mọi hàm nghiệp vụ là stub: docstring `TODO: ...` mô tả việc cần làm + `raise NotImplementedError`. Phần khai báo (settings, ORM model, Pydantic schema, DTO), phần nối dây (`create_app`, router, `build_graph`, Alembic env, Compose) và công cụ nội bộ là code thật. Đã có migration Alembic baseline. Xem mục 9 cho cấu trúc, mục 10 cho quy ước và CI, [ARCHITECT.md](ARCHITECT.md) cho ranh giới.

---

## 1. Dự án làm gì

Web app nhận **các file CSV thô + một yêu cầu phân tích bằng ngôn ngữ tự nhiên**, trả ra ba thứ:

1. Một **warehouse đã dựng** (mart trên Postgres).
2. Một **bộ dashboard Metabase**.
3. Toàn bộ **source code pipeline dưới dạng dbt project chạy được độc lập** (ZIP / Pull Request).

Hệ thống tự động hóa phần *có khuôn mẫu* khi tiếp nhận nguồn dữ liệu mới: khảo sát dữ liệu, viết dbt model, sinh test, dựng DAG, tối ưu query, dựng báo cáo. Phần *cần phán đoán nghiệp vụ* (grain, định nghĩa chỉ số, star schema) luôn đi qua cổng duyệt của con người.

Ba điểm phân biệt — mọi thiết kế phải giữ được:

- **Mã được kiểm chứng bằng cách chạy thật và đối chiếu kết quả**, không chỉ được sinh ra.
- **Optimizer chỉ giữ rewrite vừa nhanh hơn vừa cho kết quả tương đương**, kiểm chứng trên bộ dữ liệu thử.
- **Hai cổng duyệt bắt buộc**; hệ thống không tác động vào môi trường production của người dùng.

Dự án tham chiếu của nhóm: OULAD Student Data Warehouse (7 CSV, 32.000 sinh viên, 10,6 triệu bản ghi; bronze → silver → star schema → dbt marts → Metabase). Đây vừa là golden dataset cho eval vừa là baseline con người.

---

## 2. Nguyên tắc bất biến (KHÔNG được vi phạm)

Đây là các ràng buộc kiến trúc và an toàn. Khi viết code, nếu một thay đổi đụng tới một trong các điều này, dừng lại và hỏi.

1. **LLM đề xuất, công cụ xác định phán xét.** Không thành phần LLM nào tự chấm kết quả của chính nó. Quyết định giữ/loại luôn do code xác định (chạy, đo, so sánh).
2. **Không gửi dữ liệu thô vào LLM.** Chỉ gửi *hồ sơ thống kê* (profile). Lưu ý tên cột và giá trị hiếm vẫn có thể nhạy cảm — không coi đây là bảo đảm tuyệt đối, và không mở rộng lượng mẫu gửi đi khi chưa cân nhắc.
3. **Mã sinh ra không bao giờ chạy trong tiến trình backend.** DuckDB không tạo ranh giới bảo vệ: SQL do LLM sinh có thể đọc/ghi file và ăn tài nguyên; dbt macro và Python cũng vậy. FastAPI chỉ tiếp nhận yêu cầu và quản lý trạng thái.
4. **Worker cách ly:** mỗi lượt một workspace + một file DuckDB riêng; giới hạn RAM, CPU, thời gian, dung lượng; **không giữ thông tin kết nối hay quyền ghi Postgres phục vụ**.
5. **Chỉ publisher có quyền ghi warehouse.** Metabase đọc bằng tài khoản chỉ đọc.
6. **DAG Airflow sinh từ template cố định** — chỉ thay cấu hình và danh sách tác vụ. Không nạp mã Python tùy ý vào Airflow đang vận hành.
7. **Không sinh mã khi thiết kế chưa qua Cổng 1** (FR-06).
8. **Phê duyệt gắn với một phiên bản cụ thể** (thiết kế + mã + test + lô dữ liệu + lượt chạy + báo cáo). Sửa mã sau khi duyệt → phê duyệt cũ mất hiệu lực, phải chạy lại kiểm tra và duyệt lại (FR-13).
9. **Quan sát thống kê ≠ ràng buộc.** Test bắt buộc chỉ sinh từ ràng buộc đã được duyệt ở Cổng 1 (FR-08). Quan sát chỉ dùng để đề xuất kèm bằng chứng; giả định chưa xác nhận thì hỏi lại hoặc cảnh báo.
10. **Khi thiếu thông tin, Modeler hỏi lại thay vì đoán** (ví dụ cột `amount`: đơn giá, thành tiền hay số đã thanh toán?).
11. **Không tự merge PR, không tự áp dụng thay đổi schema chưa duyệt, không công bố dữ liệu khi test fail.**
12. **Không dùng tag `latest`** cho bất kỳ image/dependency nào. Mọi phiên bản phải được ghim.

---

## 3. Kiến trúc tổng thể

### 3.1 Luồng xử lý (LangGraph)

```
CSV + yêu cầu NL
  → Profiler            (xác định)   hồ sơ dữ liệu
  → Modeler             (LLM)        bản thiết kế dữ liệu
       ↺ thiếu thông tin → hỏi người dùng → quay về Modeler
  → [Cổng 1] duyệt thiết kế          ↺ trả lại → Modeler
  → Codegen             (LLM)        dbt models + tests + cấu hình DAG
  → Worker cách ly      (xác định)   chạy & đo
       ⇄ Optimizer (LLM + quy tắc) đề xuất rewrite → chạy lại → đối chiếu
  → [Cổng 2] duyệt mã + bằng chứng   ↺ trả lại → Codegen
  → Publisher           (xác định)   nạp staging Postgres → đối chiếu → công bố
  → Dashboard           (xác định)   Metabase cards + dashboard → trả link
```

Cổng duyệt là **điểm dừng HITL** của LangGraph (interrupt), trạng thái lưu bằng **checkpointer trên Postgres** để backend restart vẫn tiếp tục đúng chỗ (FR-21).

### 3.2 Phân vai thành phần

| Thành phần | Loại | Nhiệm vụ |
|---|---|---|
| Profiler | Xác định | Thống kê cột, dò khóa ứng viên (kể cả khóa ghép) và quan hệ, kèm bằng chứng |
| Modeler | LLM | Diễn giải yêu cầu, đề xuất thiết kế, hỏi lại khi mơ hồ |
| Codegen | LLM | Sinh/sửa dbt model, test, cấu hình DAG (có retrieval few-shot từ Qdrant) |
| Optimizer | LLM + quy tắc | Đề xuất rewrite SQL |
| Executor & comparator | Xác định | Chạy, đo, so sánh, quyết định giữ hay loại |
| Publisher | Xác định | Nạp Postgres staging, đối chiếu, công bố phiên bản |
| Dashboard builder | Xác định | Đồng bộ metadata, tạo card/dashboard Metabase qua REST API |

Output của mọi agent LLM phải được validate bằng **Pydantic v2** trước khi dùng.

### 3.3 Ba môi trường tách biệt

1. **Sandbox xây dựng** — chạy mã đang sinh hoặc đang sửa.
2. **Môi trường chạy pipeline đã duyệt** — thực thi đúng phiên bản đã duyệt, vẫn dùng DuckDB (Airflow).
3. **Postgres phục vụ** — chỉ nhận mart đã đạt kiểm tra.

### 3.4 Quyết định kiến trúc đã chốt

- **Postgres là warehouse phục vụ** vì Metabase không có driver DuckDB chính thức. **DuckDB là nơi biến đổi và đo đạc.**
- **Một instance Postgres, nhiều database tách vai trò:** warehouse phân tích, metadata ứng dụng, metadata Airflow, app DB của Metabase. Tách database, không dựng thêm container.
- **LangGraph điều phối việc *viết* pipeline; Airflow điều phối việc *chạy* pipeline.** Không thay thế nhau.
- **Hàng đợi job = bảng job trong Postgres** (khóa hàng — `SELECT ... FOR UPDATE SKIP LOCKED`, retry, phục hồi). **Không thêm Redis/Celery** ở bản đầu.
- **Polling thay cho WebSocket** — trạng thái đã bền vững nên restart vẫn khôi phục.
- **Volume bền vững dùng chung giữa worker và Airflow** cho CSV gốc, manifest lô, mã và báo cáo từng phiên bản. Không lưu lâu dài trên filesystem tạm của container (ví dụ Cloud Run filesystem nằm trong RAM).

---

## 4. Luồng người dùng và yêu cầu chi tiết

Vai trò: **Engineer** (nạp dữ liệu, mô tả yêu cầu, duyệt thiết kế, sửa mã) và **Reviewer** (duyệt mã + bằng chứng trước công bố). Chế độ nhóm: Reviewer ≠ Engineer. Chế độ cá nhân: một người làm cả hai, **nhật ký phải ghi rõ không có review độc lập**.

### Bước 1 — Nạp dữ liệu (FR-01)
Đoán encoding, dấu phân cách, ký hiệu null, định dạng ngày; hiển thị preview vài dòng để xác nhận. **Lưu nguyên vẹn file gốc và cấu hình đọc.**

### Bước 2 — Lập hồ sơ (FR-02, FR-03)
Profiler quét bằng DuckDB: kiểu suy ra, tỉ lệ null, số giá trị phân biệt, min/max, mẫu giá trị. Dò khóa chính ứng viên (kể cả khóa ghép) và quan hệ ứng viên, mỗi ứng viên kèm bằng chứng: tỉ lệ khớp khóa, số bản ghi không tìm thấy cha, **cảnh báo join làm tăng số dòng** (fan-out).

### Bước 3 — Đề xuất thiết kế (FR-04, FR-05)
Bản thiết kế dữ liệu phải có **đủ sáu nội dung**, mỗi lựa chọn kèm lý giải:

| Nội dung | Ví dụ |
|---|---|
| Grain | Một dòng fact = một dòng sản phẩm trong đơn |
| Khóa và quan hệ | Khóa ghép, khóa nghiệp vụ, quan hệ một–nhiều |
| Định nghĩa chỉ số | Doanh thu tính trước hay sau hoàn tiền |
| Quy tắc làm sạch | Dòng thiếu khóa bị cách ly hay làm dừng pipeline |
| Quy tắc cập nhật | Lô mới thay thế toàn bộ hay bổ sung (bản đầu: chỉ snapshot thay thế) |
| Yêu cầu dashboard | Chỉ số, chiều phân tích, bộ lọc, loại card |

Nghiệp vụ hoặc grain mơ hồ → hỏi trước khi chốt.

### Bước 4 — Cổng 1 (FR-06)
Engineer duyệt, sửa trực tiếp, hoặc trả lại Modeler. Không sinh mã khi chưa có xác nhận.

### Bước 5 — Sinh mã và chạy thử (FR-07 → FR-11)
dbt model **ba tầng**:

- **Bronze:** giữ biểu diễn nguồn, **không ép kiểu nghiệp vụ** (mã `00123` không được thành số). Mỗi dòng mang `batch_id`, tên file, định danh dòng, thời điểm nạp. Chấp nhận bản ghi lỗi.
- **Silver:** chuẩn hóa kiểu, xử lý null, khử trùng lặp; dòng lỗi **bị cách ly kèm lý do** và báo cáo số lượng.
- **Mart:** fact + dimension theo thiết kế đã duyệt; phải đạt mọi ràng buộc đã chốt.

Test áp đúng tầng như trên. Chất lượng bộ test đo bằng: tỉ lệ pass trên dữ liệu sạch + tỉ lệ bắt được lỗi khi tiêm lỗi có chủ đích.

Chạy trong worker cách ly; ghi **thời gian chạy, số dòng quét, bộ nhớ đỉnh, kết quả test** cho từng model. `dbt compile` phải thành công; DAG phải import được.

### Bước 6 — Tối ưu (FR-12)
Xem mục 5.

### Bước 7 — Cổng 2 (FR-13)
Reviewer xem diff mã, kết quả test, bảng so sánh hiệu năng, cấu hình dashboard. Không thể công bố phiên bản khác bằng phê duyệt của phiên bản cũ.

### Bước 8 — Công bố Postgres (FR-14)
Nạp mart vào **staging** (psycopg `COPY`) → đối chiếu dữ liệu → công bố phiên bản (chuyển nguyên tử, ví dụ swap schema/view). Hỏng giữa chừng → **dashboard vẫn phục vụ phiên bản đã công bố trước đó**.

### Bước 9 — Dashboard Metabase (FR-15)
Đồng bộ metadata → tạo/cập nhật card → gom vào dashboard → **kiểm tra truy vấn từng card** trước khi trả link. Ba loại card cố định: **KPI số, biểu đồ đường, biểu đồ cột**. **Lưu ID card và dashboard** để retry không tạo bản trùng và chạy lại riêng bước này không cần nạp lại dữ liệu (idempotent).

### Chạy lại theo lịch (FR-16, FR-17)
Pipeline đã duyệt được đăng ký thành DAG Airflow. Bản đầu **chỉ snapshot thay thế toàn bộ**.

| Tình huống | Hành vi bắt buộc |
|---|---|
| Một lô cần nhiều file | Chỉ chạy khi bộ file đủ và được đánh dấu sẵn sàng |
| Cùng lô chạy hai lần | Thay thế, **không nhân đôi dữ liệu** |
| Lô mới đổi schema | Dừng và hỏi Engineer, không tự áp dụng |
| Hai lượt trùng thời điểm | Khóa theo pipeline, đưa vào hàng đợi |
| Bước công bố thất bại | Retry được, không tạo dữ liệu hay dashboard trùng |

Mỗi lượt chạy lại vẫn chạy bộ test đã duyệt; fail → dừng và báo, không công bố.

### Bàn giao mã nguồn (FR-18, FR-19)
Ba đường ra: **tải ZIP**, **mở Pull Request** vào repo người dùng chỉ định (GitHub API), **sao chép từng file** trong editor. ZIP và PR luôn chứa **cùng phiên bản đã duyệt**; không tự merge.

Nội dung gói xuất:

| Thành phần | Vai trò |
|---|---|
| `models/`, `dbt_project.yml`, `profiles.yml` mẫu | Pipeline dbt |
| `schema.yml`, SQL test tùy chỉnh, macro | Bộ kiểm thử đầy đủ |
| Loader CSV + manifest nguồn | Tái tạo bước nạp |
| Script chuyển mart sang Postgres | Hoàn tất pipeline |
| Cấu hình dashboard + script dựng lại | Tái tạo Metabase |
| Dockerfile, Compose, dependency ghim phiên bản | Dựng môi trường |
| File DAG | Chạy định kỳ trên Airflow của người dùng |
| Manifest phiên bản + báo cáo kiểm chứng | Xác định đúng bộ mã đã kiểm chứng |

Gói xuất giữ đúng kiến trúc **DuckDB → Postgres → Metabase**; không transpile sang warehouse khác. **Nghiệm thu:** máy sạch tải ZIP, điền cấu hình, cung cấp CSV → dựng lại được mart và dashboard **mà không gọi API của nền tảng**. Sửa trong editor sau bàn giao tạo phiên bản mới phải test lại; sửa ở máy người dùng là nhánh độc lập, không đồng bộ ngược.

### Xác thực (FR-20, FR-21)
Phân quyền theo dự án, tối thiểu hai vai trò; chỉ Reviewer có quyền duyệt; lịch sử duyệt gắn với dự án. Backend restart vẫn khôi phục đúng lượt đang chờ duyệt.

---

## 5. Vòng tối ưu (Optimizer)

- **Phạm vi bản đầu:** chỉ rewrite SQL trên DuckDB. (Index Postgres, phân vùng file là hướng mở rộng.)
- **sqlglot** parse và biến đổi SQL *đã compile*; kế hoạch thực thi và số đo lấy từ **DuckDB profiling**.
- Optimizer xếp hạng query theo thời gian chạy rồi đề xuất rewrite.

Hai phép kiểm chứng **tách biệt**, không gộp:
1. **Đầu ra vs đáp án chuẩn** → pipeline có đúng không.
2. **Sau rewrite vs trước rewrite** → rewrite có giữ nguyên kết quả không. (Giữ nguyên một kết quả sai không làm pipeline đúng.)

**Tiêu chí TƯƠNG ĐƯƠNG:**
- Schema đầu ra khớp.
- So sánh theo **multiset có đếm số lần xuất hiện từng dòng** — không chỉ row count.
- Quy tắc rõ cho NULL, số thực (dung sai) và timestamp.
- Giá trị phụ thuộc thời gian chạy (`now()`, `current_date`, random…) được cố định qua tham số.
- Kết luận chỉ giới hạn ở bộ dữ liệu kiểm thử.

**Tiêu chí NHANH HƠN:**
- Cùng dữ liệu, cùng phiên bản engine, cùng cấu hình tài nguyên.
- Chạy lặp, lấy **median**; cải thiện phải **lớn hơn biên độ nhiễu đo**.
- Đo cả từng model và toàn pipeline.

**Ngân sách vòng lặp:** số ứng viên tối đa, số lần sửa lỗi tối đa, thời gian tối đa, điều kiện dừng. Mọi rewrite bị loại → giữ bản hợp lệ tốt nhất trước đó. Query đã tốt, không cần rewrite, là kết quả hợp lệ. Mỗi rewrite bị loại được ghi nhật ký kèm lý do, phân loại: **sai dữ liệu / lỗi chạy / không nhanh hơn / quá thời gian**.

Lưu ý: đây là tối ưu **thời gian dựng dữ liệu trên DuckDB**, không đồng nghĩa dashboard trên Postgres nhanh hơn — đừng tuyên bố như vậy trong UI hay báo cáo.

---

## 6. Retrieval few-shot (Qdrant)

Kho mẫu = cặp (mô tả yêu cầu, dbt model tương ứng), thu từ các dự án dbt mã nguồn mở và phần tập chuẩn dành riêng. Embedding bằng `gemini-embedding-001`. Trước khi sinh mã, truy xuất vài mẫu gần nhất đưa vào ngữ cảnh Codegen.

**Chống rò rỉ đáp án:** tập mẫu retrieval phải tách khỏi tập đo — tách cả biến thể cùng tác vụ và cùng dataset.

---

## 7. Đánh giá (eval) offline

Bộ eval **chạy offline, tách khỏi web app**, dùng pytest + bộ đối chiếu SQL tự xây. Golden set: OULAD + hai bộ công khai khác; mỗi tác vụ có bản thiết kế chuẩn và bảng kết quả chuẩn viết tay.

Baseline:
- **Nội bộ:** output trước khi Optimizer can thiệp (đo tác dụng riêng của tối ưu).
- **Con người:** pipeline OULAD viết tay — chỉ có nghĩa khi chuẩn hóa engine, phần cứng, phạm vi đo; nếu không, ghi rõ là "so sánh giữa hai hệ thống".

| Nhóm chỉ số | Nội dung |
|---|---|
| Hợp lệ kỹ thuật | dbt compile, DAG import và chạy được |
| Đúng dữ liệu | Tỉ lệ bảng kết quả khớp đáp án chuẩn |
| Chất lượng thiết kế | Chấm grain, khóa, quan hệ; chấp nhận nhiều thiết kế hợp lệ |
| Chất lượng test | Pass trên dữ liệu sạch; bắt lỗi khi tiêm lỗi |
| Hiệu năng | Cải thiện median thời gian chạy và số dòng quét so với baseline nội bộ |
| Rewrite bị loại | Phân loại theo 4 lý do ở mục 5 |
| Khả dụng | Số dòng Reviewer phải sửa, số vòng sửa, tỉ lệ tác vụ hoàn tất |
| Ablation | Có/không retrieval, optimizer, sinh test |

Số dòng quét và bộ nhớ đỉnh là chỉ số tài nguyên, **không quy đổi thành tiền**. Ghi lại chi phí token và thời gian tìm rewrite.

---

## 8. Tech stack

| Layer | Công nghệ |
|---|---|
| Backend | FastAPI · Python 3.11 · Pydantic v2 (async REST) |
| Orchestration | LangGraph (StateGraph, checkpointer Postgres) |
| LLM & embeddings | Google Gemini `gemini-3.5-flash-lite` · `gemini-embedding-001` |
| Transform | dbt-core · dbt-duckdb · DuckDB |
| SQL analysis | sqlglot · DuckDB profiling |
| Scheduler | Apache Airflow (LocalExecutor) |
| Relational DB | PostgreSQL · SQLAlchemy · Alembic |
| Vector DB | Qdrant |
| File storage | Volume bền vững dùng chung worker ↔ Airflow |
| Publish/export | psycopg (`COPY`) · GitHub API · ZIP |
| BI | Metabase + REST API |
| Frontend | React 19 · Vite · TypeScript · CSS thuần · Monaco editor (review diff) |
| Eval | pytest · SQL comparator tự xây · golden dataset |
| Deploy | Docker Compose (backend + services) · Vercel (SPA tĩnh) |

LLM provider của dự án là **Gemini**, không phải Anthropic/OpenAI — đừng thêm SDK LLM khác khi chưa được yêu cầu.

**Phiên bản:** tổ hợp tương thích Airflow + dbt-core + dbt-duckdb + DuckDB được chốt bằng cách dựng thử trong tuần đầu rồi khóa lại. Khi thêm dependency, ghim phiên bản chính xác; không nâng cấp một trong bốn thành phần này đơn lẻ.

**Triển khai demo:** SPA trên Vercel (chỉ file tĩnh, không serverless function); FastAPI + worker trong container có volume bền vững; Airflow `api-server` + `scheduler` + `dag-processor` (mô hình Airflow 3) container riêng dùng chung volume, dbt chạy từ virtualenv riêng trong image; Postgres có lưu trữ bền vững; Metabase container riêng. Nền tảng nào được chọn cũng phải nêu rõ worker, scheduler, volume, kết nối mạng và cách phục hồi job.

---

## 9. Cấu trúc thư mục

```
backend/
  pyproject.toml, uv.lock   dependency + cấu hình Ruff, mypy, pytest; quản lý bằng uv
  .python-version           3.11.14, khớp base image
  Dockerfile                multi-stage, uv cache mount, base image ghim tag + digest, user non-root
  alembic.ini, migrations/  Alembic async; versions/ có migration baseline
  app/
    main.py                 create_app (uvicorn --factory), lifespan (TODO)
    core/                   config (ApiSettings / WorkerSettings / PublisherSettings), security, logging
    db/                     models.py (schema + naming convention), session.py, checkpointer.py (setup LangGraph)
    api/                    schemas.py (DTO), deps.py (auth, require_role), routes/*
    graph/                  state.py, nodes.py (stub), builder.py (PipelineGraph, luồng + HITL)
    services/               runs (start/resume/deliver/recover), approvals (fingerprint), batches
    agents/                 LLM: llm.py (Gemini), modeler, codegen, optimizer, schemas.py, prompts/*.md
    codegen/                xác định: bronze, tests (từ constraint đã duyệt), guard (allowlist), project
    ingest/                 sniff.py (FR-01), storage.py (bố cục volume)
    profiler/               profile.py, schemas.py (DataProfile — thứ duy nhất gửi cho LLM)
    compare/                multiset.py (TƯƠNG ĐƯƠNG), benchmark.py (NHANH HƠN)
    optimizer/              judge.py (phán xét xác định), rules.py (sqlglot)
    publisher/              postgres.py (staging → reconcile → swap view)
    metabase/               client.py, builder.py (upsert idempotent theo logical_key)
    export/                 bundle.py (ZIP xác định), github_pr.py
    retrieval/              store.py (Qdrant, chống rò rỉ tập eval)
    jobs/                   queue.py (Postgres SKIP LOCKED, lease, serial_key)
    versioning.py           VersionParts, fingerprint, StaleApprovalError
  worker/
    main.py                 sandbox worker (queue "sandbox", không có quyền warehouse)
    publisher_main.py       publisher (queue "publisher", giữ DSN warehouse + Metabase)
    runner.py               job kinds: profile, dbt_build, rewrite_benchmark
    sandbox.py              env allowlist, rlimit, timeout, DUCKDB_LOCKDOWN_SETTINGS
  templates/dbt_project/    dbt_project.yml.j2, profiles.yml.j2, macros/ (generic test dataforge_*)
  tests/
    conftest.py             fixture app, client (ASGITransport + LifespanManager), checkpointer, database_url
    unit/                   không I/O: smoke, compare, guards, acceptance_rules
    integration/            marker `integration`, cần Postgres: queue, acceptance_pipeline
airflow/
  Dockerfile                Airflow 3.3.2 + dbt trong virtualenv riêng /opt/dbt-venv
  dbt/requirements.in|txt   dbt stack ghim, lock có hash (uv pip compile, Linux)
  dags/dataforge_pipelines.py   DAG template cố định, chỉ đọc dag_config.json
  tests/                    DagBag integrity (TODO)
  ruff.toml                 kế thừa backend + rule AIR
frontend/                   React 19 + Vite 8 + TS 7 + Monaco + Biome; api/client.ts và pages/* là stub
eval/                       tasks, metrics, fault_injection, run_eval (stub); golden/ chứa bộ chuẩn
scripts/check_conventions.py   cưỡng chế "không comment" + "code chỉ ASCII"
infra/postgres/init.sh      tạo 4 database + role (publisher ghi, metabase_reader chỉ đọc)
docker-compose.yml          postgres, qdrant, metabase, migrate, backend, sandbox-worker, publisher, airflow-*
.github/workflows/ci.yml    conventions, backend-lint, backend-test, frontend, images, security
.github/dependabot.yml      cập nhật hằng tuần; dbt-core + dbt-duckdb + duckdb gom một nhóm
.pre-commit-config.yaml     ruff, uv-lock, check_conventions
ARCHITECT.md                ranh giới tiến trình, phụ thuộc package, chủ sở hữu schema từng DB
SECURITY.md                 kênh báo lỗ hổng
```

Ranh giới module và chủ sở hữu schema từng database: xem [ARCHITECT.md](ARCHITECT.md). Tóm tắt:
- Phần **xác định** (`profiler`, `compare`, `optimizer/judge`, `codegen`, `publisher`, `metabase`, `worker`) không import `app.agents`, ngoại trừ các Pydantic schema trong `app.agents.schemas`.
- `app.agents` chỉ nhận `DataProfile`, không bao giờ nhận đường dẫn file hay dòng dữ liệu.
- Chỉ `worker/publisher_main.py` dùng `PublisherSettings`; sandbox worker dùng `WorkerSettings` (không có trường warehouse) và chỉ nằm trên mạng `sandbox` (`internal: true`).
- LLM chỉ sinh `models/silver/*.sql`, `models/mart/*.sql`. Bronze, schema test, `dag_config.json` sinh xác định.
- `eval/` chạy bằng môi trường của backend (không phải uv workspace, vì backend không phải package cài được). Airflow không thuộc môi trường uv nào của backend.

---

## 10. Quy ước khi viết code

**Ngôn ngữ và comment (bắt buộc):**
- Toàn bộ code viết bằng **tiếng Anh**: tên, docstring, chuỗi lỗi, prompt LLM, text UI, file template, metadata package. Tài liệu (`docs/`, `*.md`) có thể dùng tiếng Việt.
- **Không dùng comment**: `#` trong Python, YAML, TOML, Dockerfile, shell, requirements; `//` / `/* */` trong TS, CSS; `--` trong SQL; `{# #}` trong Jinja. Code phải tự giải thích qua tên và cấu trúc; điều bắt buộc phải nói thì đặt trong docstring của hàm hoặc class. Ngoại lệ duy nhất: shebang `#!/bin/bash`.
- **Ngoại lệ lint chỉ khai báo trong file cấu hình** (`[tool.ruff.lint.per-file-ignores]`, `biome.json`), không bao giờ inline (`# noqa`, `# type: ignore`, `// biome-ignore` đều là comment).
- File sinh tự động cũng phải sạch comment: migration Alembic (bỏ dòng `# ###`), lock `uv pip compile` (dùng `--no-header --no-annotate`).
- `scripts/check_conventions.py` cưỡng chế hai quy tắc trên; CI và pre-commit đều chạy nó.
- Clean code: hàm nhỏ, một việc; tên rõ nghĩa; không để code chết, import thừa hay magic number.

**Quy ước stub khi chưa triển khai:**
- Python: docstring bắt đầu bằng `TODO:` mô tả hành vi + ràng buộc liên quan (mã FR), thân hàm là `raise NotImplementedError`.
- TypeScript: `throw new Error("TODO: ...")`; component React render `<p className="todo">TODO: ...</p>`.
- Test chưa viết: `@pytest.mark.skip(reason="TODO")` + docstring `TODO:` nêu kịch bản.
- Khi triển khai một hàm: bỏ `TODO:` khỏi docstring (giữ phần mô tả hợp đồng nếu còn giá trị), thay skip bằng test thật.
- Công cụ nội bộ (`scripts/`, `app/db/checkpointer.py`, `migrations/env.py`) và phần nối dây là code thật, không phải stub.

**Công cụ (phải sạch trước khi commit):**
- **Ruff 0.16**: `select` tường minh E, F, I, B, UP, ASYNC, S, PT, RUF, SIM, C4, TC; `airflow/` thêm AIR. `TC` coi Pydantic/SQLAlchemy base là runtime; `app/api/**` tắt TC vì FastAPI đọc annotation lúc chạy. `app/agents/prompts` bị loại khỏi `ruff format`.
- **mypy strict** + plugin Pydantic cho `app`, `worker`, `tests`, `scripts`.
- **Biome** cho frontend (lint + format + organize imports); `tsc --noEmit` riêng vì Vite không type-check. Rule tham số chưa dùng đang tắt (khớp `noUnusedParameters: false`) vì stub chưa dùng tham số.
- **pytest**: `asyncio_mode = "auto"`, loop scope tường minh, `--strict-markers`. Test cần Postgres đặt trong `tests/integration/` và tự skip khi thiếu `DATAFORGE_TEST_DATABASE_URL`. Không dùng SQLite thay Postgres (không có `SKIP LOCKED`, JSONB, enum).

**Kỹ thuật:**
- **Python 3.11.14**, type hints đầy đủ, Pydantic v2 cho mọi schema I/O (API, output agent, bản thiết kế, manifest).
- Bản thiết kế dữ liệu, manifest phiên bản, báo cáo kiểm chứng là **dữ liệu có cấu trúc, có version** — không để ở dạng text tự do.
- Mọi thao tác ngoài (Metabase, GitHub, Postgres publish) phải **idempotent** và retry an toàn.
- Mọi thay đổi schema DB ứng dụng qua **Alembic migration** (`app/db/models.py` là nguồn, có naming convention). Sửa model thì chạy autogenerate, **review tay** (enum Postgres không tự drop khi downgrade), bỏ comment, commit; CI chạy `alembic check`. Enum lưu `value` qua helper `_enum`.
- Không commit secret; cấu hình qua biến môi trường tiền tố `DATAFORGE_` (`backend/.env.example`; `.env.example` ở root cho Compose). Worker không được nhận biến môi trường chứa kết nối Postgres phục vụ.
- Dependency mới: ghim phiên bản chính xác (`uv add "pkg==x.y.z"`, `npm install --save-exact`). Image Docker trong Dockerfile ghim **tag + digest**; image trong Compose ghim tag chính xác. GitHub Actions ghim theo **commit SHA**. Không nâng lẻ dbt-core / dbt-duckdb / duckdb; nâng Airflow thì dựng lại image và chạy job `images`.
- dbt trong Airflow chạy từ `/opt/dbt-venv/bin/dbt`, không cài vào môi trường Python của Airflow. Mỗi lượt chạy một file DuckDB riêng (DuckDB chỉ cho một tiến trình ghi).

### Lệnh

Backend (trong `backend/`):

| Việc | Lệnh |
|---|---|
| Cài đặt | `uv sync --locked` |
| Test unit | `uv run --locked pytest -q` |
| Test cả integration | đặt `DATAFORGE_TEST_DATABASE_URL` rồi `uv run --locked pytest -q` |
| Lint / format | `uv run --locked ruff check . ../airflow ../scripts` · `uv run --locked ruff format --check . ../airflow ../scripts` |
| Type check | `uv run --locked mypy app worker tests ../scripts/check_conventions.py` |
| Quy ước | `uv run --locked python ../scripts/check_conventions.py` |
| API | `uv run --locked uvicorn --factory app.main:create_app --reload` |
| Sandbox worker / publisher | `uv run --locked python -m worker.main` · `uv run --locked python -m worker.publisher_main` |
| Migration | `uv run --locked alembic revision --autogenerate -m "<msg>"` · `uv run --locked alembic upgrade head` · `uv run --locked alembic check` |
| Bảng checkpointer | `uv run --locked python -m app.db.checkpointer` |
| Audit | `uv run --locked pip-audit` |

Frontend (trong `frontend/`): `npm ci` · `npm run dev` · `npm run lint` · `npm run format` · `npm run ci` (Biome + tsc + build).

dbt lock cho Airflow (trong `airflow/`): `uv pip compile dbt/requirements.in -o dbt/requirements.txt --python-version 3.11 --python-platform x86_64-manylinux_2_28 --generate-hashes --no-header --no-annotate`.

Toàn bộ stack (ở root): `cp .env.example .env` rồi `docker compose up -d --build`. Service `migrate` chạy Alembic + setup checkpointer một lần; backend, worker, publisher chỉ khởi động sau khi nó xong.

Pre-commit (ở root): `pre-commit install` (hook: ruff, uv-lock, check_conventions).

### CI (`.github/workflows/ci.yml`)

Chạy trên push và PR vào `main`, `develop`:

| Job | Kiểm tra |
|---|---|
| `conventions` | Không comment, code chỉ ASCII |
| `backend-lint` | `ruff format --check`, `ruff check`, mypy strict |
| `backend-test` | Postgres 16.15 → `alembic upgrade head` → `alembic check` → setup checkpointer → `alembic check` lần nữa → pytest (gồm integration) |
| `frontend` | `npm ci`, Biome, `tsc --noEmit`, `vite build` |
| `images` | `docker compose config`, build image backend + Airflow, `dbt --version` trong venv riêng, import file DAG trong image Airflow |
| `security` | gitleaks, pip-audit (backend + dbt lock), `npm audit --omit=dev` |

Phiên bản đã ghim: Postgres 16.15, Airflow 3.3.2 (python3.11), Metabase v0.63.18.4, Qdrant v1.19.1, uv 0.10.10, Node 22.19.0; Python deps xem `backend/pyproject.toml`, JS deps xem `frontend/package.json`.

---

## 11. Tiêu chí nghiệm thu bản đầu

Bốn tình huống **bắt buộc** phải đúng trước khi coi là hoàn chỉnh:

| Tình huống | Kết quả bắt buộc |
|---|---|
| Rewrite nhanh hơn nhưng đổi kết quả | Loại rewrite, giữ bản hợp lệ trước đó |
| Mã bị sửa sau khi đã test/duyệt | Phê duyệt cũ mất hiệu lực, chạy lại và duyệt lại |
| Cùng một lô chạy hai lần | Không nhân đôi dữ liệu |
| Tải ZIP sang máy sạch | Dựng lại mart + dashboard, không gọi API nền tảng |

Các tình huống còn lại (lỗi giữa chừng khi nạp Postgres, retry Metabase, lô đổi schema, hai lượt trùng giờ) đã có hành vi quy định ở mục 4, kiểm thử nếu còn thời gian.

---

## 12. Ngoài phạm vi bản đầu (có chủ đích)

Đừng triển khai những thứ sau trừ khi được yêu cầu rõ:

| Giới hạn bản đầu | Hướng mở rộng |
|---|---|
| Chỉ snapshot thay thế toàn bộ | Append, upsert theo khóa, SCD Type 2, late-arriving |
| Optimizer chỉ rewrite SQL DuckDB | Index Postgres, phân vùng file |
| Chỉ đo thời gian dựng dữ liệu | Đo tốc độ truy vấn BI trên Postgres |
| Giữ kiến trúc DuckDB → Postgres | Chuyển sang warehouse khác |
| Không đồng bộ ngược từ máy người dùng | Import lại / đồng bộ Git hai chiều |
| Auth tối thiểu hai vai trò | Tổ chức, nhóm, mời thành viên, phân quyền chi tiết |
| Ba loại card cố định | Agent tự chọn loại biểu đồ |
| Không Redis/Celery, không WebSocket | — |
