# CSV mẫu cho kiểm chứng upload

Dữ liệu tổng hợp để học và kiểm thử upload/config/quan hệ trước khi dùng OULAD hoặc TPC-H. Không chứa dữ liệu người dùng thật.

| Bộ | File | Mục đích |
|---|---|---|
| complete | customers.csv, orders.csv | Đủ hai file bắt buộc |
| missing | customers.csv | Thiếu orders.csv; chưa đủ điều kiện READY |
| semicolon | customers.csv, orders.csv | orders.csv dùng dấu chấm phẩy |

[expected.json](expected.json) ghi đáp án và cấu hình đọc. Có 3 customer, 3 order, tổng amount 225.00, không có order mồ côi; customer 003 chưa có order. Các mã 001/002/003 phải giữ biểu diễn nguồn. City NA chỉ thành null khi cấu hình null_tokens có NA; nếu chỉ có chuỗi rỗng, NA vẫn là text.

Script [prepare_upload_checks.py](../../../scripts/prepare_upload_checks.py) chép nguồn sang backend/data/upload-checks/input, từ chối ghi đè bản local đã bị sửa và kiểm tra delimiter/null/leading zeros. Các CSV nguồn là fixture bất biến; đây chưa phải batch READY của ứng dụng.

Cách chạy và bằng chứng: [báo cáo kiểm chứng upload](../../../../docs/testing/upload-checks.md).
