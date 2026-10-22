# Olist — Thiết kế chuẩn (bản trung gian v0.1)

**Trạng thái:** `DRAFT trung gian`. Chưa đối chiếu với schema `DataDesign` thực tế (`app/agents/schemas.py` chưa có trong môi trường làm việc). Không dùng làm đầu vào tự động cho đến khi được ánh xạ và kiểm tra.
**Căn cứ:** `olist/metadata/profile_report.json` (chạy đầy đủ, 1.550.922 dòng), `olist/dictionary/data_dictionary.md`, `olist/metadata/data_quality_report.md`.
**Nhãn:** `ĐÃ ĐO` = có số liệu trong hồ sơ profiling; `ĐỀ XUẤT` = lựa chọn thiết kế; `CẦN DUYỆT` = cần nhóm hoặc người có nghiệp vụ quyết định.

## 1. Grain

| Bảng đề xuất | Một dòng là | Nguồn | Số dòng kỳ vọng | Nhãn |
|---|---|---|---|---|
| fact_order_item | một dòng hàng trong một đơn | order_items | 112.650 | ĐÃ ĐO |
| fact_payment | một lần thanh toán trong một đơn | order_payments | 103.886 | ĐÃ ĐO |
| fact_review | một đánh giá gắn với một đơn | order_reviews | 99.224 | ĐÃ ĐO (với khóa tổ hợp) |
| dim_order | một đơn hàng | orders | 99.441 | ĐÃ ĐO |
| dim_customer | một mã khách trên một đơn (theo customer_id) | customers | 99.441 | ĐÃ ĐO |
| dim_customer_unique | một khách thật (theo customer_unique_id) | customers | 96.096 | ĐÃ ĐO; CẦN DUYỆT |
| dim_product | một sản phẩm | products | 32.951 | ĐÃ ĐO |
| dim_seller | một người bán | sellers | 3.095 | ĐÃ ĐO |
| dim_category | một danh mục (tiếng Bồ và tiếng Anh) | category_translation | 71 | ĐÃ ĐO |
| dim_zip | một mã bưu chính, tọa độ tổng hợp | geolocation (tổng hợp) | 19.015 | ĐÃ ĐO (số zip); CẦN DUYỆT (cách tổng hợp) |

Grain của `fact_order_item` không được chứa trực tiếp `payment_value`: một đơn có thể có nhiều lần thanh toán, nên nối trực tiếp sẽ nhân số dòng.

## 2. Khóa

| Bảng | Khóa | Duy nhất | Nhãn |
|---|---|---|---|
| orders | order_id | 100% | ĐÃ ĐO |
| order_items | (order_id, order_item_id) | 100% | ĐÃ ĐO |
| order_payments | (order_id, payment_sequential) | 100% | ĐÃ ĐO |
| order_reviews | (review_id, order_id) | 100% | ĐÃ ĐO |
| order_reviews | review_id đơn lẻ | 99,18%: không dùng làm khóa | ĐÃ ĐO |
| customers | customer_id | 100% | ĐÃ ĐO |
| customers | customer_unique_id | 96,64%: không phải khóa khách thật theo dữ liệu; là định danh khách theo mô tả nguồn | ĐÃ ĐO; CẦN DUYỆT |
| products | product_id | 100% | ĐÃ ĐO |
| sellers | seller_id | 100% | ĐÃ ĐO |
| category_translation | product_category_name | 100% | ĐÃ ĐO |
| geolocation | không có khóa tự nhiên (zip, lat, lng: 72,0%) | — | ĐÃ ĐO |

## 3. Quan hệ

| Quan hệ | Cardinality | Dòng con | Mồ côi | Nhãn |
|---|---|---|---|---|
| order_items → orders | N-1 | 112.650 | 0 | ĐÃ ĐO |
| order_items → products | N-1 | 112.650 | 0 | ĐÃ ĐO |
| order_items → sellers | N-1 | 112.650 | 0 | ĐÃ ĐO |
| order_payments → orders | N-1 | 103.886 | 0 | ĐÃ ĐO |
| order_reviews → orders | N-1 | 99.224 | 0 | ĐÃ ĐO |
| orders → customers (customer_id) | N-1 | 99.441 | 0 | ĐÃ ĐO |
| products → category_translation | N-1 | 32.951 | 623 (610 rỗng, 13 không có bản dịch) | ĐÃ ĐO |
| customers → dim_zip (theo zip) | N-1 | 99.441 | 278 | ĐÃ ĐO |
| sellers → dim_zip (theo zip) | N-1 | 3.095 | 7 | ĐÃ ĐO |

Không có quan hệ N-N trực tiếp. Quan hệ đơn-sản phẩm được hiện thực qua `fact_order_item`. Quan hệ theo zip không có khóa duy nhất phía cha, nên phải tổng hợp `geolocation` trước khi nối.

## 4. Metric

| Metric | Định nghĩa | Nguồn | Nhãn |
|---|---|---|---|
| Doanh thu hàng hóa | SUM(price) trên fact_order_item, lọc order_status | order_items, orders | CẦN DUYỆT (câu hỏi OLI-04) |
| Doanh thu gồm phí | SUM(price + freight_value) | order_items | CẦN DUYỆT (OLI-04) |
| Tổng thanh toán | SUM(payment_value) trên fact_payment | order_payments | CẦN DUYỆT (OLI-01) |
| Số đơn | COUNT(DISTINCT order_id) | orders | ĐỀ XUẤT |
| Số khách thật | COUNT(DISTINCT customer_unique_id) | customers | ĐỀ XUẤT; CẦN DUYỆT (OLI-02) |
| Tỉ lệ đơn trả góp | COUNT(đơn có payment_installments > 1) / COUNT(đơn) | order_payments | ĐỀ XUẤT |
| Điểm đánh giá trung bình | AVG(review_score) theo đánh giá, không theo dòng hàng | order_reviews | ĐỀ XUẤT; CẦN DUYỆT (OLI-03) |
| Thời gian giao hàng | order_delivered_customer_date − order_purchase_timestamp, chỉ đơn có cả hai ngày | orders | ĐỀ XUẤT; CẦN DUYỆT (OLI-07) |

Không dùng `SUM` trên `fact_order_item` kết hợp `fact_payment` trong cùng một truy vấn: đây là nguồn đếm trùng (rubric HF-5).

## 5. Làm sạch

| Quy tắc | Vấn đề đã đo | Quyết định đề xuất | Nhãn |
|---|---|---|---|
| Chuỗi rỗng thành NULL | Giá trị thiếu chỉ là chuỗi rỗng | Silver chuyển thành NULL | ĐÃ ĐO |
| Mã bưu chính là chuỗi 5 ký tự | 23.995 mã khách, 1.027 mã người bán có số 0 đứng đầu | VARCHAR(5), không ép số | ĐÃ ĐO |
| Không tự gán danh mục | 610 sản phẩm rỗng, 13 không có bản dịch | Giữ NULL, nhãn "Không rõ" ở dashboard | ĐÃ ĐO; CẦN DUYỆT (OLI-06) |
| Không điền ngày giao | 8 đơn delivered thiếu ngày giao | Giữ NULL, loại khỏi chỉ số thời gian giao | ĐÃ ĐO; CẦN DUYỆT (OLI-07) |
| Trim khoảng trắng nội dung đánh giá | 1.998 tiêu đề, 8.120 nội dung có khoảng trắng thừa | Trim, giữ xuống dòng trong nội dung | ĐÃ ĐO |
| Tọa độ ngoài Brazil | Vĩ độ đến 45,07; kinh độ đến 121,11 | Cảnh báo, không tự sửa | ĐÃ ĐO; CẦN DUYỆT (F-16) |
| Giá trị dạng số trong tên thành phố | seller_city có `04482255` | Giữ, cảnh báo | ĐÃ ĐO; CẦN DUYỆT (F-9) |
| Thanh toán không dương | 6 voucher, 3 not_defined | Giữ, cảnh báo | ĐÃ ĐO; CẦN DUYỆT (F-8) |

Không xóa dòng nào. Mọi quy tắc trên đều là cảnh báo hoặc giữ NULL, vì chưa có căn cứ nghiệp vụ để loại dữ liệu.

## 6. Dashboard (yêu cầu phân tích có căn cứ trong dữ liệu)

| Câu hỏi | Metric | Dimension | Bảng nguồn | Grain | Tổng hợp | Ghi chú |
|---|---|---|---|---|---|---|
| Doanh thu theo tháng | Doanh thu hàng hóa | tháng mua | fact_order_item ⋈ dim_order | dòng hàng | SUM theo tháng | Chờ OLI-04 |
| Phân bố đơn theo trạng thái | Số đơn | order_status | dim_order | đơn | COUNT | 8 trạng thái đã đo |
| Tỉ lệ trả góp theo bang | Tỉ lệ đơn trả góp | customer_state | fact_payment ⋈ dim_customer | đơn | tỉ lệ | Chờ OLI-01 |
| Điểm đánh giá theo danh mục | Điểm trung bình | category | fact_review ⋈ fact_order_item ⋈ dim_product | đánh giá | AVG | Chờ OLI-03; tránh đếm trùng đánh giá nhiều dòng hàng |
| Thời gian giao theo bang | Thời gian giao trung bình | customer_state | dim_order ⋈ dim_customer | đơn | AVG | Chờ OLI-07 |

Chỉ đề xuất các câu hỏi có cột nguồn đã đo. Không đề xuất dashboard theo khách thật cho đến khi OLI-02 được quyết định.

## 7. Câu hỏi cho Modeler (liên kết ambiguity_cases.csv)
OLI-01 (payment_value), OLI-02 (đếm khách), OLI-03 (grain đánh giá), OLI-04 (doanh thu), OLI-05 (zip), OLI-06 (danh mục), OLI-07 (đơn giao thiếu ngày), OLI-08 (không cần hỏi).

## 8. Chưa xác minh
- Tương thích với schema `DataDesign`.
- Ý nghĩa cột theo mô tả chính thức của Olist (chưa tìm được tài liệu đầy đủ).
- Các quyết định `CẦN DUYỆT`.
