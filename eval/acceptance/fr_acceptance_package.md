# DataForge — Gói nghiệm thu 21 FR v0.1

**Trạng thái:** `DRAFT` — Deliverable D, Tuần 1. Chưa qua duyệt của nhóm.
**Căn cứ:** đặc tả DataForge (mục 5, bảng FR01–FR21) và mục 7 (giới hạn bản đầu). Không có FR nào ngoài đặc tả.
**Phạm vi của tài liệu:** định nghĩa khi nào một FR được xem là hoàn thành. Tài liệu không hướng dẫn cách cài đặt.

## 0. Quy ước

- **Actor:** `Engineer`, `Reviewer`, `Hệ thống` (các module do máy thực hiện), `Publisher`, `Worker`.
- **Given / When / Then** dùng dữ liệu cụ thể khi có thể. Dữ liệu tham chiếu là bộ golden OULAD (`eval/golden/oulad/`). Khi FR cần dữ liệu khác, ghi rõ.
- **Done when** là một câu đo được. Mỗi câu chỉ có một điều kiện chính, có thể kiểm tra bằng số, bằng trạng thái hoặc bằng một cái nhìn cụ thể.
- Cột **Vấn đề mở** ghi những điểm đặc tả chưa rõ. Mục 9 gom lại các vấn đề này để nhóm quyết định.

---

## 1. Nhóm nạp dữ liệu và hồ sơ

### FR-01 — Tải CSV và nhập yêu cầu

| Mục | Nội dung |
|---|---|
| Mục tiêu | Đưa dữ liệu thô và yêu cầu phân tích vào hệ thống, giữ nguyên file gốc để tái tạo sau này |
| Actor | Engineer |
| Input | Một hoặc nhiều file CSV; một câu yêu cầu bằng ngôn ngữ tự nhiên |
| Expected output | Lô (`batch`) chứa file gốc không đổi byte; bản xem trước (vài dòng đầu) với encoding, dấu phân cách, ký hiệu null và định dạng ngày đoán được; cấu hình đọc được lưu |
| Preconditions | Engineer đã đăng nhập và thuộc một dự án |
| Postconditions | Lô ở trạng thái chờ xác nhận cấu hình đọc; file gốc có SHA-256 được ghi lại |

**User story:** As an Engineer, I want to upload CSV files and describe my analysis goal, so that the system can build a pipeline from my raw data without me writing ETL code first.

**Acceptance criteria**

- AC-01.1
  - Given một file UTF-8 với dấu phẩy, 22 dòng, không BOM
  - When Engineer tải file lên
  - Then bản xem trước hiển thị đúng dấu phẩy và encoding UTF-8, và file gốc có SHA-256 trùng với hash tính trên máy Engineer
- AC-01.2
  - Given cùng file đó, có 15 dòng dữ liệu có chuỗi rỗng ở một cột số
  - When Engineer xác nhận cấu hình đọc
  - Then cấu hình lưu `null_tokens` gồm chuỗi rỗng, và file gốc trong kho không bị sửa (SHA-256 không đổi)
- AC-01.3
  - Given một file dùng dấu chấm phẩy làm phân cách
  - When Engineer tải file lên
  - Then bản xem trước phát hiện `;` là phân cách và hiển thị đúng số cột
- AC-01.4
  - Given Engineer nhập yêu cầu rỗng
  - When bấm gửi
  - Then hệ thống từ chối với thông báo lỗi cụ thể và không tạo lượt chạy

**Tiêu chí trong đặc tả:** Đọc đúng encoding và dấu phân cách, hiển thị preview, lưu file gốc cùng cấu hình đọc.

**Xong khi:** Tải đủ 7 CSV OULAD; SHA-256 từng file khớp `source_manifest.json`; bản xem trước đúng dấu phân cách; cấu hình đọc được lưu và file gốc không đổi byte.

**Vấn đề mở:** đặc tả không nói ngưỡng khi đoán encoding sai. Đề xuất: nếu đoán không chắc chắn, bắt buộc Engineer chọn tay.

---

### FR-02 — Lập hồ sơ dữ liệu

| Mục | Nội dung |
|---|---|
| Mục tiêu | Mô tả mỗi cột bằng thống kê, không cần đưa dữ liệu thô vào LLM |
| Actor | Hệ thống (Worker thực hiện) |
| Input | Lô đã xác nhận cấu hình đọc |
| Expected output | `DataProfile` cho mỗi bảng: kiểu suy ra, tỉ lệ thiếu, số giá trị phân biệt, min/max, tối đa 5 giá trị mẫu, cờ số 0 đứng đầu |
| Preconditions | FR-01 hoàn thành |
| Postconditions | `DataProfile` được lưu; không có dòng dữ liệu thô nào được ghi vào hồ sơ |

**User story:** As an Engineer, I want the system to summarize each column statistically, so that I can judge the data without exposing raw rows to the AI model.

**Acceptance criteria**

- AC-02.1
  - Given bảng `courses` (22 dòng, 3 cột)
  - When hồ sơ được tạo
  - Then `courses.module_presentation_length` có `null_rate = 0`, `distinct_count = 7` và `min = 234`, `max = 269`, khớp `profile_report.json`
- AC-02.2
  - Given bảng `studentInfo` có cột `imd_band` thiếu ở 1.111 dòng
  - When hồ sơ được tạo
  - Then `imd_band.null_rate ≈ 3,41%` và số giá trị mẫu không vượt 5
- AC-02.3
  - Given một cột số có số 0 đứng đầu ở một số dòng (ví dụ `00123`)
  - When hồ sơ được tạo
  - Then cờ `has_leading_zero = true` được đặt
- AC-02.4
  - Given hồ sơ đã tạo
  - When kiểm tra toàn bộ đối tượng gửi đi tới LLM
  - Then không có trường nào chứa dòng dữ liệu thô

**Tiêu chí trong đặc tả:** Trả về thống kê từng cột; không gửi dữ liệu thô vào LLM.

**Xong khi:** Hồ sơ trả thống kê cho từng cột (tỉ lệ thiếu, số giá trị khác nhau, min/max) khớp `profile_report.json`; payload gửi LLM không chứa dòng dữ liệu thô.

**Vấn đề mở:** nếu một cột có hơn 5 giá trị mẫu, chọn 5 giá trị nào (ngẫu nhiên hay đầu tiên)? Cần cố định để kết quả tái lập.

---

### FR-03 — Dò khóa và quan hệ

| Mục | Nội dung |
|---|---|
| Mục tiêu | Tìm khóa chính ứng viên (kể cả khóa ghép) và quan hệ giữa các bảng, kèm bằng chứng |
| Actor | Hệ thống |
| Input | `DataProfile` và dữ liệu lô |
| Expected output | Danh sách `KeyCandidate` và `RelationshipCandidate`; mỗi quan hệ kèm tỉ lệ khớp, số dòng mồ côi, cảnh báo `fanout_warning` |
| Preconditions | FR-02 hoàn thành |
| Postconditions | Các ứng viên được lưu, chưa được coi là ràng buộc |

**User story:** As an Engineer, I want the system to propose keys and relationships with evidence, so that I can confirm the data model instead of finding join keys by hand.

**Acceptance criteria**

- AC-03.1
  - Given bảng `studentInfo`
  - When dò khóa
  - Then `(code_module, code_presentation, id_student)` được đề xuất là khóa ghép với uniqueness = 100%, và `id_student` đơn lẻ **không** được đề xuất (uniqueness ≈ 88,3%)
- AC-03.2
  - Given `studentAssessment` và `assessments` trên `id_assessment`
  - When dò quan hệ
  - Then tỉ lệ khớp = 100%, số mồ côi = 0
- AC-03.3
  - Given `studentVle` không có khóa duy nhất (79,39% trên 5 cột)
  - When dò khóa
  - Then hệ thống **không** đề xuất khóa 5 cột như khóa chính, và báo số dòng trùng
- AC-03.4
  - Given một quan hệ 1-N có mỗi khóa cha nhân bản con lên gấp đôi
  - When dò quan hệ
  - Then `fanout_warning` được đặt

**Tiêu chí trong đặc tả:** Mỗi ứng viên kèm tỉ lệ khớp khóa và cảnh báo join làm tăng số dòng.

**Xong khi:** Mỗi ứng viên khóa/quan hệ kèm tỉ lệ khớp và cờ `fanout_warning`; trên OULAD hệ thống đề xuất đúng 6 khóa chính và không đề xuất `studentVle` làm khóa.

**Vấn đề mở:** đặc tả không định nghĩa "khóa ứng viên" khi uniqueness đúng 100% nhưng chỉ trên một mẫu nhỏ. Đề xuất: yêu cầu cả 100% trên toàn bộ lô.

---

### FR-04 — Đề xuất bản thiết kế dữ liệu

| Mục | Nội dung |
|---|---|
| Mục tiêu | Modeler đề xuất thiết kế gồm grain, bảng fact, dimension, khóa, quan hệ, định nghĩa chỉ số, quy tắc làm sạch, chính sách cập nhật, yêu cầu dashboard, ràng buộc; mỗi mục có lý giải |
| Actor | Hệ thống (Modeler, dùng LLM) |
| Input | `DataProfile`, khóa và quan hệ ứng viên, yêu cầu của Engineer |
| Expected output | `DataDesign` đủ sáu nội dung ở mục 3 của đặc tả; mỗi mục có trường `rationale` không rỗng |
| Preconditions | FR-03 hoàn thành |
| Postconditions | Bản thiết kế có phiên bản và chưa được duyệt |

**User story:** As an Engineer, I want the system to propose a data design with reasons for each choice, so that I can review it quickly instead of designing from scratch.

**Acceptance criteria**

- AC-04.1
  - Given một `DataProfile` hợp lệ
  - When Modeler chạy
  - Then `DataDesign` có đủ các trường: bảng fact (kèm grain), bảng dimension, khóa, quan hệ, định nghĩa chỉ số, quy tắc làm sạch, chính sách cập nhật, yêu cầu dashboard, constraints
- AC-04.2
  - Given `DataDesign` vừa tạo
  - When kiểm tra
  - Then mọi mục trong `DataDesign` có `rationale` không rỗng
- AC-04.3
  - Given một yêu cầu phân tích OULAD
  - When Modeler chạy
  - Then `grain` của `fact_assessment_submission` là "một lần nộp của một enrollment cho một bài đánh giá" (khớp `canonical_design.md`, mục 1)

**Tiêu chí trong đặc tả:** Đủ sáu nội dung ở mục 3, mỗi lựa chọn có lý giải.

**Xong khi:** `DataDesign` có đủ sáu nội dung của đặc tả mục 3 (bảng fact kèm grain, dimension, khóa, quan hệ, định nghĩa chỉ số, quy tắc làm sạch, và các mục còn lại) và mọi lựa chọn có `rationale` không rỗng.

**Vấn đề mở:** đặc tả không định nghĩa tiêu chí so sánh một thiết kế do máy đề xuất với thiết kế chuẩn. Đề xuất: chấm theo bảng tiêu chí ở `canonical_design.md` mục 6, không đòi trùng tên bảng.

---

### FR-05 — Hỏi lại khi thiếu thông tin

| Mục | Nội dung |
|---|---|
| Mục tiêu | Khi dữ liệu mơ hồ, hỏi Engineer thay vì tự đoán |
| Actor | Hệ thống (Modeler, Clarify) |
| Input | `DataProfile` và yêu cầu có điểm mơ hồ |
| Expected output | `ModelerOutput` chứa **hoặc** `design` **hoặc** `questions`, không bao giờ cả hai |
| Preconditions | FR-04 đang chạy |
| Postconditions | Nếu có câu hỏi, lượt chạy dừng chờ trả lời |

**User story:** As an Engineer, I want the system to ask me when a column's meaning is unclear, so that a wrong guess does not become a wrong pipeline.

**Acceptance criteria**

- AC-05.1
  - Given cột `amount` không có mô tả và có phân bố giá trị hai đỉnh
  - When Modeler chạy
  - Then output chứa `questions` hỏi `amount` là đơn giá, thành tiền hay số tiền đã thanh toán, và không chứa `design`
- AC-05.2
  - Given dữ liệu rõ ràng (ví dụ `courses`)
  - When Modeler chạy
  - Then output chứa `design`, không chứa `questions`
- AC-05.3
  - Given một output bị lỗi cả hai trường `design` và `questions`
  - When hệ thống nhận output
  - Then output bị từ chối và Modeler được gọi lại

**Tiêu chí trong đặc tả:** Nghiệp vụ hoặc grain mơ hồ thì hỏi trước khi chốt thiết kế.

**Xong khi:** Trên OULAD, Modeler hỏi lại khi grain hoặc nghiệp vụ mơ hồ (ví dụ `studentVle` có khóa trùng) và không chốt thiết kế cho những điểm đó.

**Vấn đề mở:** bộ 20 tình huống chưa tồn tại. Đây là việc của Tuấn trong `eval/golden/` ở tuần sau; Deliverable D chỉ định nghĩa tiêu chí. Ví dụ OULAD có `studentVle` (Q1, nhóm trùng) là tình huống mơ hồ thật.

---

## 2. Nhóm duyệt của con người

### FR-06 — Duyệt thiết kế (Cổng 1)

| Mục | Nội dung |
|---|---|
| Mục tiêu | Engineer kiểm tra và quyết định về thiết kế trước khi sinh mã |
| Actor | Engineer |
| Input | `DataDesign` ở trạng thái chờ duyệt |
| Expected output | Quyết định một trong ba: duyệt, sửa trực tiếp (tạo phiên bản mới), trả lại Modeler |
| Preconditions | FR-04 hoàn thành, không có câu hỏi FR-05 chưa trả lời |
| Postconditions | Phê duyệt gắn với vân tay phiên bản thiết kế; `codegen` chỉ chạy khi có phê duyệt |

**User story:** As an Engineer, I want to approve, edit, or reject the data design before any code is written, so that I control the business meaning.

**Acceptance criteria**

- AC-06.1
  - Given thiết kế ở trạng thái chờ duyệt
  - When Engineer chỉ bấm "trả lại"
  - Then lượt chạy quay lại Modeler, không có bản mã nào được sinh
- AC-06.2
  - Given Engineer sửa `grain` của một bảng fact
  - When lưu
  - Then tạo phiên bản thiết kế mới, phiên bản cũ không bị ghi đè
- AC-06.3
  - Given thiết kế chưa được duyệt
  - When gọi trực tiếp bước sinh mã
  - Then hệ thống từ chối (không chỉ ẩn nút trên giao diện)
- AC-06.4
  - Given Engineer duyệt phiên bản v2
  - When hệ thống ghi phê duyệt
  - Then phê duyệt gắn với `design_hash` của đúng v2

**Tiêu chí trong đặc tả:** Không sinh mã khi chưa có xác nhận.

**Xong khi:** Mọi lần gọi bước sinh mã khi chưa có phê duyệt Cổng 1 đều bị từ chối.

---

### FR-07 — Sinh dbt model ba tầng

| Mục | Nội dung |
|---|---|
| Mục tiêu | Viết dbt model bronze, silver, mart theo thiết kế đã duyệt |
| Actor | Hệ thống (Codegen, dùng LLM cho silver và mart; bronze sinh từ khuôn) |
| Input | `DataDesign` đã duyệt, vài bài mẫu từ kho truy xuất |
| Expected output | Dự án dbt `CodeVersion` gồm model bronze, silver, mart; đã qua `guard.py` |
| Preconditions | FR-06 đã duyệt |
| Postconditions | `CodeVersion` vN được lưu với `code_hash` |

**User story:** As an Engineer, I want the system to write the three-layer dbt models from my approved design, so that I do not write repetitive transformation code.

**Acceptance criteria**

- AC-07.1
  - Given thiết kế OULAD đã duyệt
  - When Codegen chạy
  - Then `dbt compile` thành công và không có lỗi
- AC-07.2
  - Given bảng bronze của `studentInfo`
  - When đọc kết quả
  - Then `id_student` có kiểu văn bản, và giá trị `00123` (nếu có) không bị đổi thành `123`
- AC-07.3
  - Given model silver `silver_student_info`
  - When chạy
  - Then không có model silver hay mart nào đọc trực tiếp từ file CSV (chỉ đọc qua `ref`)
- AC-07.4
  - Given mã do LLM sinh ra có câu `read_csv` trực tiếp
  - When `guard.py` kiểm tra
  - Then mã bị từ chối trước khi chạy

**Tiêu chí trong đặc tả:** dbt compile thành công; bronze giữ biểu diễn nguồn.

**Xong khi:** `dbt compile` thành công trên OULAD và bronze giữ biểu diễn chuỗi (ví dụ `00123` không thành `123`).

**Vấn đề mở:** đặc tả không nói lượt chạy đầu tiên có phải đạt đúng số dòng mart kỳ vọng hay không, khi chưa có quyết định C09 (cộng dồn `studentVle`). Mục này không áp dụng cho `fact_vle_daily` cho tới khi nhóm duyệt Q1.

---

### FR-08 — Sinh test từ ràng buộc đã duyệt

| Mục | Nội dung |
|---|---|
| Mục tiêu | Chỉ biến ràng buộc đã duyệt thành test bắt buộc; quan sát thống kê không tự thành test |
| Actor | Hệ thống (Codegen) |
| Input | Các ràng buộc đã duyệt ở Cổng 1; các quan sát từ hồ sơ |
| Expected output | Tập test dbt; danh sách quan sát được đề xuất (không bắt buộc) |
| Preconditions | FR-06 đã duyệt |
| Postconditions | Test bắt buộc chỉ gồm ràng buộc đã duyệt |

**User story:** As an Engineer, I want only approved rules to become mandatory tests, so that a coincidence in the first batch does not break future batches.

**Acceptance criteria**

- AC-08.1
  - Given ràng buộc "khóa `studentInfo` duy nhất" đã duyệt và quan sát "cột `email` không trùng" chưa duyệt
  - When Codegen sinh test
  - Then có test unique cho khóa `studentInfo`, và không có test unique cho `email`
- AC-08.2
  - Given quan sát "tổng `weight` mỗi presentation = 100" (đúng ở 19/22 presentation không-Exam, sai ở GGG)
  - When Codegen chạy trên OULAD
  - Then không có test bắt buộc nào kiểm tra tổng `weight`
- AC-08.3
  - Given quan sát "`studentVle` duy nhất theo (enrollment, site, ngày)" (sai: 79,39%)
  - When Codegen chạy
  - Then không có test unique cho tổ hợp này

**Tiêu chí trong đặc tả:** Không sinh test bắt buộc từ quan sát chưa được duyệt.

**Xong khi:** Chỉ ràng buộc đã duyệt thành test bắt buộc; không có test nào sinh từ các quan sát A1–A10 của thiết kế chuẩn.

---

### FR-09 — Sinh file DAG từ template

| Mục | Nội dung |
|---|---|
| Mục tiêu | Tạo cấu hình DAG để Airflow chạy lại pipeline; không sinh mã Python mới cho Airflow |
| Actor | Hệ thống (Codegen) |
| Input | Pipeline đã duyệt |
| Expected output | File `dag_config.json` trong `approved/<phiên bản>/` |
| Preconditions | FR-07, FR-08 hoàn thành |
| Postconditions | Airflow phát hiện được DAG mới mà không cần deploy lại |

**User story:** As an Engineer, I want the scheduled job to be created from a fixed template, so that Airflow never has to run Python code written by the AI.

**Acceptance criteria**

- AC-09.1
  - Given một pipeline đã duyệt
  - When sinh DAG
  - Then chỉ có file `dag_config.json` được tạo, không có file `.py` mới
- AC-09.2
  - Given `dag_config.json`
  - When Airflow import file DAG template
  - Then DAG import được và không có lỗi import
- AC-09.3
  - Given một cấu hình DAG có trường lạ
  - When Airflow quét thư mục approved
  - Then cấu hình bị bỏ qua có cảnh báo, không chạy

**Tiêu chí trong đặc tả:** DAG import được; không nạp mã Python tùy ý vào Airflow.

**Xong khi:** DAG sinh từ template import được và chỉ tạo file `dag_config.json`, không tạo file Python mới.

---

## 3. Nhóm thực thi và đo đạc

### FR-10 — Chạy pipeline trong worker cách ly

| Mục | Nội dung |
|---|---|
| Mục tiêu | Chạy mã do máy sinh ra trong môi trường có giới hạn và không có quyền kho dữ liệu |
| Actor | Worker |
| Input | Job từ hàng đợi |
| Expected output | Kết quả chạy; log; trạng thái job |
| Preconditions | Job có trong bảng `jobs` |
| Postconditions | Job hoàn thành, hỏng hoặc được thử lại; không có kết nối tới Postgres phục vụ |

**User story:** As a Reviewer, I want AI-generated code to run in an isolated worker with limited resources, so that a bad query cannot harm the warehouse or leak secrets.

**Acceptance criteria**

- AC-10.1
  - Given job chạy mã vượt 600 giây
  - When hết thời gian
  - Then tiến trình và mọi tiến trình con bị dừng
- AC-10.2
  - Given mã cố gắng đọc biến môi trường `DATABASE_URL`
  - When chạy
  - Then biến không tồn tại trong tiến trình con (chỉ 7 biến trong danh sách cho phép được truyền)
- AC-10.3
  - Given mã cố gắng mở kết nối mạng ra ngoài
  - When chạy trong container worker
  - Then kết nối thất bại
- AC-10.4
  - Given mã cố gắng ghi vào kho dữ liệu
  - When chạy
  - Then không có đường kết nối tới kho dữ liệu để ghi

**Tiêu chí trong đặc tả:** Worker có giới hạn tài nguyên và không giữ thông tin kết nối warehouse.

**Xong khi:** Tiến trình worker có giới hạn RAM, CPU và thời gian, và không đọc được biến môi trường chứa thông tin kết nối kho dữ liệu.

---

### FR-11 — Đo hiệu năng từng model

| Mục | Nội dung |
|---|---|
| Mục tiêu | Ghi thời gian chạy, số dòng quét, bộ nhớ đỉnh cho mỗi model |
| Actor | Worker |
| Input | Job chạy model |
| Expected output | Bản ghi số đo cho mỗi model: thời gian, số dòng, bộ nhớ đỉnh |
| Preconditions | FR-10 hoàn thành |
| Postconditions | Số đo được lưu với phiên bản mã |

**User story:** As a Reviewer, I want per-model performance numbers, so that I can see which part of the pipeline is slow.

**Acceptance criteria**

- AC-11.1
  - Given một model chạy 3 lần
  - When đo
  - Then lưu được thời gian của cả 3 lần, không chỉ lần cuối
- AC-11.2
  - Given model đọc bảng 10,6 triệu dòng
  - When hoàn thành
  - Then số dòng quét được ghi đúng 10.655.280 (không làm tròn, không lấy mẫu)
- AC-11.3
  - Given model chạy
  - When đo bộ nhớ
  - Then bộ nhớ đỉnh được ghi, không chỉ bộ nhớ cuối

**Tiêu chí trong đặc tả:** Ghi thời gian chạy, số dòng quét, bộ nhớ đỉnh.

**Xong khi:** Mỗi model có thời gian chạy, số dòng quét và bộ nhớ đỉnh; số dòng quét của `studentVle` bằng 10.655.280.

---

### FR-12 — Đề xuất và kiểm chứng rewrite

| Mục | Nội dung |
|---|---|
| Mục tiêu | Tối ưu SQL, giữ rewrite chỉ khi vừa nhanh hơn vừa cho kết quả tương đương |
| Actor | Hệ thống (Optimizer; đề xuất bằng sqlglot và LLM, phán quyết bằng `judge.py` không dùng LLM) |
| Input | Model chậm, ngân sách (tối đa 5 ứng viên, 600 giây) |
| Expected output | Danh sách rewrite với phán quyết: giữ, loại (kèm lý do) |
| Preconditions | FR-11 có số đo |
| Postconditions | Bản giữ được là bản nhanh nhất hợp lệ; nếu không có, giữ bản gốc |

**User story:** As a Reviewer, I want SQL rewrites that are faster but produce the same results, so that performance improves without silent data changes.

**Acceptance criteria**

- AC-12.1
  - Given rewrite nhanh hơn nhưng cho kết quả khác bản gốc
  - When phán quyết
  - Then rewrite bị loại với lý do "sai kết quả", và bản gốc được giữ
- AC-12.2
  - Given mọi rewrite đều không nhanh hơn ngưỡng nhiễu đo được
  - When phán quyết
  - Then giữ bản gốc, và ghi "query vốn đã tốt" là kết quả hợp lệ
- AC-12.3
  - Given hai rewrite hợp lệ
  - When chọn
  - Then chọn rewrite có thời gian trung vị thấp hơn
- AC-12.4
  - Given ngân sách đã dùng hết 5 ứng viên
  - When tiếp tục
  - Then không thử thêm ứng viên nào

**Tiêu chí trong đặc tả:** Rewrite đổi kết quả bị loại; mọi rewrite bị loại thì giữ bản hợp lệ trước đó.

**Xong khi:** Rewrite đổi kết quả bị loại kèm lý do; khi mọi rewrite bị loại thì bản hợp lệ trước đó được giữ.

**Vấn đề mở:** đặc tả không cho biết ngưỡng nhiễu cụ thể là bao nhiêu. Cần Tuấn/nhóm đo nhiễu trên máy chuẩn trước khi cố định.

---

### FR-13 — Duyệt mã và bằng chứng (Cổng 2)

| Mục | Nội dung |
|---|---|
| Mục tiêu | Reviewer xem mã, bằng chứng và quyết định công bố |
| Actor | Reviewer |
| Input | `CodeVersion`, kết quả test, bảng so sánh hiệu năng, cấu hình dashboard |
| Expected output | Quyết định duyệt hoặc trả lại Codegen, kèm vân tay phiên bản |
| Preconditions | FR-10, FR-11, FR-12 hoàn thành |
| Postconditions | Phê duyệt gắn với đúng một `CodeVersion` và báo cáo |

**User story:** As a Reviewer, I want to review the code diff and the evidence together, so that I approve only what has actually been tested.

**Acceptance criteria**

- AC-13.1
  - Given Reviewer duyệt phiên bản mã vN
  - When sau đó Engineer sửa mã thành vN+1
  - Then phê duyệt của vN không còn hiệu lực và không thể dùng để công bố vN+1
- AC-13.2
  - Given Reviewer trả lại
  - When lưu
  - Then lượt chạy quay về Codegen với ghi chú của Reviewer
- AC-13.3
  - Given Reviewer xem bằng chứng
  - When mở màn hình
  - Then thấy được kết quả test và bảng so sánh hiệu năng của đúng phiên bản đang xem

**Tiêu chí trong đặc tả:** Không thể công bố phiên bản khác bằng phê duyệt của phiên bản cũ.

**Xong khi:** Phiên bản đã duyệt không thể công bố sau khi mã bị sửa: phê duyệt cũ mất hiệu lực.

**Vấn đề mở:** đặc tả nói Reviewer là người có quyền duyệt, nhưng chế độ cá nhân cho một người làm cả hai vai trò. Xem mục 9, vấn đề V1.

---

## 4. Nhóm công bố và xuất

### FR-14 — Công bố sang Postgres

| Mục | Nội dung |
|---|---|
| Mục tiêu | Nạp mart vào staging, đối chiếu, rồi đổi công tắc phục vụ |
| Actor | Publisher |
| Input | Phiên bản đã duyệt |
| Expected output | Phiên bản được công bố; bản cũ vẫn phục vụ nếu lỗi |
| Preconditions | FR-13 đã duyệt |
| Postconditions | `published_versions` có bản mới; dashboard trỏ tới bản mới |

**User story:** As a Reviewer, I want the approved data published to the warehouse safely, so that a failed load never shows an empty dashboard to users.

**Acceptance criteria**

- AC-14.1
  - Given bước đối chiếu phát hiện lệch số dòng
  - When chạy
  - Then không chạy bước đổi công tắc
- AC-14.2
  - Given lỗi xảy ra giữa bước đổi công tắc
  - When giao dịch quay lui
  - Then dashboard vẫn đọc được phiên bản cũ và không có trang trống
- AC-14.3
  - Given OULAD đã nạp
  - When đối chiếu
  - Then số dòng mỗi bảng khớp kỳ vọng trong `canonical_design.md` mục 6 (I1, I2, I3, I6)

**Tiêu chí trong đặc tả:** Nạp staging rồi đối chiếu; lỗi giữa chừng không phá phiên bản đang phục vụ.

**Xong khi:** Nạp staging rồi đối chiếu; lỗi giữa chừng không làm hỏng phiên bản đang phục vụ.

---

### FR-15 — Dựng card và dashboard Metabase

| Mục | Nội dung |
|---|---|
| Mục tiêu | Tạo card và dashboard tự động, không tạo bản trùng khi thử lại |
| Actor | Hệ thống (Publisher, module Metabase) |
| Input | Phiên bản đã công bố; cấu hình dashboard đã duyệt |
| Expected output | Các card có số đúng; một dashboard; link trả về |
| Preconditions | FR-14 hoàn thành |
| Postconditions | Các ID card và dashboard được lưu trong `metabase_objects` |

**User story:** As a Reviewer, I want the dashboard created automatically and checked before I receive the link, so that I never receive a broken chart.

**Acceptance criteria**

- AC-15.1
  - Given một card có truy vấn lỗi
  - When kiểm tra trước khi trả link
  - Then card bị báo lỗi và link không được trả về
- AC-15.2
  - Given lỗi tạm thời ở API Metabase, lượt đầu thất bại
  - When thử lại 5 lần
  - Then chỉ có đúng một dashboard và đúng một bộ card tồn tại
- AC-15.3
  - Given dashboard đã có
  - When chạy lại bước dựng
  - Then card được cập nhật, không được tạo mới
- AC-15.4
  - Given cấu hình dashboard gồm đúng 3 loại card
  - When dựng
  - Then không có card loại khác được tạo

**Tiêu chí trong đặc tả:** Kiểm tra truy vấn từng card trước khi trả link; retry không tạo bản trùng.

**Xong khi:** Mọi card được chạy thử trước khi trả link, và retry không tạo thêm dashboard hay card trùng.

---

### FR-16 — Đăng ký DAG chạy lại theo lịch

| Mục | Nội dung |
|---|---|
| Mục tiêu | Pipeline đã duyệt chạy lại theo lịch trên Airflow |
| Actor | Engineer (đăng ký), Hệ thống (chạy) |
| Input | `dag_config.json` đã duyệt |
| Expected output | DAG hiển thị trong Airflow; lịch chạy |
| Preconditions | FR-09 hoàn thành |
| Postconditions | Lượt chạy theo lịch dùng đúng phiên bản đã duyệt |

**User story:** As an Engineer, I want approved pipelines to re-run on schedule, so that new batches of data flow in without manual work.

**Acceptance criteria**

- AC-16.1
  - Given một lô được chạy hai lần
  - When hoàn thành lần thứ hai
  - Then bảng đích có số dòng bằng lần đầu, không nhân đôi
- AC-16.2
  - Given lô chưa có đủ file (thiếu `_READY`)
  - When DAG đến lịch
  - Then DAG chờ, không chạy
- AC-16.3
  - Given hai lượt chạy cùng pipeline trùng giờ
  - When hệ thống nhận
  - Then lượt thứ hai xếp hàng, không chạy song song

**Tiêu chí trong đặc tả:** Cùng một lô chạy hai lần không nhân đôi dữ liệu.

**Xong khi:** Cùng một lô chạy hai lần cho số dòng đích giống hệt lần đầu; không nhân đôi.

---

### FR-17 — Dừng khi lô mới đổi schema

| Mục | Nội dung |
|---|---|
| Mục tiêu | Không tự áp dụng thay đổi cấu trúc chưa được duyệt |
| Actor | Hệ thống |
| Input | Lô mới |
| Expected output | Dừng và yêu cầu Engineer quyết định |
| Preconditions | FR-16 đang chạy |
| Postconditions | Lô bị giữ, không ghi vào kho |

**User story:** As an Engineer, I want the pipeline to stop when a new batch has a different structure, so that unreviewed changes never reach the warehouse.

**Acceptance criteria**

- AC-17.1
  - Given lô mới có thêm một cột
  - When DAG chạy
  - Then dừng trước bước nạp, báo cột mới
- AC-17.2
  - Given lô mới đổi kiểu một cột
  - When DAG chạy
  - Then dừng, không ép kiểu tự động
- AC-17.3
  - Given lô có cấu trúc giống hệt
  - When DAG chạy
  - Then không dừng

**Tiêu chí trong đặc tả:** Không tự áp dụng thay đổi schema chưa được duyệt.

**Xong khi:** Lô có cột mới hoặc đổi kiểu bị dừng trước bước nạp, và không có dữ liệu nào vào kho.

**Vấn đề mở:** đặc tả không định nghĩa "đổi kiểu" có bao gồm đổi cách viết (ví dụ `10-20` thành `10-20%`). Cần quyết định.

---

### FR-18 — Xuất ZIP project độc lập

| Mục | Nội dung |
|---|---|
| Mục tiêu | Gói toàn bộ pipeline để chạy được trên máy khác mà không gọi API nền tảng |
| Actor | Engineer |
| Input | Phiên bản đã duyệt |
| Expected output | ZIP tất định: cùng phiên bản thì cùng checksum |
| Preconditions | FR-13 đã duyệt |
| Postconditions | Manifest phiên bản và báo cáo kiểm chứng nằm trong ZIP |

**User story:** As an Engineer, I want a zip of the approved project that runs on any clean machine, so that the team is not locked into this platform.

**Acceptance criteria**

- AC-18.1
  - Given cùng một phiên bản được nén hai lần
  - When so sánh checksum
  - Then hai file ZIP giống hệt (cùng thứ tự file, cùng timestamp)
- AC-18.2
  - Given ZIP được giải nén trên máy sạch, điền cấu hình, đưa CSV vào
  - When chạy
  - Then dựng lại được mart và dashboard
- AC-18.3
  - Given máy sạch không có kết nối tới DataForge
  - When chạy AC-18.2
  - Then không có lệnh gọi nào tới API nền tảng

**Tiêu chí trong đặc tả:** Máy sạch dựng lại được mart và dashboard, không gọi API nền tảng.

**Xong khi:** ZIP của OULAD dựng lại được mart và dashboard trên máy sạch mà không gọi API nền tảng nào.

---

### FR-19 — Mở Pull Request

| Mục | Nội dung |
|---|---|
| Mục tiêu | Đưa mã đã duyệt vào repo người dùng chỉ định, không tự merge |
| Actor | Engineer |
| Input | Phiên bản đã duyệt; repo đích và quyền truy cập |
| Expected output | PR chứa đúng nội dung phiên bản đã duyệt |
| Preconditions | FR-13 đã duyệt; Engineer có quyền ghi vào repo đích |
| Postconditions | PR mở, chưa merge |

**User story:** As an Engineer, I want the approved code opened as a pull request in my own repo, so that my team reviews it with the normal process.

**Acceptance criteria**

- AC-19.1
  - Given PR được mở
  - When so sánh nội dung với phiên bản đã duyệt
  - Then nội dung trùng từng byte (so checksum)
- AC-19.2
  - Given PR vừa mở
  - When kiểm tra trạng thái
  - Then trạng thái là chưa merge, và hệ thống không có quyền merge
- AC-19.3
  - Given Engineer không có quyền ghi vào repo đích
  - When gửi yêu cầu
  - Then hệ thống báo lỗi quyền, không tạo nhánh

**Tiêu chí trong đặc tả:** PR chứa đúng phiên bản đã duyệt; hệ thống không tự merge.

**Xong khi:** PR chứa đúng nội dung phiên bản đã duyệt (kiểm bằng checksum) và không tự merge.

---

## 5. Nhóm xác thực và độ bền

### FR-20 — Xác thực và phân quyền theo dự án

| Mục | Nội dung |
|---|---|
| Mục tiêu | Chỉ người có vai trò đúng trong dự án mới thực hiện được thao tác |
| Actor | Hệ thống |
| Input | Thông tin đăng nhập; vai trò trong dự án |
| Expected output | Quyền được cấp hoặc từ chối theo vai trò |
| Preconditions | Người dùng đã có tài khoản |
| Postconditions | Lịch sử duyệt gắn với dự án |

**User story:** As a project owner, I want only the right role to approve, so that approvals mean something.

**Acceptance criteria**

- AC-20.1
  - Given người dùng là Engineer của dự án
  - When gọi API duyệt (Cổng 2)
  - Then bị từ chối
- AC-20.2
  - Given người dùng không thuộc dự án
  - When truy cập bất kỳ tài nguyên nào của dự án
  - Then bị từ chối
- AC-20.3
  - Given Reviewer của dự án A
  - When cố duyệt lượt chạy của dự án B
  - Then bị từ chối
- AC-20.4
  - Given Engineer và Reviewer là cùng một người trong chế độ cá nhân
  - When duyệt
  - Then hệ thống cho phép và ghi nhật ký "không có review độc lập"

**Tiêu chí trong đặc tả:** Chỉ Reviewer có quyền duyệt; lịch sử duyệt gắn với dự án.

**Xong khi:** Chỉ Reviewer duyệt được Cổng 2 và mọi quyết định duyệt được ghi vào lịch sử gắn với dự án. (Xung đột với chế độ cá nhân: xem V1.)

**Vấn đề mở:** AC-20.4 là quyết định nghiệp vụ, không phải kỹ thuật. Xem vấn đề V1 ở mục 9.

---

### FR-21 — Khôi phục lượt đang chờ duyệt

| Mục | Nội dung |
|---|---|
| Mục tiêu | Khởi động lại backend không làm mất lượt đang dở |
| Actor | Hệ thống |
| Input | Trạng thái lượt chạy lưu bền vững |
| Expected output | Lượt chạy tiếp tục đúng bước |
| Preconditions | Trạng thái đã được lưu |
| Postconditions | Người dùng thấy đúng nội dung đang chờ |

**User story:** As an Engineer, I want my pending review to still be there after a server restart, so that I do not lose work.

**Acceptance criteria**

- AC-21.1
  - Given lượt chạy đang chờ duyệt Cổng 1
  - When backend khởi động lại
  - Then lượt vẫn ở Cổng 1 với đúng nội dung thiết kế
- AC-21.2
  - Given sập server giữa hai bước của graph
  - When khởi động lại
  - Then lượt tiếp tục từ bước dở, không chạy lại bước đã xong
- AC-21.3
  - Given Engineer mở lại trình duyệt sau khi restart
  - When xem lượt chạy
  - Then thấy đúng vị trí đang dừng

**Tiêu chí trong đặc tả:** Backend khởi động lại vẫn tiếp tục đúng trạng thái.

**Xong khi:** Khởi động lại backend ở ba điểm chờ (Cổng 1, giữa codegen và execute, Cổng 2) thì lượt chạy tiếp tục đúng bước với nội dung không đổi.

---

## 6. Tổng hợp

### 6.1 Ma trận truy vết FR → mục tiêu "Done when"

| FR | Nhóm | Phụ thuộc | Đo bằng OULAD |
|---|---|---|---|
| FR-01 | Nạp | — | SHA-256 khớp `source_manifest.json` |
| FR-02 | Nạp | FR-01 | Tỉ lệ thiếu và số giá trị khớp `profile_report.json` |
| FR-03 | Nạp | FR-02 | 6 khóa chính, 10 quan hệ |
| FR-04 | Thiết kế | FR-03 | Grain khớp `canonical_design.md` |
| FR-05 | Thiết kế | FR-04 | Bộ 20 tình huống (chưa có) |
| FR-06 | Duyệt | FR-04 | Chặn sinh mã khi chưa duyệt |
| FR-07 | Mã | FR-06 | Số dòng mart I1, I2 |
| FR-08 | Mã | FR-06 | 0 test từ A1–A10 |
| FR-09 | Mã | FR-07, FR-08 | DAG import được |
| FR-10 | Thực thi | — | 10 mã tấn công bị chặn |
| FR-11 | Thực thi | FR-10 | Số dòng quét 10.655.280 |
| FR-12 | Tối ưu | FR-11 | Bộ thử cố định |
| FR-13 | Duyệt | FR-10–12 | Khóa phê duyệt theo phiên bản |
| FR-14 | Công bố | FR-13 | I1–I6 |
| FR-15 | Dashboard | FR-14 | Cột "Kiểm tra" |
| FR-16 | Lịch | FR-09 | Chạy hai lần, số dòng giống |
| FR-17 | Lịch | FR-16 | 3 lô thử |
| FR-18 | Xuất | FR-13 | Số dòng I1–I3 trên máy sạch |
| FR-19 | Xuất | FR-13 | Checksum PR |
| FR-20 | Bảo mật | — | Kiểm tra vai trò phía máy chủ |
| FR-21 | Bền | — | Giết tiến trình ở 3 điểm |

### 6.2 Bộ kiểm thử dùng lại

Các tình huống dùng cho nhiều FR: (a) OULAD gốc; (b) OULAD với một cột mới; (c) OULAD với một cột đổi kiểu; (d) bộ 10 mã tấn công; (e) bộ 20 tình huống mơ hồ/rõ ràng (FR-05, chưa có).

---

## 6.3 Bảng tóm tắt "xong khi" (một dòng mỗi FR)

| FR | Tiêu chí trong đặc tả | Xong khi |
|---|---|---|
| FR-01 | Đọc đúng encoding và dấu phân cách, hiển thị preview, lưu file gốc cùng cấu hình đọc | Tải đủ 7 CSV OULAD; SHA-256 từng file khớp `source_manifest.json`; bản xem trước đúng dấu phân cách; cấu hình đọc được lưu và file gốc không đổi byte. |
| FR-02 | Trả về thống kê từng cột; không gửi dữ liệu thô vào LLM | Hồ sơ trả thống kê cho từng cột (tỉ lệ thiếu, số giá trị khác nhau, min/max) khớp `profile_report.json`; payload gửi LLM không chứa dòng dữ liệu thô. |
| FR-03 | Mỗi ứng viên kèm tỉ lệ khớp khóa và cảnh báo join làm tăng số dòng | Mỗi ứng viên khóa/quan hệ kèm tỉ lệ khớp và cờ `fanout_warning`; trên OULAD hệ thống đề xuất đúng 6 khóa chính và không đề xuất `studentVle` làm khóa. |
| FR-04 | Đủ sáu nội dung ở mục 3, mỗi lựa chọn có lý giải | `DataDesign` có đủ sáu nội dung của đặc tả mục 3 (bảng fact kèm grain, dimension, khóa, quan hệ, định nghĩa chỉ số, quy tắc làm sạch, và các mục còn lại) và mọi lựa chọn có `rationale` không rỗng. |
| FR-05 | Nghiệp vụ hoặc grain mơ hồ thì hỏi trước khi chốt thiết kế | Trên OULAD, Modeler hỏi lại khi grain hoặc nghiệp vụ mơ hồ (ví dụ `studentVle` có khóa trùng) và không chốt thiết kế cho những điểm đó. |
| FR-06 | Không sinh mã khi chưa có xác nhận | Mọi lần gọi bước sinh mã khi chưa có phê duyệt Cổng 1 đều bị từ chối. |
| FR-07 | dbt compile thành công; bronze giữ biểu diễn nguồn | `dbt compile` thành công trên OULAD và bronze giữ biểu diễn chuỗi (ví dụ `00123` không thành `123`). |
| FR-08 | Không sinh test bắt buộc từ quan sát chưa được duyệt | Chỉ ràng buộc đã duyệt thành test bắt buộc; không có test nào sinh từ các quan sát A1–A10 của thiết kế chuẩn. |
| FR-09 | DAG import được; không nạp mã Python tùy ý vào Airflow | DAG sinh từ template import được và chỉ tạo file `dag_config.json`, không tạo file Python mới. |
| FR-10 | Worker có giới hạn tài nguyên và không giữ thông tin kết nối warehouse | Tiến trình worker có giới hạn RAM, CPU và thời gian, và không đọc được biến môi trường chứa thông tin kết nối kho dữ liệu. |
| FR-11 | Ghi thời gian chạy, số dòng quét, bộ nhớ đỉnh | Mỗi model có thời gian chạy, số dòng quét và bộ nhớ đỉnh; số dòng quét của `studentVle` bằng 10.655.280. |
| FR-12 | Rewrite đổi kết quả bị loại; mọi rewrite bị loại thì giữ bản hợp lệ trước đó | Rewrite đổi kết quả bị loại kèm lý do; khi mọi rewrite bị loại thì bản hợp lệ trước đó được giữ. |
| FR-13 | Không thể công bố phiên bản khác bằng phê duyệt của phiên bản cũ | Phiên bản đã duyệt không thể công bố sau khi mã bị sửa: phê duyệt cũ mất hiệu lực. |
| FR-14 | Nạp staging rồi đối chiếu; lỗi giữa chừng không phá phiên bản đang phục vụ | Nạp staging rồi đối chiếu; lỗi giữa chừng không làm hỏng phiên bản đang phục vụ. |
| FR-15 | Kiểm tra truy vấn từng card trước khi trả link; retry không tạo bản trùng | Mọi card được chạy thử trước khi trả link, và retry không tạo thêm dashboard hay card trùng. |
| FR-16 | Cùng một lô chạy hai lần không nhân đôi dữ liệu | Cùng một lô chạy hai lần cho số dòng đích giống hệt lần đầu; không nhân đôi. |
| FR-17 | Không tự áp dụng thay đổi schema chưa được duyệt | Lô có cột mới hoặc đổi kiểu bị dừng trước bước nạp, và không có dữ liệu nào vào kho. |
| FR-18 | Máy sạch dựng lại được mart và dashboard, không gọi API nền tảng | ZIP của OULAD dựng lại được mart và dashboard trên máy sạch mà không gọi API nền tảng nào. |
| FR-19 | PR chứa đúng phiên bản đã duyệt; hệ thống không tự merge | PR chứa đúng nội dung phiên bản đã duyệt (kiểm bằng checksum) và không tự merge. |
| FR-20 | Chỉ Reviewer có quyền duyệt; lịch sử duyệt gắn với dự án | Chỉ Reviewer duyệt được Cổng 2 và mọi quyết định duyệt được ghi vào lịch sử gắn với dự án. (Xung đột với chế độ cá nhân: xem V1.) |
| FR-21 | Backend khởi động lại vẫn tiếp tục đúng trạng thái | Khởi động lại backend ở ba điểm chờ (Cổng 1, giữa codegen và execute, Cổng 2) thì lượt chạy tiếp tục đúng bước với nội dung không đổi. |

Ghi chú: mọi ngưỡng số trong bảng trên lấy từ dữ liệu OULAD đã đo, không tự đặt. Các ngưỡng không có trong đặc tả (ví dụ tỉ lệ đạt cho bộ test tình huống, số mã tấn công) được ghi là ĐỀ XUẤT trong mục 9 và không dùng làm tiêu chí xong.

## 7. Định nghĩa "Hoàn thành" của Deliverable D

Gói này được coi là hoàn thành khi:

- [x] Có đủ 21 FR, mỗi FR có metadata, user story, ít nhất ba acceptance criteria, và câu "Done when".
- [ ] Nhóm duyệt các vấn đề mở ở mục 9.
- [ ] Các câu "Done when" được người phụ trách module xác nhận là đo được.

## 8. Tự kiểm tra (self-review)

| Câu hỏi | Kết quả |
|---|---|
| Có bịa FR nào không? | Không. Đủ 21 FR, tên và mục tiêu bám sát đặc tả |
| Có acceptance criteria nào không kiểm thử được? | Hầu hết có số cụ thể. FR-05 phụ thuộc bộ tình huống chưa có; ghi rõ ở vấn đề mở |
| "Done when" có mơ hồ không? | Các câu có số hoặc danh sách cụ thể; FR-12 và FR-17 còn ngưỡng/định nghĩa chưa chốt, đã ghi |
| Có mâu thuẫn giữa FR và invariant không? | Có một mâu thuẫn tiềm ẩn ở FR-20 và chế độ cá nhân (V1) |
| Có FR nào phụ thuộc số liệu chưa đo không? | FR-12 cần ngưỡng nhiễu; FR-05 cần bộ tình huống |

## 9. Vấn đề mở cần nhóm quyết định

| ID | Vấn đề | FR liên quan | Đề xuất |
|---|---|---|---|
| V1 | Đặc tả nói chỉ Reviewer được duyệt, nhưng chế độ cá nhân cho một người làm cả hai vai | FR-13, FR-20 | Giữ chế độ cá nhân, ghi nhật ký rõ ràng; hoặc tách quyền rõ ràng theo chế độ |
| V2 | Ngưỡng nhiễu đo hiệu năng chưa có số | FR-12 | Đo trên máy chuẩn, lấy độ lệch chuẩn của 10 lần chạy lặp |
| V3 | Đoán encoding khi không chắc chắn | FR-01 | Bắt buộc Engineer chọn tay |
| V4 | Chọn 5 giá trị mẫu khi có hơn 5 giá trị | FR-02 | Cố định theo thứ tự xuất hiện đầu tiên |
| V5 | "Khóa ứng viên" với uniqueness 100% trên mẫu nhỏ | FR-03 | Yêu cầu 100% trên toàn lô |
| V6 | Tiêu chí so thiết kế máy với thiết kế chuẩn | FR-04 | Chấm theo `canonical_design.md` mục 6 |
| V7 | Bộ 20 tình huống mơ hồ/rõ ràng chưa có | FR-05 | Tuần sau, thuộc `eval/golden/` |
| V8 | Đổi kiểu có bao gồm đổi cách viết (`10-20` thành `10-20%`) không | FR-17 | Quy định rõ: đổi cách viết là đổi kiểu |
| V9 | Lượt chạy đầu có phải đạt đúng số dòng mart kỳ vọng khi chưa duyệt C09 | FR-07 | Không kiểm tra số dòng `fact_vle_daily` cho tới khi duyệt Q1 |
