# OULAD — Metric và yêu cầu dashboard v0.1

**Trạng thái:** `DRAFT`, chỉ ở mức thiết kế (chưa triển khai Metabase). Đây là phần 4.6 và 4.7 của Task 4.
**Căn cứ:** `model/canonical_design.md` (tên bảng đích, grain, quyết định C09) và `metadata/profile_report.json`.

## 0. Quy ước

- Tên bảng/cột trong cột "Nguồn" là bảng đích của thiết kế đề xuất (`dim_*`, `fact_*`). Nếu Modeler chọn thiết kế khác, giữ nguyên định nghĩa, đổi tên nguồn.
- **Giá trị tham chiếu** là số tính trực tiếp từ `profile_report.json` bản chạy đầy đủ (lô OULAD gốc, ngày 08/10/2026, DuckDB 1.5.5). Giá trị tham chiếu chỉ là mốc kiểm tra nhanh, không thay thế bảng kết quả chuẩn (`expected/`, làm ở tuần sau).
- Mọi cột `date*` là số ngày tương đối, không phải ngày lịch. Quy ước dấu: giá trị âm là trước ngày bắt đầu presentation (SUY LUẬN, chưa đối chiếu tài liệu gốc).
- Mọi metric nào phụ thuộc quyết định chưa duyệt đều ghi rõ.

---

## 1. Định nghĩa metric (mục 4.6)

| ID | Tên | Định nghĩa và công thức | Grain | Nguồn | Bộ lọc | Ý nghĩa nghiệp vụ | Giá trị tham chiếu |
|---|---|---|---|---|---|---|---|
| M01 | `enrollment_count` | Số lượt học: `COUNT(*)` | enrollment | `dim_enrollment` | không | Quy mô nhóm sinh viên theo module-presentation | 32.593 |
| M02 | `student_count` | Số sinh viên khác nhau: `COUNT(DISTINCT id_student)` | sinh viên | `dim_enrollment.id_student` | không | Một sinh viên có thể học nhiều lượt nên khác M01 | 28.785 |
| M03 | `repeat_student_rate` | Số sinh viên có từ 2 lượt học trở lên chia M02 | sinh viên | `dim_enrollment` | không | Mức độ sinh viên quay lại học tiếp | 3.538 / 28.785 = 12,29% |
| M04 | `withdrawal_rate` | `COUNT(final_result = 'Withdrawn') / COUNT(*)` | enrollment | `dim_enrollment.final_result` | không | Tỉ lệ rút học theo kết quả cuối | 10.156 / 32.593 = 31,16% |
| M05 | `fail_rate` | `COUNT(final_result = 'Fail') / COUNT(*)` | enrollment | `dim_enrollment.final_result` | không | Tỉ lệ không đạt | 7.052 / 32.593 = 21,64% |
| M06 | `pass_rate_all` | `COUNT(final_result IN ('Pass','Distinction')) / COUNT(*)`. Mẫu số là mọi enrollment | enrollment | `dim_enrollment.final_result` | không | Tỉ lệ đạt tính cả người rút học | 15.385 / 32.593 = 47,20% |
| M07 | `pass_rate_completers` | `COUNT(final_result IN ('Pass','Distinction')) / COUNT(final_result <> 'Withdrawn')`. Mẫu số loại người rút học | enrollment | `dim_enrollment.final_result` | `final_result <> 'Withdrawn'` ở mẫu số | Tỉ lệ đạt trong số người học hết khóa | 15.385 / 22.437 = 68,57% |
| M08 | `distinction_rate` | `COUNT(final_result = 'Distinction') / COUNT(*)` | enrollment | `dim_enrollment.final_result` | không | Tỉ lệ đạt loại xuất sắc | 3.024 / 32.593 = 9,28% |
| M09 | `unregistration_rate` | `COUNT(date_unregistration IS NOT NULL) / COUNT(*)` | enrollment | `dim_enrollment.date_unregistration` | không | Tỉ lệ có sự kiện hủy đăng ký. Khác M04 ở 102 dòng (xem C13) | 10.072 / 32.593 = 30,90% |
| M10 | `submission_count` | `COUNT(*)` lượt nộp | lượt nộp | `fact_assessment_submission` | không | Khối lượng bài nộp | 173.912 |
| M11 | `avg_score` | `AVG(score)`, bỏ qua `score` rỗng | lượt nộp | `fact_assessment_submission.score` | `score IS NOT NULL` | Điểm trung bình. **Cần hỏi (Q3):** có tính điểm banked không | 75,80 (bỏ 173 dòng rỗng) |
| M12 | `avg_score_excl_banked` | Như M11 nhưng thêm điều kiện `is_banked = 0` | lượt nộp | `fact_assessment_submission` | `score IS NOT NULL AND is_banked = 0` | Điểm trung bình chỉ tính điểm làm trong lần học này | 75,82 (`is_banked = 0`) |
| M13 | `late_submission_rate` | `COUNT(date_submitted > deadline) / COUNT(deadline IS NOT NULL)` với `deadline = dim_assessment.date` | lượt nộp | `fact_assessment_submission.date_submitted`, `dim_assessment.date` | `dim_assessment.date IS NOT NULL` | Tỉ lệ nộp sau hạn. Bài không có hạn (11 bài Exam) bị loại | 28,83% (49.318 / 171.047 lượt có hạn) |
| M14 | `total_clicks` | `SUM(sum_click)` | ngày × học liệu × enrollment | `fact_vle_daily.sum_click` | không | Tổng tương tác trên VLE. **Phụ thuộc C09** (cộng dồn dòng cùng khóa) | 39.605.099 |
| M15 | `active_enrollment_rate` | Số enrollment có ít nhất một dòng click chia M01 | enrollment | `fact_vle_daily`, `dim_enrollment` | không | Mức độ sinh viên có dùng VLE | 29.228 / 32.593 = 89,68% |
| M16 | `clicks_per_active_enrollment` | M14 chia số enrollment có click | enrollment | `fact_vle_daily` | không | Cường độ tương tác của người có dùng VLE. Mẫu số không gồm 3.365 enrollment không có click | 1.355,0 (39.605.099 / 29.228) |
| M17 | `unused_site_rate` | Số học liệu không có dòng click nào chia số học liệu | học liệu | `dim_vle_site`, `fact_vle_daily` | không | Tỉ lệ học liệu không được dùng | 96 / 6.364 = 1,51% |
| M18 | `pre_start_click_share` | `SUM(sum_click WHERE date < 0) / M14` | ngày × học liệu × enrollment | `fact_vle_daily` | không | Tỉ trọng tương tác trước khi khóa bắt đầu. Phụ thuộc quy ước dấu của `date` | 5,42% (2.147.947 / 39.605.099) |
| M19 | `avg_registration_lead_days` | `AVG(-date_registration)` bỏ qua rỗng | enrollment | `dim_enrollment.date_registration` | `date_registration IS NOT NULL` (loại 45 dòng) | Số ngày trung bình đăng ký trước ngày bắt đầu | chưa đo |

### Metric KHÔNG được định nghĩa

| Metric bị loại | Lý do (QUAN SÁT) |
|---|---|
| Điểm tổng kết có trọng số: `SUM(score * weight / 100)` | Tổng `weight` không nhất quán: không-Exam bằng 0 ở cả 3 presentation của GGG, Exam bằng 200 ở CCC 2014B và 2014J; 56 bài có `weight = 0`. Công thức cho kết quả không so sánh được giữa các module |
| Điểm thi trung bình toàn bộ như một chỉ số riêng | Chỉ 6/24 bài Exam có lượt nộp (18 bài không có lượt nộp); trung bình Exam chỉ phản ánh 6 bài, không đại diện cho mọi bài thi
| Số click mỗi ngày theo ngày lịch | Dữ liệu không có ngày lịch (C11) |
| Chỉ số theo từng sinh viên (`dim_student`) | `age_band` thay đổi giữa các lượt học ở 72/3.538 sinh viên (2,04%); các thuộc tính còn lại nhất quán. Vì vậy không tách `dim_student` |

### Điểm cần Cổng 1 chốt trước khi dùng metric

| Điểm | Metric bị ảnh hưởng |
|---|---|
| Mẫu số của tỉ lệ đạt (Q2) | M06 và M07 cho hai số khác nhau 47,20% và 68,57% |
| Tính điểm banked hay không (Q3) | M11 và M12 |
| Cộng dồn dòng `studentVle` cùng khóa (Q1, C09) | M14, M16, M18 |
| `final_result` hay `date_unregistration` quyết định "rút học" (C13) | M04 và M09, lệch 102 dòng |

---

## 2. Yêu cầu dashboard (mục 4.7)

**Ràng buộc kỹ thuật theo đặc tả bản đầu:** chỉ ba loại card: **KPI dạng số**, **biểu đồ đường**, **biểu đồ cột**. Mọi biểu đồ dưới đây thuộc một trong ba loại này; không có biểu đồ tròn, bản đồ hay bảng pivot.

**Cột "Kiểm tra" là tiêu chí nghiệm thu:** số trên biểu đồ phải khớp số đã đo; đây là cách phát hiện sai khi nối bảng.

### DB1. Tổng quan (KPI)

Bộ lọc chung: `code_module`, `code_presentation`.

| Mã | Tên | Loại | Business question | Bảng | Dimension | Measure | Aggregation | Insight kỳ vọng (câu hỏi cần trả lời) | Kiểm tra |
|---|---|---|---|---|---|---|---|---|---|
| K1 | Số lượt học | KPI | Quy mô dữ liệu là bao nhiêu? | `dim_enrollment` | không | M01 | COUNT | Không lọc: 32.593 | = 32.593 |
| K2 | Số sinh viên | KPI | Bao nhiêu sinh viên khác nhau? | `dim_enrollment` | không | M02 | COUNT DISTINCT | Khác K1 do sinh viên học lại | = 28.785 |
| K3 | Tỉ lệ rút học | KPI | Bao nhiêu phần trăm enrollment kết thúc là Withdrawn? | `dim_enrollment` | không | M04 | tỉ lệ | Mức rút học tổng thể | = 31,16% |
| K4 | Tỉ lệ đạt (không tính người rút) | KPI | Trong người học hết khóa, bao nhiêu đạt? | `dim_enrollment` | không | M07 | tỉ lệ | Chất lượng kết quả của người hoàn thành | = 68,57% |
| K5 | Số lượt nộp bài | KPI | Có bao nhiêu bài nộp? | `fact_assessment_submission` | không | M10 | COUNT | Khối lượng đánh giá | = 173.912 |
| K6 | Tổng click | KPI | Tổng mức tương tác trên VLE? | `fact_vle_daily` | không | M14 | SUM | Quy mô hoạt động học tập | = 39.605.099 |

### DB2. Kết quả học tập

Bộ lọc: `code_module`, `code_presentation`, `gender`, `age_band`, `disability`.

| Mã | Tên | Loại | Business question | Bảng | Dimension | Measure | Aggregation | Insight kỳ vọng | Kiểm tra |
|---|---|---|---|---|---|---|---|---|---|
| B1 | Phân bố kết quả cuối theo module | Cột | Mỗi module có cơ cấu Pass/Fail/Withdrawn/Distinction ra sao? | `dim_enrollment` | `code_module`, `final_result` | M01 | COUNT | Module nào có tỉ lệ rút học hoặc đạt khác biệt? | tổng các cột = 32.593; khớp: 748, 7.909, 4.434, 6.272, 2.934, 7.762, 2.534 (tổng 32.593); 28 nhóm module × kết quả |
| B2 | Tỉ lệ đạt (không tính người rút) theo module-presentation | Cột | Module-presentation nào có tỉ lệ đạt cao hay thấp? | `dim_enrollment` | `code_module`, `code_presentation` | M07 | tỉ lệ | So sánh 22 module-presentation | 22 cột |
| B3 | Tỉ lệ rút học theo module-presentation | Cột | Module-presentation nào mất nhiều người học nhất? | `dim_enrollment` | `code_module`, `code_presentation` | M04 | tỉ lệ | So sánh 22 module-presentation | 22 cột |
| B4 | Kết quả theo trình độ học vấn | Cột | Trình độ học vấn có liên hệ với kết quả cuối không? | `dim_enrollment` | `highest_education`, `final_result` | M01 | COUNT | Thứ tự các mức cần Cổng 1 duyệt | tổng = 32.593; 5 nhóm |
| B5 | Kết quả theo nhóm thiếu thốn (IMD) | Cột | Nhóm thiếu thốn có liên hệ với kết quả cuối không? | `dim_enrollment` | `imd_band`, `final_result` | M01 | COUNT | Nhóm "Không rõ" (1.111 dòng) hiển thị riêng, không bỏ | tổng = 32.593; 10 nhóm + "Không rõ"; nhóm `10-20%` đã chuẩn hóa (C02) |
| B6 | Kết quả theo số lần học trước | Cột | Học lại có liên hệ với kết quả không? | `dim_enrollment` | `num_of_prev_attempts`, `final_result` | M01 | COUNT | Phần lớn dữ liệu ở 0 lần trước (28.421 dòng) | tổng = 32.593 |

### DB3. Mức độ tương tác (VLE)

Bộ lọc: `code_module`, `code_presentation`, `activity_type`.

| Mã | Tên | Loại | Business question | Bảng | Dimension | Measure | Aggregation | Insight kỳ vọng | Kiểm tra |
|---|---|---|---|---|---|---|---|---|---|
| L1 | Click theo ngày tương đối | Đường | Tương tác thay đổi thế nào từ trước đến sau khi khóa bắt đầu? | `fact_vle_daily` | `date` (số ngày tương đối, từ -25 đến 269) | M14 | SUM | Có đỉnh theo thời điểm học kỳ không? | tổng toàn đường = tổng click bronze; 295 điểm khi không lọc |
| B7 | Click theo loại học liệu | Cột | Loại học liệu nào được dùng nhiều nhất? | `fact_vle_daily` ⋈ `dim_vle_site` | `activity_type` | M14 | SUM | Loại nào chiếm phần lớn click? | 20 nhóm; tổng = tổng click |
| B8 | Tỉ lệ enrollment có dùng VLE theo module-presentation | Cột | Module nào có nhiều sinh viên không bao giờ vào VLE? | `fact_vle_daily`, `dim_enrollment` | `code_module`, `code_presentation` | M15 | tỉ lệ | So sánh 22 module-presentation | tỉ lệ toàn bộ = 89,68% |
| B9 | Click bình quân mỗi enrollment có dùng VLE theo module | Cột | Cường độ tương tác khác nhau thế nào giữa các module? | `fact_vle_daily` | `code_module` | M16 | tỉ lệ | Module nào có cường độ cao nhất? | Tổng toàn bộ: 1.355,0 mỗi enrollment có click; chi tiết theo module chưa đo |

### DB4. Kết quả bài đánh giá

Bộ lọc: `code_module`, `code_presentation`, `assessment_type`.

| Mã | Tên | Loại | Business question | Bảng | Dimension | Measure | Aggregation | Insight kỳ vọng | Kiểm tra |
|---|---|---|---|---|---|---|---|---|---|
| B10 | Điểm trung bình theo loại bài | Cột | TMA, CMA, Exam khác nhau thế nào về điểm? | `fact_assessment_submission` ⋈ `dim_assessment` | `assessment_type` | M11 | AVG | Exam chỉ có lượt nộp ở 6/24 bài | 3 cột: CMA 81,03; Exam 65,57; TMA 72,56 |
| B11 | Điểm trung bình theo module | Cột | Module nào có điểm trung bình cao hay thấp? | `fact_assessment_submission` ⋈ `dim_assessment` | `code_module` | M11 | AVG | So sánh 7 module | 7 cột |
| L2 | Số lượt nộp theo ngày nộp | Đường | Bài nộp tập trung vào thời điểm nào? | `fact_assessment_submission` | `date_submitted` (từ -11 đến 608) | M10 | COUNT | Có đỉnh quanh hạn nộp không? | tổng = 173.912 |
| B12 | Tỉ lệ nộp muộn theo module | Cột | Module nào có nhiều bài nộp muộn nhất? | `fact_assessment_submission` ⋈ `dim_assessment` | `code_module` | M13 | tỉ lệ | Loại bài không có hạn | Tổng toàn bộ 28,83%; chi tiết theo module chưa đo |

### DB5. Giữ chân người học

Bộ lọc: `code_module`, `code_presentation`.

| Mã | Tên | Loại | Business question | Bảng | Dimension | Measure | Aggregation | Insight kỳ vọng | Kiểm tra |
|---|---|---|---|---|---|---|---|---|---|
| L3 | Số lượt hủy đăng ký theo ngày | Đường | Người học rút ở thời điểm nào của khóa? | `dim_enrollment` | `date_unregistration` (từ -365 đến 444) | M01 | COUNT | Có giai đoạn rút học tập trung không? | tổng = 10.072 |
| B13 | Tỉ lệ hủy đăng ký theo module-presentation | Cột | Module-presentation nào mất người học sớm? | `dim_enrollment` | `code_module`, `code_presentation` | M09 | tỉ lệ | So sánh 22 nhóm | toàn bộ = 30,90% |
| B14 | Số ngày đăng ký trước khi bắt đầu theo module | Cột | Người học đăng ký sớm bao nhiêu? | `dim_enrollment` | `code_module` | M19 | AVG | Loại 45 dòng thiếu | chưa đo |

### DB6. So sánh module và presentation

| Mã | Tên | Loại | Business question | Bảng | Dimension | Measure | Aggregation | Insight kỳ vọng | Kiểm tra |
|---|---|---|---|---|---|---|---|---|---|
| B15 | Số lượt học theo module-presentation | Cột | Quy mô từng module-presentation? | `dim_enrollment` | `code_module`, `code_presentation` | M01 | COUNT | Từ nhỏ nhất đến lớn nhất (tối đa 2.498) | 22 cột; tổng = 32.593 |
| L4 | Số lượt học theo presentation, mỗi đường một module | Đường | Quy mô thay đổi thế nào qua 2013B, 2013J, 2014B, 2014J? | `dim_enrollment` | `code_presentation` (thứ tự thời gian), chuỗi theo `code_module` | M01 | COUNT | Module nào tăng hoặc giảm? Một số module chỉ có 2 hoặc 3 presentation | 4 điểm tối đa mỗi đường; tổng = 32.593 |
| B16 | Số bài đánh giá và học liệu theo module | Cột | Module nào có nhiều học liệu và bài đánh giá? | `dim_assessment`, `dim_vle_site` | `code_module` | COUNT | COUNT | So sánh cấu trúc khóa học | tổng bài = 206; tổng học liệu = 6.364 |

### Lưu ý cho người triển khai dashboard

1. Nhóm `imd_band` rỗng hiển thị là "Không rõ", không bị loại; `10-20` phải được chuẩn hóa thành `10-20%` trước khi dựng (C02) kẻo xuất hiện thành hai nhóm.
2. Trục `date*` ghi rõ "số ngày so với ngày bắt đầu", không dùng nhãn ngày/tháng.
3. Sắp xếp thứ tự các nhóm có thứ bậc (`imd_band`, `highest_education`, `age_band`) cần quy tắc sắp xếp riêng; thứ tự `highest_education` chờ Cổng 1.
4. Mọi biểu đồ có cột "Kiểm tra" có thể viết thành truy vấn đối chiếu trực tiếp trên mart; làm ở tuần sau trong `expected/`.
5. Dashboard chỉ phục vụ đo lường chất lượng sinh ra của DataForge; việc dựng thật thuộc người sở hữu Metabase, ngoài phạm vi Tuấn.

## 3. Việc còn lại

| # | Việc | Điều kiện hoàn thành |
|---|---|---|
| 1 | (Xong) Điền giá trị tham chiếu từ bản chạy đầy đủ | Đã điền; cần Cổng 1 duyệt định nghĩa |
| 2 | Nhóm duyệt định nghĩa M06/M07, M11/M12, M14 | Mỗi cặp có quyết định dùng định nghĩa nào làm chuẩn |
| 3 | Người sở hữu Metabase xác nhận 3 loại card đủ cho 26 card trên | Có phản hồi |
