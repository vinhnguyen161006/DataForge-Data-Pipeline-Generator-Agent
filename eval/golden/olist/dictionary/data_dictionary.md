# Olist — Data Dictionary (tiếng Việt)

**Trạng thái:** `v0.1-draft`. Số liệu (số dòng, tỉ lệ thiếu, giá trị phân biệt, khoảng giá trị, phân bố) đo trực tiếp từ bản profiling đầy đủ ngày 09/10/2026. **Ý nghĩa nghiệp vụ của cột là suy luận từ tên cột và mô tả công khai, chưa đối chiếu lại với tài liệu gốc của Olist.**
**Nguồn:** Brazilian E-Commerce Public Dataset by Olist, Kaggle, CC BY-NC-SA 4.0. Chi tiết nguồn xem `README.md`; báo cáo chất lượng xem `metadata/data_quality_report.md`.

## 0. Cách đọc tài liệu

### Thang độ chắc chắn

| Nhãn | Nghĩa |
|---|---|
| `Đã đo` | Có số trong `profile_report.json` |
| `Suy luận` | Ý nghĩa cột suy ra từ tên và mô tả công khai; chưa đối chiếu lại |
| `Cần duyệt` | Cần nhóm quyết định (làm sạch, ràng buộc, ca đặc biệt) |

Cột "Ý nghĩa" là `Suy luận` cho đến khi được đối chiếu với tài liệu gốc (xem mục 7).

### Quy ước kiểu

- **Kiểu gốc:** mọi cột trong CSV đều là văn bản. Báo cáo ghi nhận chuỗi rỗng là giá trị thiếu duy nhất (không có `NULL`, `NA`, `?`).
- **Kiểu chuẩn:** kiểu đề xuất ở tầng silver. Bronze giữ nguyên chuỗi.
- **Mã bưu chính** (`*_zip_code_prefix`) và **mã định danh** là chuỗi, không ép số: có 23.995 mã khách và 1.027 mã người bán bắt đầu bằng số 0. Báo cáo `profile_report.json` ghi nhãn `integer` cho các cột này vì phép thử số nguyên không phân biệt được số có số 0 đứng đầu. **Nhãn `integer` của hai cột mã bưu chính là sai về ngữ nghĩa**; kiểu chuẩn đề xuất là VARCHAR.
- **Thời gian** định dạng `YYYY-MM-DD HH:MM:SS` ở mọi cột thời điểm (đã đo khoảng giá trị). Các cột ngày không có giờ (`order_estimated_delivery_date`, `review_creation_date`) luôn có `00:00:00`.
- **Chữ thường và không dấu:** tên thành phố hiển thị ở dạng chữ thường, không dấu (ví dụ `sao paulo`). Số byte ngoài ASCII: `geolocation` 160.464, `order_reviews` 110.640, `sellers` 6, `category_translation` 3; nội dung cụ thể của các byte này chưa được liệt kê.
- **Số liệu thống kê số của cột văn bản không có ý nghĩa:** báo cáo tính min/max số cho cột văn bản bằng cách ép kiểu, có kết quả vô nghĩa như `nmax = 10.000.000.000.000` trong tiêu đề đánh giá. Bỏ qua các trường `numeric_*` của cột văn bản.

### Quan hệ giữa các bảng (đã đo, 0 mồ côi trừ khi ghi khác)

| Quan hệ | Dòng con | Mồ côi |
|---|---|---|
| `orders.customer_id` → `customers` | 99.441 | 0 |
| `order_items.order_id` → `orders` | 112.650 | 0 |
| `order_items.product_id` → `products` | 112.650 | 0 |
| `order_items.seller_id` → `sellers` | 112.650 | 0 |
| `order_payments.order_id` → `orders` | 103.886 | 0 |
| `order_reviews.order_id` → `orders` | 99.224 | 0 |
| `products.product_category_name` → `category_translation` | 32.951 | 623 (610 rỗng + 13 không có bản dịch) |
| `customers.customer_zip_code_prefix` → `geolocation` (theo zip) | 99.441 | 278 |
| `sellers.seller_zip_code_prefix` → `geolocation` (theo zip) | 3.095 | 7 |

Quan hệ theo zip không có khóa duy nhất phía cha (19.015 zip, 1.000.163 dòng), nên phép nối theo zip có thể nhân số dòng. Phải tổng hợp `geolocation` theo zip trước khi nối.

---

## customers (khách hàng)

**File:** `olist_customers_dataset.csv` · **Số dòng:** 99.441 · **Grain:** Một mã khách trên một đơn hàng · **Khóa:** customer_id

| Cột | Ý nghĩa | Kiểu chuẩn | Khóa / quan hệ | Thiếu (số dòng, %) | Giá trị phân biệt | Khoảng và phân bố đo được | Quy tắc làm sạch đề xuất | Độ chắc chắn |
|---|---|---|---|---|---|---|---|---|
| `customer_id` | Mã khách gắn với một đơn hàng cụ thể; khác nhau cho mỗi đơn, kể cả cùng một người mua | VARCHAR(32) | PK | 0 | 99.441 | Khóa của bảng; FK từ `orders.customer_id`; Mã hex 32 ký tự; duy nhất 100%. Không dùng để đếm khách thật | Giữ nguyên | Suy luận; số liệu Đã đo |
| `customer_unique_id` | Mã nhận diện khách thật, xuyên suốt nhiều đơn | VARCHAR(32) | Không phải khóa | 0 | 96.096 | Duy nhất 96,64%; 2.997 mã xuất hiện nhiều hơn một lần; Dùng cho chỉ số khách; không dùng customer_id | Giữ nguyên | Suy luận; số liệu Đã đo |
| `customer_zip_code_prefix` | Năm chữ số đầu mã bưu chính của khách | VARCHAR(5) | FK (theo zip) tới `geolocation` | 0 | 14.994 | Lưu dạng chuỗi giữ số 0 đầu (23.995 dòng bắt đầu bằng 0); Chuỗi 5 ký tự; 14.994 giá trị khác nhau | Không ép số; luôn giữ chuỗi 5 ký tự | Suy luận; số liệu Đã đo |
| `customer_city` | Tên thành phố của khách | VARCHAR | — | 0 | 4.119 | 4.119 giá trị khác nhau; Viết thường, không dấu (ví dụ `sao paulo`); phổ biến nhất `sao paulo` 15.540 dòng | Giữ nguyên; chuẩn hóa tên trong tầng dim, cần duyệt | Suy luận; số liệu Đã đo |
| `customer_state` | Bang (UF) của khách, hai chữ cái | CHAR(2) | — | 0 | 27 | 27 giá trị (đủ 27 bang và Distrito Federal); SP 41.746; RJ 12.852; MG 11.635 (phổ biến nhất) | Giữ nguyên | Suy luận; số liệu Đã đo |

## geolocation (tọa độ theo mã bưu chính)

**File:** `olist_geolocation_dataset.csv` · **Số dòng:** 1.000.163 · **Grain:** Một bản ghi tọa độ theo mã bưu chính (không có khóa tự nhiên) · **Khóa:** không có

| Cột | Ý nghĩa | Kiểu chuẩn | Khóa / quan hệ | Thiếu (số dòng, %) | Giá trị phân biệt | Khoảng và phân bố đo được | Quy tắc làm sạch đề xuất | Độ chắc chắn |
|---|---|---|---|---|---|---|---|---|
| `geolocation_zip_code_prefix` | Năm chữ số đầu mã bưu chính | VARCHAR(5) | Không phải khóa (một zip có nhiều dòng) | 0 | 19.015 | Có 19.015 giá trị; 245.733 dòng bắt đầu bằng 0; Chuỗi 5 ký tự | Giữ chuỗi, không ép số | Suy luận; số liệu Đã đo |
| `geolocation_lat` | Vĩ độ của điểm trong zip | DOUBLE | — | 0 | 717.372 | 717.372 giá trị khác nhau; khoảng -36,61 đến 45,07; Có giá trị gần 0 (ví dụ -0,00004); cần kiểm tra điểm có nằm ở Brazil không | Giữ nguyên; kiểm tra miền theo bang trong tầng silver | Suy luận; số liệu Đã đo |
| `geolocation_lng` | Kinh độ của điểm trong zip | DOUBLE | — | 0 | 717.615 | 717.615 giá trị khác nhau; khoảng -101,47 đến 121,11; Giá trị ngoài Brazil (ví dụ 121,11; 9,34) cần kiểm tra thêm | Giữ nguyên; cảnh báo nếu ngoài khung Brazil; cần duyệt | Suy luận; số liệu Đã đo |
| `geolocation_city` | Tên thành phố ứng với điểm tọa độ | VARCHAR | — | 0 | 8.011 | 8.011 giá trị; có biến thể chính tả (`so paulo` 24.918 dòng và `sao paulo` 135.800 dòng); Có giá trị bất thường `* cidade`; một dòng có khoảng trắng thừa | Giữ nguyên; không gộp biến thể khi chưa có rule được duyệt | Suy luận; số liệu Đã đo |
| `geolocation_state` | Bang của điểm tọa độ | CHAR(2) | — | 0 | 27 | 27 giá trị; SP 404.268 (chiếm đa số dòng) | Giữ nguyên | Suy luận; số liệu Đã đo |

## orders (đơn hàng)

**File:** `olist_orders_dataset.csv` · **Số dòng:** 99.441 · **Grain:** Một đơn hàng · **Khóa:** order_id

| Cột | Ý nghĩa | Kiểu chuẩn | Khóa / quan hệ | Thiếu (số dòng, %) | Giá trị phân biệt | Khoảng và phân bố đo được | Quy tắc làm sạch đề xuất | Độ chắc chắn |
|---|---|---|---|---|---|---|---|---|
| `order_id` | Mã đơn hàng | VARCHAR(32) | PK | 0 | 99.441 | Khóa của bảng; đích FK của `order_items`, `order_payments`, `order_reviews`; Duy nhất 100% | Giữ nguyên | Suy luận; số liệu Đã đo |
| `customer_id` | Mã khách của đơn (xem `customers.customer_id`) | VARCHAR(32) | FK → `customers.customer_id` | 0 | 99.441 | Quan hệ N-1; 0 dòng mồ côi; Duy nhất 100% trong bảng này (mỗi đơn có một mã khách riêng) | Giữ nguyên | Suy luận; số liệu Đã đo |
| `order_status` | Trạng thái đơn hàng | VARCHAR | — | 0 | 8 | 8 giá trị khác nhau; delivered 96.478; shipped 1.107; canceled 625; unavailable 609; invoiced 314; processing 301; approved 2; created 5 | Giữ nguyên; danh sách giá trị là cảnh báo, không chặn | Suy luận; số liệu Đã đo |
| `order_purchase_timestamp` | Thời điểm khách đặt hàng | TIMESTAMP | — | 0 | 98.875 | 98.875 giá trị khác nhau; từ 2016-09-04 đến 2018-10-17; Định dạng `YYYY-MM-DD HH:MM:SS` (giờ có thể là 00:00:00) | Ép TIMESTAMP; kiểm tra định dạng | Suy luận; số liệu Đã đo |
| `order_approved_at` | Thời điểm đơn được duyệt thanh toán | TIMESTAMP | — | 160 (0,16%) | 90.734 | Thiếu 160 dòng (0,16%); Chuỗi rỗng khi thiếu | Rỗng → NULL ở silver | Suy luận; số liệu Đã đo |
| `order_delivered_carrier_date` | Thời điểm đơn được bàn giao cho đơn vị vận chuyển | TIMESTAMP | — | 1.783 (1,79%) | 81.019 | Thiếu 1.783 dòng (1,79%); Chuỗi rỗng khi thiếu; phần lớn thiếu do đơn chưa đến bước này | Rỗng → NULL ở silver | Suy luận; số liệu Đã đo |
| `order_delivered_customer_date` | Thời điểm khách nhận hàng | TIMESTAMP | — | 2.965 (2,98%) | 95.665 | Thiếu 2.965 dòng (2,98%); trong đó 8 đơn `delivered` thiếu ngày; Chuỗi rỗng khi thiếu; 8 đơn `delivered` thiếu là ca kiểm thử (F-7) | Rỗng → NULL; đơn `delivered` thiếu ngày là cảnh báo chờ duyệt | Suy luận; số liệu Đã đo |
| `order_estimated_delivery_date` | Ngày giao dự kiến khi đặt hàng | TIMESTAMP | — | 0 | 459 | Không thiếu; 459 ngày khác nhau; từ 2016-09-30 đến 2018-11-12; Giờ luôn là 00:00:00 | Ép TIMESTAMP | Suy luận; số liệu Đã đo |

## order_items (dòng hàng)

**File:** `olist_order_items_dataset.csv` · **Số dòng:** 112.650 · **Grain:** Một dòng hàng trong một đơn · **Khóa:** (order_id, order_item_id)

| Cột | Ý nghĩa | Kiểu chuẩn | Khóa / quan hệ | Thiếu (số dòng, %) | Giá trị phân biệt | Khoảng và phân bố đo được | Quy tắc làm sạch đề xuất | Độ chắc chắn |
|---|---|---|---|---|---|---|---|---|
| `order_id` | Mã đơn chứa dòng hàng | VARCHAR(32) | PK (ghép); FK → `orders.order_id` | 0 | 98.666 | 98.666 đơn có dòng hàng; 775 đơn không có dòng nào; Đơn nhiều hàng xuất hiện nhiều dòng | Giữ nguyên | Suy luận; số liệu Đã đo |
| `order_item_id` | Số thứ tự của dòng hàng trong đơn | SMALLINT | PK (ghép) | 0 | 21 | Từ 1 đến 21; 98.666 dòng có số 1; Không có khoảng trống trong dãy số của đơn (0 đơn bị gián đoạn) | Ép SMALLINT | Suy luận; số liệu Đã đo |
| `product_id` | Mã sản phẩm được bán | VARCHAR(32) | FK → `products.product_id` | 0 | 32.951 | 32.951 sản phẩm khác nhau; 0 mồ côi; Sản phẩm bán nhiều nhất 527 dòng | Giữ nguyên | Suy luận; số liệu Đã đo |
| `seller_id` | Mã người bán của dòng hàng | VARCHAR(32) | FK → `sellers.seller_id` | 0 | 3.095 | 3.095 người bán khác nhau; 0 mồ côi; Người bán nhiều nhất 2.033 dòng | Giữ nguyên | Suy luận; số liệu Đã đo |
| `shipping_limit_date` | Hạn người bán phải chuyển hàng cho đơn vị vận chuyển | TIMESTAMP | — | 0 | 93.318 | 93.318 giá trị khác nhau; từ 2016-09-19 đến 2020-04-09; Định dạng `YYYY-MM-DD HH:MM:SS`; giá trị 2020 nằm ngoài khoảng dữ liệu đơn hàng (2016 đến 2018) | Ép TIMESTAMP; cảnh báo giá trị ngoài khoảng, cần duyệt | Suy luận; số liệu Đã đo |
| `price` | Giá của một đơn vị hàng, đơn vị real brasileiro (BRL) | DECIMAL(10,2) | — | 0 | 5.968 | 5.968 giá trị; từ 0,85 đến 6.735,00; Giá phổ biến nhất 59,90 (2.481 dòng) | Ép DECIMAL(10,2); không kiểm tra theo dòng với hàng + phí | Suy luận; số liệu Đã đo |
| `freight_value` | Phí vận chuyển của dòng hàng, BRL | DECIMAL(10,2) | — | 0 | 6.999 | 6.999 giá trị; từ 0,00 đến 409,68; 383 dòng có phí bằng 0 (hợp lệ, ca đối chứng) | Ép DECIMAL(10,2); không coi phí 0 là lỗi | Suy luận; số liệu Đã đo |

## order_payments (thanh toán)

**File:** `olist_order_payments_dataset.csv` · **Số dòng:** 103.886 · **Grain:** Một lần thanh toán trong một đơn · **Khóa:** (order_id, payment_sequential)

| Cột | Ý nghĩa | Kiểu chuẩn | Khóa / quan hệ | Thiếu (số dòng, %) | Giá trị phân biệt | Khoảng và phân bố đo được | Quy tắc làm sạch đề xuất | Độ chắc chắn |
|---|---|---|---|---|---|---|---|---|
| `order_id` | Mã đơn được thanh toán | VARCHAR(32) | PK (ghép); FK → `orders.order_id` | 0 | 99.440 | 99.440 đơn; 1 đơn không có thanh toán; Đơn trả nhiều phương thức có nhiều dòng | Giữ nguyên | Suy luận; số liệu Đã đo |
| `payment_sequential` | Số thứ tự của lần thanh toán trong đơn | SMALLINT | PK (ghép) | 0 | 29 | Từ 1 đến 29; 99.360 dòng có số 1; Không kiểm tra khoảng trống trong bảng này | Ép SMALLINT | Suy luận; số liệu Đã đo |
| `payment_type` | Phương thức thanh toán | VARCHAR | — | 0 | 5 | 5 giá trị; credit_card 76.795; boleto 19.784; voucher 5.775; debit_card 1.529; not_defined 3 | Giữ nguyên; `not_defined` là cảnh báo | Suy luận; số liệu Đã đo |
| `payment_installments` | Số kỳ trả góp | SMALLINT | — | 0 | 24 | 24 giá trị khác nhau; từ 0 đến 24; Phổ biến nhất 1 kỳ (52.546 dòng); có giá trị 0 (số dòng chưa đo) | Ép SMALLINT; giá trị 0 cần xác nhận ý nghĩa | Suy luận; số liệu Đã đo |
| `payment_value` | Số tiền của lần thanh toán, BRL | DECIMAL(10,2) | — | 0 | 29.077 | 29.077 giá trị; từ 0,00 đến 13.664,08; 9 dòng có giá trị không dương (6 voucher, 3 not_defined); là ca cần duyệt (F-8) | Ép DECIMAL(10,2); là trường trung tâm của câu hỏi FR-05 (F-3) | Suy luận; số liệu Đã đo |

## order_reviews (đánh giá)

**File:** `olist_order_reviews_dataset.csv` · **Số dòng:** 99.224 · **Grain:** Một đánh giá gắn với một đơn · **Khóa:** (review_id, order_id)

| Cột | Ý nghĩa | Kiểu chuẩn | Khóa / quan hệ | Thiếu (số dòng, %) | Giá trị phân biệt | Khoảng và phân bố đo được | Quy tắc làm sạch đề xuất | Độ chắc chắn |
|---|---|---|---|---|---|---|---|---|
| `review_id` | Mã đánh giá | VARCHAR(32) | Không phải khóa (xem mục 3) | 0 | 98.410 | 98.410 giá trị khác nhau; 789 mã xuất hiện nhiều hơn một lần (tối đa 3); Mã trùng là ca khóa giả (F-2) | Không dùng làm khóa đơn lẻ | Suy luận; số liệu Đã đo |
| `order_id` | Mã đơn được đánh giá | VARCHAR(32) | FK → `orders.order_id` | 0 | 98.673 | 98.673 đơn có đánh giá; 768 đơn không có; Một đơn có thể có nhiều đánh giá | Giữ nguyên | Suy luận; số liệu Đã đo |
| `review_score` | Điểm đánh giá của khách, từ 1 đến 5 | SMALLINT | — | 0 | 5 | 5 giá trị; 5 sao 57.328; 4 sao 19.142; 1 sao 11.424; 3 sao 8.179; 2 sao 3.151 | Ép SMALLINT; kiểm tra miền 1 đến 5 | Suy luận; số liệu Đã đo |
| `review_comment_title` | Tiêu đề bình luận, tiếng Bồ Đào Nha | VARCHAR | — | 87.657 (88,34%) | 4.528 | Thiếu 87.657 dòng (88,34%); có 1.998 dòng chứa khoảng trắng thừa; Giá trị phổ biến khác rỗng: `Recomendo` 423, `recomendo` 345 (khác chữ hoa thường) | Rỗng → NULL; trim khoảng trắng; cân nhắc chữ hoa thường | Suy luận; số liệu Đã đo |
| `review_comment_message` | Nội dung bình luận, tiếng Bồ Đào Nha | VARCHAR | — | 58.250 (58,71%) | 36.160 | Thiếu 58.250 dòng (58,71%); 8.120 dòng có khoảng trắng thừa; có ký tự xuống dòng `\r\n` trong nội dung; Nội dung có dấu phẩy, dấu ngoặc kép và xuống dòng; khi đọc CSV phải đúng dấu nháy kép | Rỗng → NULL; giữ xuống dòng; không dùng để suy ra điểm | Suy luận; số liệu Đã đo |
| `review_creation_date` | Ngày khách gửi đánh giá | TIMESTAMP | — | 0 | 636 | 636 ngày khác nhau; từ 2016-10-02 đến 2018-08-31; Giờ luôn là 00:00:00 | Ép TIMESTAMP (chỉ dùng ngày) | Suy luận; số liệu Đã đo |
| `review_answer_timestamp` | Thời điểm đánh giá được ghi nhận | TIMESTAMP | — | 0 | 98.248 | 98.248 giá trị khác nhau; từ 2016-10-07 đến 2018-10-29; Định dạng `YYYY-MM-DD HH:MM:SS` | Ép TIMESTAMP | Suy luận; số liệu Đã đo |

## products (sản phẩm)

**File:** `olist_products_dataset.csv` · **Số dòng:** 32.951 · **Grain:** Một sản phẩm · **Khóa:** product_id

| Cột | Ý nghĩa | Kiểu chuẩn | Khóa / quan hệ | Thiếu (số dòng, %) | Giá trị phân biệt | Khoảng và phân bố đo được | Quy tắc làm sạch đề xuất | Độ chắc chắn |
|---|---|---|---|---|---|---|---|---|
| `product_id` | Mã sản phẩm | VARCHAR(32) | PK | 0 | 32.951 | Duy nhất 100%; là đích FK của `order_items.product_id`; 32.951 giá trị | Giữ nguyên | Suy luận; số liệu Đã đo |
| `product_category_name` | Tên danh mục sản phẩm, tiếng Bồ Đào Nha | VARCHAR | FK (theo tên) → `category_translation` | 610 (1,85%) | 74 | Thiếu 610 dòng (1,85%); 13 sản phẩm có danh mục không có bản dịch; Phổ biến nhất `cama_mesa_banho` 3.029 | Rỗng → NULL; 13 dòng không khớp bản dịch là cảnh báo (F-6) | Suy luận; số liệu Đã đo |
| `product_name_lenght` | Số ký tự của tên sản phẩm (tên cột viết sai chính tả trong nguồn: `lenght`) | SMALLINT | — | 610 (1,85%) | 67 | Thiếu 610 dòng (1,85%); từ 5 đến 76; Phổ biến 60 ký tự (2.182 dòng) | Giữ tên gốc; ép SMALLINT; đổi tên chuẩn ở tầng silver | Suy luận; số liệu Đã đo |
| `product_description_lenght` | Số ký tự của mô tả sản phẩm (tên cột viết sai chính tả trong nguồn: `lenght`) | SMALLINT | — | 610 (1,85%) | 2.961 | Thiếu 610 dòng (1,85%); từ 4 đến 3.992; Giá trị 404 phổ biến (94 dòng) | Giữ tên gốc; ép SMALLINT | Suy luận; số liệu Đã đo |
| `product_photos_qty` | Số ảnh của sản phẩm | SMALLINT | — | 610 (1,85%) | 20 | Thiếu 610 dòng (1,85%); từ 1 đến 20; 1 ảnh 16.489; 2 ảnh 6.263; 3 ảnh 3.860 | Ép SMALLINT | Suy luận; số liệu Đã đo |
| `product_weight_g` | Khối lượng sản phẩm, gam | INTEGER | — | 2 (0,01%) | 2.205 | Thiếu 2 dòng; từ 0 đến 40.425; Có giá trị 0 (số dòng chưa đo; cần kiểm tra vì khối lượng 0 có thể là lỗi nhập) | Ép INTEGER; cảnh báo khi bằng 0 (cần duyệt) | Suy luận; số liệu Đã đo |
| `product_length_cm` | Chiều dài sản phẩm, cm | SMALLINT | — | 2 (0,01%) | 100 | Thiếu 2 dòng; từ 7 đến 105; Phổ biến 16 cm (5.520 dòng) | Ép SMALLINT | Suy luận; số liệu Đã đo |
| `product_height_cm` | Chiều cao sản phẩm, cm | SMALLINT | — | 2 (0,01%) | 103 | Thiếu 2 dòng; từ 2 đến 105; Phổ biến 10 cm (2.548 dòng) | Ép SMALLINT | Suy luận; số liệu Đã đo |
| `product_width_cm` | Chiều rộng sản phẩm, cm | SMALLINT | — | 2 (0,01%) | 96 | Thiếu 2 dòng; từ 6 đến 118; Phổ biến 11 cm (3.718 dòng) | Ép SMALLINT | Suy luận; số liệu Đã đo |

## sellers (người bán)

**File:** `olist_sellers_dataset.csv` · **Số dòng:** 3.095 · **Grain:** Một người bán · **Khóa:** seller_id

| Cột | Ý nghĩa | Kiểu chuẩn | Khóa / quan hệ | Thiếu (số dòng, %) | Giá trị phân biệt | Khoảng và phân bố đo được | Quy tắc làm sạch đề xuất | Độ chắc chắn |
|---|---|---|---|---|---|---|---|---|
| `seller_id` | Mã người bán | VARCHAR(32) | PK | 0 | 3.095 | Duy nhất 100%; đích FK của `order_items.seller_id`; 3.095 giá trị | Giữ nguyên | Suy luận; số liệu Đã đo |
| `seller_zip_code_prefix` | Năm chữ số đầu mã bưu chính của người bán | VARCHAR(5) | FK (theo zip) tới `geolocation` | 0 | 2.246 | 2.246 giá trị; 1.027 dòng bắt đầu bằng 0; Chuỗi 5 ký tự | Giữ chuỗi, không ép số | Suy luận; số liệu Đã đo |
| `seller_city` | Tên thành phố của người bán | VARCHAR | — | 0 | 611 | 611 giá trị khác nhau; Có một giá trị dạng số `04482255` (là giá trị thấp nhất của cột; số dòng chưa đo); phổ biến nhất `sao paulo` 694 | Giữ nguyên; giá trị dạng số là ca cần kiểm tra (F-9) | Suy luận; số liệu Đã đo |
| `seller_state` | Bang của người bán | CHAR(2) | — | 0 | 23 | 23 giá trị; SP 1.849 (chiếm đa số); PR 349; MG 244 | Giữ nguyên | Suy luận; số liệu Đã đo |

## category_translation (dịch danh mục)

**File:** `product_category_name_translation.csv` · **Số dòng:** 71 · **Grain:** Một danh mục sản phẩm · **Khóa:** product_category_name

| Cột | Ý nghĩa | Kiểu chuẩn | Khóa / quan hệ | Thiếu (số dòng, %) | Giá trị phân biệt | Khoảng và phân bố đo được | Quy tắc làm sạch đề xuất | Độ chắc chắn |
|---|---|---|---|---|---|---|---|---|
| `product_category_name` | Tên danh mục, tiếng Bồ Đào Nha | VARCHAR | PK | 0 | 71 | 71 giá trị, duy nhất 100%; Ví dụ `agro_industria_e_comercio` | Giữ nguyên; có BOM UTF-8 ở đầu file, đã được đọc đúng | Suy luận; số liệu Đã đo |
| `product_category_name_english` | Tên danh mục, tiếng Anh | VARCHAR | — | 0 | 71 | 71 giá trị; Ví dụ `agro_industry_and_commerce` | Giữ nguyên | Suy luận; số liệu Đã đo |

---

## Phát hiện về dữ liệu cần quyết định

| # | Phát hiện | Bằng chứng | Đề xuất | Cần duyệt |
|---|---|---|---|---|
| F-2 | `review_id` không phải khóa | 789 mã trùng, tối đa 3 dòng | Khóa đánh giá là (`review_id`, `order_id`) | Có |
| F-3 | Lệch giữa thanh toán và hàng + phí | 380 đơn lệch hơn 0,01; 82,4% trả góp | Hỏi Engineer về ý nghĩa `payment_value` (FR-05) | Có |
| F-6 | Danh mục sản phẩm | 610 rỗng; 13 không có bản dịch | Giữ NULL, không tự gán | Có |
| F-7 | Đơn `delivered` thiếu ngày giao | 8 đơn | Ca kiểm thử ràng buộc | Có |
| F-8 | Thanh toán không dương | 6 voucher, 3 not_defined | Xác nhận lỗi hay hợp lệ | Có |
| F-9 | `seller_city` có giá trị dạng số | Giá trị thấp nhất `04482255` | Kiểm tra dòng này; số dòng chưa đo | Có |
| F-10 | Tên thành phố có biến thể chính tả | `so paulo` (24.918) bên cạnh `sao paulo` (135.800) trong geolocation | Không gộp khi chưa có rule được duyệt | Có |
| F-11 | Mã bưu chính có số 0 đứng đầu | 23.995 mã khách, 1.027 mã người bán | Luôn lưu chuỗi 5 ký tự | Không (quy ước) |
| F-12 | Khối lượng sản phẩm bằng 0 | Có giá trị 0 (số dòng chưa đo) | Cảnh báo; cần kiểm tra | Có |
| F-13 | Giá trị `payment_installments` = 0 | Có (số dòng chưa đo) | Xác nhận ý nghĩa | Có |
| F-14 | `shipping_limit_date` có năm 2020 | Khoảng đến 2020-04-09, ngoài khoảng đơn hàng 2016 đến 2018 | Cảnh báo; kiểm tra có phải dữ liệu thật không | Có |
| F-15 | Nội dung đánh giá có xuống dòng và khoảng trắng | 8.120 nội dung có khoảng trắng; có `\r\n` | Giữ xuống dòng; đọc CSV đúng dấu nháy kép | Không (quy ước đọc) |

## Việc còn lại

| # | Việc | Điều kiện hoàn thành |
|---|---|---|
| 1 | Nhóm duyệt F-2 đến F-14 | Mỗi mục có Approved hoặc Rejected |
| 2 | Hỏi Engineer về F-3 | Có câu trả lời về `payment_value` |
| 3 | Đếm số dòng cho các mục "chưa đo": F-9, F-12, F-13 | Có số liệu trong `profile_report.json` (cần truy vấn bổ sung) |
| 4 | Đối chiếu ý nghĩa cột với mô tả gốc của Olist trên Kaggle | Các cột khớp được nâng lên `Đã xác nhận` |
