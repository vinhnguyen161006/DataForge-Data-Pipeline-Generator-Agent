# OULAD — Báo cáo chất lượng dữ liệu (v0.2)

**Nguồn số liệu:** `profile_report.json` và `source_manifest.json`, chạy ngày 06/10/2026 với DuckDB 1.5.5, đọc toàn bộ 7 file (không giới hạn dòng).
**Phạm vi:** đo và ghi nhận. Mọi quyết định làm sạch nằm trong `dictionary/data_dictionary.md` mục 10 và chờ duyệt.

## 1. Kiểm kê file

| File | Số dòng | Kích thước (byte) | SHA-256 |
|---|---|---|---|
| `courses.csv` | 22 | 526 | `4f16eee7454b15e109b0a21a0e43be820e6846ed6f9301bb7feb5ab5ad737a75` |
| `assessments.csv` | 206 | 8.200 | `8cc738fb88ad760571d6f2a23059bfee0ffcae3bcd830514c9cbd5c6d5a046f1` |
| `vle.csv` | 6.364 | 260.126 | `d1b28303dea802ad87b4484e1196e878e06824850b9a4fe8aa34693439fe87e9` |
| `studentInfo.csv` | 32.593 | 3.461.652 | `7e6f3e474a5eee00639d2a414a6c7e928745823c2d2c2563ca1780145f99b0d6` |
| `studentRegistration.csv` | 32.593 | 1.109.984 | `0d32676285372aaf2e7a80304e5b274b4fba24313e2ca4c04317225e1ec90170` |
| `studentAssessment.csv` | 173.912 | 5.690.310 | `fd5320786328d05af841ee7dd4b5871b9dada3b9fe9d6a3642b2f42635510a6e` |
| `studentVle.csv` | 10.655.280 | 453.836.331 | `52668253d876c5becbcb72185977152700cecab2942aca807fecc3dd54b937f0` |

Tổng khoảng 442,9 MiB; riêng `studentVle.csv` là 432,8 MiB.

**Điều kiện dừng đã đạt:** `studentInfo` = 32.593 và `studentVle` = 10.655.280, khớp số liệu nguồn.

## 2. Định dạng

| Kiểm tra | Kết quả |
|---|---|
| Encoding | UTF-8 hợp lệ ở cả 7 file; không BOM; 0 byte ngoài ASCII |
| Dấu phân cách | Dấu phẩy ở cả 7 file (số dấu phẩy trong header khớp số cột - 1) |
| Header | Khớp 100% với giả thuyết ban đầu cả 7 file |
| Dấu nháy | Mọi trường trong header đều nằm trong dấu nháy kép |
| Kết thúc dòng | Cả 7 file `crlf` (lần chạy v2). Nhãn `mixed` ở lần chạy v1 là lỗi đếm của script (S1) |

## 3. Chất lượng dữ liệu đo được

| Tiêu chí | Kết quả |
|---|---|
| Khóa chính | 6/7 bảng đạt 100% duy nhất ở khóa ứng viên; `studentVle` đạt 79,39% (không có khóa tự nhiên) |
| Dòng trùng hoàn toàn | 0 ở 6 bảng; 787.170 ở `studentVle` (7,39% tổng số dòng) |
| Khóa ngoại | 0 dòng mồ côi ở cả 10 quan hệ đã đo |
| Giá trị thiếu | Chỉ ở 7 cột (bảng dưới); token thiếu duy nhất là chuỗi rỗng |
| Khoảng trắng thừa / số 0 đứng đầu | 0 ở mọi cột |
| Điểm ngoài [0, 100] | 0 |
| Click <= 0 hoặc thiếu | 0 |
| Hủy đăng ký trước khi đăng ký | 0 |
| `week_from > week_to` | 0 |
| Hạn nộp bài (`assessments.date`) sau khi hết khóa | 0 |
| Lượt nộp bài (`studentAssessment`) sau khi hết khóa | 85 (muộn nhất 354 ngày) |
| Lượt nộp bài trước ngày bắt đầu | 2.057 (min -11 ngày) |

| Cột bị thiếu | Dòng thiếu | Tỉ lệ |
|---|---|---|
| `assessments.date` | 11 | 5,34% |
| `vle.week_from` | 5.243 | 82,39% |
| `vle.week_to` | 5.243 | 82,39% |
| `studentInfo.imd_band` | 1.111 | 3,41% |
| `studentRegistration.date_registration` | 45 | 0,14% |
| `studentRegistration.date_unregistration` | 22.521 | 69,10% (không có sự kiện hủy, không phải lỗi) |
| `studentAssessment.score` | 173 | 0,10% |

## 4. Hai lỗi của script đã phát hiện và sửa (v2)

| # | Lỗi | Ảnh hưởng | Trạng thái |
|---|---|---|---|
| S1 | Đếm `\r\n` theo từng khối 1 MiB nên bỏ sót cặp bị cắt đúng ranh giới khối | Có thể gây nhãn `mixed` giả ở file lớn (`studentVle` 433 khối, `studentAssessment` 5 khối). Nhãn `mixed` hiện tại là **chưa đáng tin** | Đã sửa; xác nhận bằng lần chạy v2: cả 7 file là `crlf` |
| S2 | Nhãn `inferred_type = integer` dùng phép ép kiểu DuckDB làm tròn số lẻ | `weight` bị gắn nhãn `integer` dù có 7,5; 12,5; 17,5. Các cột khác chưa kiểm được bằng nhãn này | Đã sửa; xác nhận bằng v2: `weight` là numeric, mọi cột integer còn lại chỉ chứa số nguyên |

Bản v2 cũng thêm 12 truy vấn để trả lời các câu hỏi còn mở (mục 5). Bản v2 đã chạy thành công trên DuckDB 1.5.5 với dữ liệu thật (12/12 truy vấn mới không lỗi, đo toàn bộ dòng).

## 5. Câu hỏi đã trả lời bằng v2

| Câu hỏi | Kết quả |
|---|---|
| 11 bài thiếu `date` thuộc loại nào? | Cả 11 đều là Exam (11/24 bài Exam) |
| `week_from` và `week_to` thiếu trên cùng các dòng? | Có: 5.243 dòng thiếu cả hai; 1.121 dòng có đủ cả hai; không có dòng thiếu một trong hai |
| 18 bài không có lượt nộp là loại nào? | Cả 18 đều là Exam, ở 18 cặp module-presentation; chỉ 6/24 bài Exam có điểm |
| Bao nhiêu lượt nộp sau khi hết khóa? | 85 lượt, muộn nhất 354 ngày sau khi hết khóa |
| Bao nhiêu lượt nộp trước ngày bắt đầu? | 2.057 lượt (min -11 ngày) |
| Dòng trùng khóa ở `studentVle` khác nhau thế nào? | 1.614.505 nhóm trùng khóa, dư 2.195.960 dòng; 1.179.074 nhóm (73,0%) có nhiều giá trị `sum_click` khác nhau; 460.864 dòng dư thuộc nhóm mọi dòng cùng `sum_click`. Xuất hiện ở cả 22 presentation (từ 18.747 nhóm ở GGG 2014J đến 179.402 ở FFF 2014J) |
| Số lượt học trên mỗi sinh viên? | 1 lượt: 25.247; 2: 3.293; 3: 221; 4: 23; 5: 1 (tổng 28.785 sinh viên) |
| 45 dòng thiếu `date_registration` thuộc kết quả cuối nào? | Withdrawn 39, Fail 5, Pass 1 |
| 173 dòng thiếu `score` có liên quan `is_banked` không? | 172 dòng `is_banked = 0`, 1 dòng `is_banked = 1`: không thấy liên hệ rõ |
| `imd_band` thiếu tập trung ở đâu? | Thiếu ở cả 22 presentation; nhiều nhất CCC 2014J (146), CCC 2014B (108), FFF 2013J (101) |
| Bài weight = 0 thuộc module nào? | FFF CMA 28, GGG CMA 18, GGG TMA 9, BBB TMA 1 (tổng 56) |

**INSUFFICIENT EVIDENCE** cho mọi kết luận về nguyên nhân (vì sao `studentVle` có dòng lặp, vì sao 18/24 bài Exam không có điểm, vì sao có lượt nộp muộn tới 354 ngày). Báo cáo này không đoán nguyên nhân. Con số "1.408.790 dòng khác `sum_click`" từng được suy ra bằng phép trừ ở bản trước đã bị thay bằng số đo trực tiếp ở trên.

## 6. Việc cần phối hợp

| Với | Nội dung |
|---|---|
| Chủ repo / CI | `studentVle.csv` (432,8 MiB) vượt giới hạn 100 MB mỗi file của GitHub, nên không thể commit trực tiếp. Cần chọn: Git LFS, hoặc chỉ commit `source_manifest.json` + hướng dẫn tải + kiểm tra SHA-256 (quyết định D3 trong `README.md`) |
| Người viết Profiler / Modeler | `studentVle` là ca thử tự nhiên cho việc không được đề xuất khóa duy nhất sai (79,39%); `weight` cần DECIMAL; `imd_band` có một nhóm viết khác dạng; `date*` là số ngày tương đối chứ không phải ngày lịch |
| Người viết bộ so sánh multiset (`compare/multiset.py`) | `studentVle` có 787.170 dòng trùng hoàn toàn, nên so sánh theo đếm số lần xuất hiện của từng dòng là bắt buộc; so sánh theo tập hợp hoặc theo số dòng sẽ cho kết luận sai |
| Người viết test (FR-08) | Không sinh test bắt buộc từ: tổng `weight` = 100 mỗi presentation (sai ở GGG và CCC), `Withdrawn` ⇔ có `date_unregistration` (sai 102 dòng), khóa duy nhất ở `studentVle` (sai) |
