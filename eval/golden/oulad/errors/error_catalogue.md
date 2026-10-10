# OULAD — Danh mục lỗi tiêm (Error Catalogue) v0.1

**Trạng thái:** `DRAFT`, Deliverable F, Tuần 1. Gồm taxonomy và 25 lỗi mẫu đại diện, cộng 11 ca đối chứng. Chưa tiêm lỗi vào dữ liệu thật và chưa chạy hệ thống DataForge; mọi giá trị kỳ vọng được tính từ `metadata/profile_report.json` (lô OULAD gốc) và chưa được kiểm chứng bằng cách tiêm thật.
**Dữ liệu máy đọc được:** `errors/error_catalogue.csv` (cùng nội dung, UTF-8 có BOM để mở bằng Excel).
**Liên kết:** `model/canonical_design.md` (ràng buộc R01 đến R11, quan sát A1 đến A10, quy tắc làm sạch C01 đến C15).

## 1. Mục tiêu

Đặc tả DataForge đo chất lượng bộ test bằng hai tỉ lệ: tỉ lệ pass trên dữ liệu sạch và tỉ lệ bắt được lỗi khi tiêm lỗi có chủ đích. Một bộ test rỗng cũng pass hết trên dữ liệu sạch, nên chỉ riêng tỉ lệ pass không chứng minh được gì. Danh mục này định nghĩa trước **lỗi nào được tiêm, tiêm thế nào, hệ thống phải phát hiện gì và phải làm gì**, để việc chấm điểm không phụ thuộc cảm tính.

Danh mục cũng có **ca đối chứng** (mục 6): những điều bất thường có sẵn trong OULAD gốc mà hệ thống **không được** coi là lỗi. Nếu thiếu các ca này, một hệ thống chặn mọi thứ bất thường sẽ đạt 100% tỉ lệ bắt lỗi nhưng làm gãy pipeline trên dữ liệu hợp lệ.

## 2. Taxonomy 12 nhóm

| Nhóm | Định nghĩa | Lỗi mẫu | Số lỗi mẫu |
|---|---|---|---|
| Missing values | Giá trị thiếu ở cột không phải khóa | E01, E02 | 2 |
| Unexpected null | Giá trị thiếu ở cột khóa hoặc cột bắt buộc | E03, E04 | 2 |
| Duplicate | Dòng trùng hoàn toàn ở bảng không có khóa duy nhất | E25 | 1 |
| Duplicate PK | Khóa chính trùng (giống hệt hoặc xung đột nội dung) | E05, E06 | 2 |
| Invalid FK | Khóa ngoại trỏ tới bản ghi không tồn tại | E07, E08 | 2 |
| Broken relationship | Mất bản ghi cha làm hỏng quan hệ hàng loạt | E09 | 1 |
| Type mismatch | Kiểu giá trị không đúng với cột | E10, E11 | 2 |
| Invalid date | Giá trị ngày/số ngày không hợp lệ hoặc vô lý về thứ tự | E12, E13 | 2 |
| Outlier | Giá trị ngoài miền hợp lý hoặc cực đoan | E14, E15, E16 | 3 |
| Ambiguous column | Tên cột không đủ nghĩa để thiết kế chắc chắn | E17, E18 | 2 |
| Inconsistent category | Giá trị phân loại viết khác nhau hoặc xuất hiện giá trị mới | E19, E20, E21 | 3 |
| Schema drift | Lô mới đổi cấu trúc (thêm, đổi tên, bỏ cột) | E22, E23, E24 | 3 |

### 2.1 Liên hệ với 6 loại lỗi của `eval/fault_injection.py`

Bản đồ codebase ghi `fault_injection.py` có sẵn danh sách 6 loại lỗi. Danh mục này phủ đủ 6 loại và mở rộng thêm.

| Loại trong `fault_injection.py` | Giá trị `fault_class` | Lỗi mẫu |
|---|---|---|
| Khóa rỗng | `key_null` | E03, E04 |
| Khóa trùng | `key_duplicate` | E05, E06, E25 |
| Bản ghi mồ côi | `orphan_record` | E07, E08, E09 |
| Trạng thái lạ | `unexpected_status` | E19, E20, E21 |
| Ngày sai | `invalid_date` | E12, E13 |
| Số tiền âm | `negative_amount` (OULAD không có cột tiền; dùng số click không dương) | E16 |
| Ngoài 6 loại | `outside_core_six` | E01, E02, E10, E11, E14, E15, E17, E18, E22, E23, E24 |

## 3. Mã hành vi kỳ vọng và mức nghiêm trọng

**Các mã hành vi dưới đây là ĐỀ XUẤT.** Đặc tả nêu rõ "dòng thiếu khóa bị cách ly hay làm dừng pipeline" là một quyết định thiết kế cần duyệt ở Cổng 1; vì vậy hành vi kỳ vọng trong bảng phụ thuộc vào chính sách mà nhóm sẽ duyệt.

| Mã | Hành vi | Căn cứ trong đặc tả |
|---|---|---|
| **Q** | Cách ly dòng lỗi ở silver kèm lý do, báo số lượng; phần còn lại tiếp tục | "dòng lỗi bị cách ly kèm lý do và báo cáo số lượng" |
| **S** | Dừng pipeline, không công bố, báo cụ thể vì sao | "test fail thì dừng và báo, không công bố dữ liệu sai"; "lô mới đổi schema thì dừng và hỏi Engineer" |
| **W** | Cảnh báo và tiếp tục; không cách ly | Quan sát thống kê chỉ để đề xuất, không thành luật chặn |
| **H** | Hỏi lại Engineer và dừng chờ trả lời | FR-05 |
| **A** | Chấp nhận; không phản ứng | Dùng cho ca đối chứng |

| Mức | Nghĩa |
|---|---|
| Critical | Dữ liệu sai hoặc thiếu lọt vào mart và dashboard nếu không bắt |
| High | Làm sai một số chỉ số quan trọng nếu không bắt |
| Medium | Làm lệch chỉ số hoặc gây nhập nhằng, có thể phát hiện bằng cảnh báo |
| Low | Ảnh hưởng nhỏ, chủ yếu để theo dõi |

Phân bố theo mã hành vi của 25 lỗi mẫu: Q = 11, S = 5, W = 7, H = 2. Theo mức: Critical = 3, High = 11, Medium = 8, Low = 3.

## 4. Quy tắc tiêm lỗi

1. **Không bao giờ sửa `raw/`.** Lỗi được tạo từ bản sao hoặc từ đặc tả tiêm áp lên bản sao tạm.
2. **Một lỗi mỗi bản sao.** Để biết chính xác lỗi nào gây ra phát hiện nào. Ca gộp nhiều lỗi (kịch bản hỗn hợp) làm sau.
3. **Tất định.** Chọn dòng theo thứ tự băm cố định của khóa kèm một giá trị seed ghi trong cấu hình (đề xuất seed = 20261008), không phụ thuộc thứ tự dòng trong file.
4. **Lưu đặc tả, không lưu bản sao lớn.** `studentVle.csv` nặng khoảng 433 MiB; không commit các bản sao đã tiêm. Lưu đặc tả tiêm (bảng, cột, số dòng, seed) và tập khóa của các dòng đã tiêm để đối chiếu.
5. **Ghi lại tập dòng đã tiêm** (danh sách khóa) làm đáp án để so với tập dòng hệ thống báo.
6. **Số kỳ vọng được đối chiếu bằng cách chạy lại script profiling** trên bản sao đã tiêm và tính chênh lệch với baseline trong `profile_report.json`.

## 5. Danh mục lỗi mẫu (25 lỗi)

| ID | Bảng.Cột | Nhóm | Mô tả | Cách tiêm | Phát hiện kỳ vọng | Hành vi | Mức | FR | Trạng thái |
|---|---|---|---|---|---|---|---|---|---|
| E01 | `studentInfo`.gender | Missing values | Giá trị giới tính bị bỏ trống ở một số dòng | Chọn 100 dòng theo thứ tự băm cố định, đặt gender thành chuỗi rỗng | Hồ sơ báo null_like_rate của gender tăng từ 0% lên 0.3068% (100 dòng). Không có ràng buộc đã duyệt về gender nên không có test nào fail | **W**: Cảnh báo tăng tỉ lệ thiếu; tiếp tục chạy; không cách ly | Low | FR-02 | Draft |
| E02 | `studentAssessment`.score | Missing values | Điểm bị bỏ trống thêm ở một số lượt nộp | Chọn 200 dòng có score không rỗng, đặt score thành chuỗi rỗng | null_like_rows của score tăng từ 173 lên 373 (0.2145%). Điểm trung bình (M11) tính trên mẫu nhỏ hơn 200 dòng | **W**: Cảnh báo; tiếp tục; trung bình bỏ qua NULL, số lượt nộp (M10) không đổi | Low | FR-02 | Draft |
| E03 | `studentInfo`.id_student | Unexpected null | Mã sinh viên rỗng ở các dòng của bảng khóa chính ghép | Chọn 50 dòng, đặt id_student thành chuỗi rỗng | rows_with_null_like_key_part của khóa 3 cột tăng từ 0 lên 50 (0.1534%); ràng buộc R01 và R11 fail với đúng 50 dòng | **Q**: Cách ly 50 dòng ở silver với lý do null_key; báo số lượng; mart không chứa 50 dòng này | High | FR-08, FR-07 | Draft |
| E04 | `studentAssessment`.id_assessment | Unexpected null | Mã bài đánh giá rỗng ở các lượt nộp | Chọn 50 dòng, đặt id_assessment thành chuỗi rỗng | R11 fail (50 dòng khóa rỗng); đồng thời R02 báo 50 dòng mồ côi khi nối sang assessments | **Q**: Cách ly 50 dòng với lý do null_key; không đếm hai lần giữa hai ràng buộc | High | FR-08, FR-07 | Draft |
| E05 | `studentInfo`.(khóa 3 cột) | Duplicate PK | Thêm các dòng sao chép nguyên văn dòng đã có | Chọn 50 dòng, thêm 50 bản sao giống hệt vào cuối bảng | rows = 32643; distinct_keys = 32593; uniqueness_pct = 99.8468%; duplicate_key_groups = 50; rows_in_duplicate_groups = 100; duplicate_full_rows = 50 | **Q**: Giữ một bản mỗi khóa; cách ly 50 bản dư với lý do duplicate_key; mart có đúng 32.593 dòng enrollment | High | FR-03, FR-08, FR-16 | Draft |
| E06 | `assessments`.id_assessment | Duplicate PK | Hai bài đánh giá khác nhau dùng chung một mã, nội dung xung đột | Chọn 2 dòng, thêm 2 dòng mới có id_assessment trùng dòng gốc nhưng weight khác | R01 fail: duplicate_key_groups = 2, rows_in_duplicate_groups = 4; các dòng trong nhóm KHÔNG giống hệt nhau (xung đột nội dung) | **S**: Dừng pipeline, không công bố; yêu cầu Engineer quyết định giữ dòng nào (không tự chọn) | Critical | FR-03, FR-08, FR-13 | Draft |
| E07 | `studentRegistration`.id_student | Invalid FK | Đăng ký của sinh viên không tồn tại trong studentInfo | Chọn 100 dòng, thay id_student bằng giá trị lớn hơn max hiện có (2.716.795) và không tồn tại trong studentInfo | orphan_rows = 100 theo quan hệ registration → info; đồng thời 100 enrollment của studentInfo mất bản ghi đăng ký (student_info_without_registration = 100); R02 và R03 fail | **Q**: Cách ly 100 dòng mồ côi và 100 enrollment thiếu đăng ký; báo cả hai số | High | FR-03, FR-08, FR-14 | Draft |
| E08 | `studentVle`.id_site | Invalid FK | Click ghi nhận trên học liệu không tồn tại | Chọn 1.000 dòng, thay id_site bằng giá trị không có trong vle | orphan_rows = 1000 theo quan hệ studentVle → vle; match_rate_pct giảm từ 100% xuống 99.9906%; R02 fail | **Q**: Cách ly 1.000 dòng với lý do orphan_site; tổng click mart giảm đúng bằng tổng sum_click của 1.000 dòng này | High | FR-03, FR-08 | Draft |
| E09 | `courses`.(khóa 2 cột) | Broken relationship | Xóa module-presentation làm mọi bảng con mất cha | Xóa 2 dòng của module AAA khỏi courses (2013J và 2014J) | Tối thiểu: assessments mồ côi 12 dòng; studentInfo 748 dòng; studentRegistration 748 dòng; số dòng của vle đo khi tiêm. R02 fail ở nhiều quan hệ | **S**: Dừng pipeline; báo danh sách bảng con bị ảnh hưởng; không cách ly hàng loạt hàng trăm nghìn dòng một cách im lặng | Critical | FR-03, FR-08, FR-13 | Draft |
| E10 | `studentInfo`.studied_credits | Type mismatch | Giá trị số bị thay bằng chữ | Chọn 50 dòng, đặt studied_credits thành chuỗi 'sixty' | inferred_type của studied_credits đổi từ integer sang text; 50 dòng không ép kiểu được số nguyên | **Q**: Cách ly 50 dòng với lý do type_cast; báo số lượng; không ép bừa thành 0 hay NULL | High | FR-02, FR-07 | Draft |
| E11 | `studentAssessment`.score | Type mismatch | Điểm viết theo dấu phẩy thập phân thay cho dấu chấm | Chọn 30 dòng có điểm, đặt score thành dạng '75,5' | inferred_type của score đổi sang text; 30 dòng không ép được kiểu số | **Q**: Cách ly 30 dòng với lý do type_cast (định dạng số); không tự thay dấu phẩy thành dấu chấm khi chưa có quy tắc đã duyệt | Medium | FR-02, FR-07 | Draft |
| E12 | `studentRegistration`.date_registration | Invalid date | Cột số ngày tương đối chứa ngày lịch | Chọn 50 dòng có giá trị, đặt date_registration thành '2013-10-01' | inferred_type của date_registration đổi từ integer sang text; 50 dòng không ép kiểu được số ngày | **Q**: Cách ly 50 dòng với lý do invalid_date_offset | Medium | FR-02, FR-07 | Draft |
| E13 | `studentRegistration`.date_unregistration | Invalid date | Ngày hủy đăng ký sớm hơn ngày đăng ký | Chọn 100 dòng có cả hai ngày, đặt date_unregistration = date_registration - 10 | unregistered_before_registered tăng từ 0 lên 100; R07 fail với đúng 100 dòng | **Q**: Cách ly 100 dòng với lý do unregistered_before_registered | Medium | FR-08 | Draft |
| E14 | `studentAssessment`.score | Outlier | Điểm vượt khoảng cho phép [0, 100] | Chọn 50 dòng, đặt score = 150 | score_outside_0_100 tăng từ 0 lên 50; R05 fail với đúng 50 dòng | **Q**: Cách ly 50 dòng với lý do score_out_of_range; điểm trung bình không bị kéo lên | High | FR-08 | Draft |
| E15 | `studentVle`.sum_click | Outlier | Số click lớn bất thường nhưng vẫn là số hợp lệ | Chọn 20 dòng, đặt sum_click = 10000000 | numeric_max của sum_click nhảy từ 6.977 lên 10.000.000; tổng click (M14) tăng khoảng 200 triệu; KHÔNG có ràng buộc đã duyệt về cận trên nên không có test fail | **W**: Cảnh báo ngoại lệ so với lô trước; tiếp tục; không cách ly (không có căn cứ coi là sai) | Medium | FR-02 | Draft |
| E16 | `studentVle`.sum_click | Outlier | Số click bằng 0 hoặc âm | Chọn 30 dòng: 15 dòng đặt sum_click = 0 và 15 dòng đặt sum_click = -5 | clicks_missing_or_not_positive tăng từ 0 lên 30; R06 fail với đúng 30 dòng | **Q**: Cách ly 30 dòng với lý do non_positive_click | High | FR-08 | Draft |
| E17 | `studentVle`.sum_click (đổi tên thành amount) | Ambiguous column | Tên cột bị đổi thành tên chung chung, mất ngữ nghĩa | Đổi tên cột sum_click thành amount ở toàn bộ file; giữ nguyên giá trị | Modeler không thể xác định amount là số tiền, số lượng hay số lần; phân bố là số nguyên dương, lệch phải (1 đến 6.977). Output phải chứa questions, không chứa design | **H**: Hỏi lại Engineer, dừng chờ trả lời; không tự đoán nghĩa | High | FR-05, FR-04 | Draft |
| E18 | `studentAssessment`.score (đổi tên thành value) | Ambiguous column | Tên cột bị đổi thành value | Đổi tên cột score thành value ở toàn bộ file; giữ nguyên giá trị | Modeler phải hỏi value là điểm, điểm có trọng số hay thang khác; miền 0 đến 100 gợi ý điểm nhưng không đủ để kết luận | **H**: Hỏi lại Engineer; không đặt grain hay chỉ số điểm khi chưa được trả lời | Medium | FR-05, FR-04 | Draft |
| E19 | `studentInfo`.final_result | Inconsistent category | Cùng một giá trị viết khác nhau (hoa/thường, khoảng trắng) | Chọn 60 dòng có 'Pass': 30 dòng đổi thành 'pass', 30 dòng đổi thành ' Pass ' | distinct_values của final_result tăng từ 4 lên 6; rows_with_padding_whitespace = 30; số dòng 'Pass' đúng giảm từ 12.361 xuống 12.301 | **W**: Cảnh báo giá trị phân loại lạ; không tự chuẩn hóa nếu chưa có quy tắc đã duyệt; chỉ số tỉ lệ đạt (M06, M07) bị lệch nếu để nguyên | Medium | FR-02, FR-08 | Draft |
| E20 | `studentInfo`.final_result | Inconsistent category | Xuất hiện giá trị trạng thái chưa từng có | Chọn 20 dòng, đặt final_result = 'Deferred' | distinct_values tăng từ 4 lên 5; giá trị mới 'Deferred' đúng 20 dòng; ràng buộc miền giá trị ở mức cảnh báo | **W**: Cảnh báo giá trị mới và yêu cầu Engineer xác nhận; không dừng, không loại: một giá trị mới có thể hợp lệ ở lô sau | Medium | FR-08, FR-17 | Draft |
| E21 | `studentInfo`.imd_band | Inconsistent category | Một nhóm thiếu ký tự %, giống lỗi đã có ở nhóm 10-20 | Chọn 100 dòng có '20-30%', đổi thành '20-30' | distinct_values của imd_band tăng thêm 1 so với baseline; hai cách viết cùng nhóm cùng tồn tại | **W**: Cảnh báo biến thể cách viết; quy tắc chuẩn hóa chỉ áp dụng cho nhóm đã duyệt (10-20), nên nhóm này cần quyết định mới | Low | FR-02, FR-08 | Draft |
| E22 | `studentInfo`.(thêm cột ethnicity) | Schema drift | Lô mới có thêm một cột | Thêm cột ethnicity (rỗng) vào header và mọi dòng | So sánh header với lô đã duyệt: thừa 1 cột ethnicity | **S**: Dừng trước bước nạp; báo tên cột mới; không tự áp dụng thay đổi schema | High | FR-17, FR-16 | Draft |
| E23 | `studentInfo`.gender (đổi tên thành sex) | Schema drift | Lô mới đổi tên một cột | Đổi tên cột gender thành sex ở toàn bộ file | So sánh header: thiếu gender, thừa sex | **S**: Dừng trước bước nạp; không tự ánh xạ sex sang gender | High | FR-17, FR-16 | Draft |
| E24 | `studentVle`.(bỏ cột sum_click) | Schema drift | Lô mới thiếu một cột quan trọng | Xóa cột sum_click khỏi header và mọi dòng | So sánh header: thiếu sum_click; mọi chỉ số click (M14 đến M18) không tính được | **S**: Dừng trước bước nạp; báo cột thiếu | Critical | FR-17, FR-16 | Draft |
| E25 | `studentVle`.(dòng trùng hoàn toàn) | Duplicate | Thêm dòng sao chép nguyên văn vào bảng không có khóa duy nhất | Chọn 1.000 dòng, thêm 1.000 bản sao giống hệt vào cuối bảng | duplicate_full_rows tăng từ 787.170 lên 788.170 (+1.000). Vì OULAD gốc đã có 787.170 dòng trùng được chấp nhận (NC01) nên hệ thống KHÔNG thể phân biệt 1.000 dòng mới với dòng trùng tự nhiên bằng test đã duyệt; chỉ phát hiện được qua so sánh thống kê với lô trước | **W**: Cảnh báo tăng đột biến số dòng trùng so với lô trước; tiếp tục; không cách ly (ca giới hạn: lỗi không thể bắt bằng test) | Medium | FR-02, FR-03 | Draft |

Các lỗi E01, E02, E15, E19 đến E21 và E25 có hành vi **W** (cảnh báo). Chúng **không** được kỳ vọng bị bắt bởi test bắt buộc, vì chưa có ràng buộc đã duyệt tương ứng; mục tiêu là hệ thống báo qua hồ sơ thống kê. Hai lỗi E17 và E18 có hành vi **H**: kỳ vọng là câu hỏi của Modeler, không phải test. Ba lỗi E22 đến E24 do kiểm tra cấu trúc của lô mới (FR-17).

## 6. Ca đối chứng (negative controls, 11 ca)

Những ca này **không phải lỗi**: hệ thống phải chấp nhận. Chúng bảo vệ bộ test khỏi việc chặn nhầm dữ liệu hợp lệ.

| ID | Bảng | Mô tả | Cách thực hiện | Quan sát kỳ vọng | Hành vi | FR | Nguồn |
|---|---|---|---|---|---|---|---|
| NC01 | studentVle | Dòng trùng khóa có sẵn trong OULAD gốc (A1) | Không tiêm gì: dùng dữ liệu gốc | Khóa 5 cột duy nhất 79,39%; 1.614.505 nhóm trùng. Hệ thống không được coi đây là lỗi | **A**: Không sinh test unique cho khóa này; không cách ly; không dừng; hỏi Engineer về cộng dồn (Q1) | FR-08, FR-05 | Draft |
| NC02 | assessments | Tổng weight không bằng 100 ở một số presentation (A2, A3) | Không tiêm gì: dùng dữ liệu gốc | Tổng không-Exam bằng 0 ở GGG; tổng Exam bằng 200 ở CCC 2014B và 2014J | **A**: Không sinh test kiểm tổng weight; không cách ly; không dừng | FR-08 | Draft |
| NC03 | studentInfo | Withdrawn không khớp với date_unregistration (A4) | Không tiêm gì: dùng dữ liệu gốc | 93 dòng Withdrawn không có ngày hủy; 9 dòng Fail có ngày hủy | **A**: Không sinh test liên bảng giữa hai cột này; không cách ly | FR-08 | Draft |
| NC04 | studentAssessment | Nộp trước ngày bắt đầu hoặc sau khi hết khóa (A5) | Không tiêm gì: dùng dữ liệu gốc | 2.057 lượt nộp có ngày < 0; 85 lượt nộp sau khi hết khóa | **A**: Không chặn khoảng ngày nộp; không cách ly | FR-08 | Draft |
| NC05 | studentInfo | id_student không duy nhất riêng lẻ (A6) | Không tiêm gì: dùng dữ liệu gốc | 28.785 giá trị khác nhau trên 32.593 dòng | **A**: Không đề xuất id_student làm khóa chính; khóa 3 cột được đề xuất | FR-03 | Draft |
| NC06 | assessments, vle, studentInfo | Bài không có lượt nộp, học liệu không có click, enrollment không có click (A7, A8) | Không tiêm gì: dùng dữ liệu gốc | 18 bài Exam không có lượt nộp; 96 học liệu và 3.365 enrollment không có click | **A**: Không coi là lỗi khóa ngoại; không cách ly | FR-03 | Draft |
| NC07 | nhiều bảng | Cột thiếu có sẵn trong dữ liệu gốc (A9, A10) | Không tiêm gì: dùng dữ liệu gốc | imd_band 1.111; date_registration 45; assessments.date 11; score 173; week_from và week_to 5.243 dòng | **A**: Giữ NULL; không cách ly; không dừng; không tự điền | FR-02, FR-08 | Draft |
| NC08 | studentInfo | Nhóm 10-20 thiếu % có sẵn trong dữ liệu gốc (C02) | Không tiêm gì: dùng dữ liệu gốc | 3.516 dòng viết '10-20' trong khi 9 nhóm khác có '%' | **A**: Áp dụng chuẩn hóa C02 nếu đã được duyệt; nếu chưa duyệt thì cảnh báo; không dừng | FR-08 | Draft |
| NC09 | mọi bảng | Đổi thứ tự cột trong file nhưng giữ nguyên tên cột | Hoán đổi vị trí hai cột bất kỳ ở header và mọi dòng | So sánh header theo tên cột: không có cột thừa hoặc thiếu | **A**: Không dừng; đọc theo tên cột. Cần xác nhận với người sở hữu module nạp dữ liệu | FR-17, FR-01 | Draft |
| NC10 | mọi bảng | File dùng LF thay cho CRLF | Chuyển kết thúc dòng của file từ CRLF sang LF | Nội dung dữ liệu không đổi; SHA-256 của file đổi | **A**: Không dừng; không cách ly. Số dòng và giá trị giữ nguyên | FR-01 | Draft |
| NC11 | mọi bảng | File có dấu BOM UTF-8 ở đầu | Thêm 3 byte BOM UTF-8 vào đầu file | Tên cột đầu tiên không được đổi thành chuỗi có ký tự lạ | **A**: Đọc đúng tên cột đầu; không dừng | FR-01 | Draft |

**Điều kiện đạt chung cho mọi ca đối chứng:** số dòng bị cách ly = 0, số lần dừng pipeline = 0, và không có test bắt buộc nào được sinh ra từ các quan sát A1 đến A10.

## 7. Thước đo

| Thước đo | Định nghĩa | Ghi chú |
|---|---|---|
| Tỉ lệ bắt đúng loại | Số lỗi mẫu mà hệ thống phát hiện đúng nhóm / tổng số lỗi mẫu; tính riêng cho kênh test (Q, S), kênh cảnh báo (W), kênh hỏi lại (H) | Báo cáo theo nhóm taxonomy và theo mức nghiêm trọng |
| Tỉ lệ bắt đúng số lượng | Số lỗi mẫu mà số dòng hệ thống báo bằng đúng số dòng đã tiêm / tổng số lỗi mẫu có số dòng xác định | E09 chỉ so các bảng đã có số tối thiểu |
| Tỉ lệ chặn nhầm | Số ca đối chứng mà hệ thống cách ly, dừng hoặc sinh test sai / 11 | Mục tiêu 0 |
| Tỉ lệ pass trên dữ liệu sạch | Tỉ lệ test đã duyệt đạt trên OULAD gốc | Mục tiêu 100% theo `canonical_design.md` mục 7 |

**Ngưỡng đạt (ĐỀ XUẤT, chờ nhóm chốt):** 100% lỗi Critical và High phải được phát hiện đúng loại; 0 ca đối chứng bị chặn nhầm. Chưa đề xuất ngưỡng cho mức Medium và Low vì chưa có dữ liệu so sánh.

## 8. Những giới hạn đã biết

- **E25 là ca giới hạn có chủ ý.** Vì OULAD gốc đã chứa 787.170 dòng trùng hoàn toàn ở `studentVle` được chấp nhận (NC01), một dòng sao chép thêm không thể phân biệt bằng test đã duyệt. Danh mục ghi nhận điều này thay vì giả vờ hệ thống bắt được.
- **Một số lỗi ở mức W chỉ bắt được khi có lô trước để so sánh** (E15, E19 đến E21, E25). Lô đầu tiên không có baseline để so.
- **Các giá trị kỳ vọng chưa được kiểm chứng bằng tiêm thật.** Chúng là dự đoán từ số đo ở `profile_report.json`; khi tiêm thật có thể lệch (ví dụ E09 còn thiếu số dòng của `vle`).

## 9. Việc còn lại và câu hỏi mở

| ID | Việc / câu hỏi | Ai | Ghi chú |
|---|---|---|---|
| F1 | Duyệt chính sách Q / S / W (dòng lỗi thì cách ly hay dừng; ngưỡng bao nhiêu dòng thì dừng) | Nhóm (Cổng 1) | Đổi chính sách thì phải đổi cột hành vi |
| F2 | Xác nhận NC09 đến NC11 (đổi thứ tự cột, LF thay CRLF, BOM) là chấp nhận | Người sở hữu module nạp dữ liệu | Đang ghi "Needs decision" |
| F3 | Ai hiện thực `eval/fault_injection.py` từ danh mục này | Nhóm xác định | Tuấn chỉ cung cấp danh mục và đặc tả tiêm |
| F4 | Tiêm thật và đối chiếu số kỳ vọng | Tuấn (kèm người viết fault_injection) | Chuyển trạng thái từ Draft sang Approved |
| F5 | Tạo danh mục tương tự cho Olist và TPC-H khi hai dataset được xác nhận | Tuấn | Tái dùng cấu trúc này |

## 10. Tự kiểm tra

| Câu hỏi | Kết quả |
|---|---|
| Đủ 12 nhóm taxonomy chưa? | Đủ; mỗi nhóm có ít nhất một lỗi mẫu |
| Mỗi lỗi có đủ 12 trường trong yêu cầu chưa? | Đủ trong CSV: ID, dataset, bảng, cột, loại lỗi, mô tả, cách tiêm, phát hiện kỳ vọng, hành vi kỳ vọng, mức, FR, trạng thái |
| Có bịa số liệu không? | Mọi số đều lấy từ `profile_report.json`, hoặc là số chọn khi tiêm (50, 100, ...) |
| Có số nào chưa chắc? | E09: số dòng `vle` chưa biết; được ghi "đo khi tiêm" |
| Có mâu thuẫn với thiết kế chuẩn không? | Hành vi dựa vào R01 đến R11 và A1 đến A10 của `canonical_design.md` |
