# Olist — Báo cáo chất lượng dữ liệu (v0.1)

**Nguồn số liệu:** `profile_report.json` và `source_manifest.json` của bản chạy **đầy đủ** (không giới hạn dòng), DuckDB 1.5.5, ngày 09/10/2026. Mọi con số dưới đây đo trực tiếp trên 9 file trong `raw/`.
**Phạm vi:** đo và ghi nhận. Quyết định làm sạch và ràng buộc phải được nhóm duyệt; chưa có ràng buộc nào được coi là luật.

## 1. Kiểm kê file

| File | Số dòng | Kích thước (byte) | SHA-256 |
|---|---|---|---|
| `olist_customers_dataset.csv` | 99.441 | 9.033.957 | `983a422239e1712ded753b3bf9ecf47dc73f144d306029dcfa99e70a226883d2` |
| `olist_geolocation_dataset.csv` | 1.000.163 | 61.273.883 | `b514f6fc991b9566aeba02aa5d67e2c3630f034b60a0e05aa0d082a3b66d88d6` |
| `olist_orders_dataset.csv` | 99.441 | 17.654.914 | `8df58ef3d2d7e9944010f7beecd9b75367f5588ec6e3c91cec19ae3345ef9ecf` |
| `olist_order_items_dataset.csv` | 112.650 | 15.438.671 | `0bc4d068c4fe38cbb01bd90e8746e3c613fe7b4baef75fab7b0e329701c3e279` |
| `olist_order_payments_dataset.csv` | 103.886 | 5.777.138 | `4f713964f2815dbbaa40b9488268c55aac3627bfce5aa96cf58d1f3616de3cc0` |
| `olist_order_reviews_dataset.csv` | 99.224 | 14.451.670 | `012b61c7593e34f51fa614efdf802b9c7056ce6aae5307ddb93236e7cfc797d7` |
| `olist_products_dataset.csv` | 32.951 | 2.379.446 | `3e6569628a17fbc75fd206ee357b59e20364b9afa90f5b6cd5b4d624c58aa9cc` |
| `olist_sellers_dataset.csv` | 3.095 | 174.703 | `1f643d2b950373b85735e7794b20986f528d7a000432e7c6f9bcbb44d0846a0e` |
| `product_category_name_translation.csv` | 71 | 2.613 | `a81f0d1f27b27e7293f761bc79e3ce8f348ee39c4b3ed3e49bde38f478586278` |
| **Tổng** | **1.550.922** | **126.186.995** | |

Số dòng khớp với mô tả công khai của Olist: 99.441 đơn hàng (`orders`, `customers`), 9 bảng. Đây là căn cứ **đo được** cho con số khoảng 100.000 đơn, không còn là "Nguồn thứ ba".

**Đã sửa:** tài liệu trước ghi tổng khoảng 1,3 triệu dòng. Con số đo được là **1.550.922 dòng**; phần lớn là `geolocation` (1.000.163).

## 2. Định dạng

| Kiểm tra | Kết quả |
|---|---|
| Encoding | UTF-8 hợp lệ ở cả 9 file |
| Dấu phân cách | Dấu phẩy ở cả 9 file; số dấu phẩy trong header khớp số cột - 1 |
| Header | Khớp 100% với danh sách kỳ vọng ở cả 9 file |
| Kết thúc dòng | 6 file `lf`; `order_reviews` và `category_translation` là `crlf`. Không có file `mixed` |
| BOM | `product_category_name_translation.csv` có BOM UTF-8. DuckDB đọc đúng tên cột đầu (header khớp), nhưng đây là điểm cần giữ trong tầng bronze |
| Ký tự ngoài ASCII | Có ở `geolocation` (160.464 byte), `order_reviews` (110.640 byte), `sellers` (6), `category_translation` (3). Nội dung tiếng Bồ Đào Nha có dấu, không phải lỗi |

## 3. Khóa

| Bảng | Khóa | Duy nhất | Kết luận |
|---|---|---|---|
| `customers` | `customer_id` | 100% | Khóa đúng |
| `customers` | `customer_unique_id` | **96,64%** (96.096 / 99.441), 2.997 nhóm trùng | **Không phải khóa** của khách thật; một khách có thể có nhiều `customer_id` |
| `orders` | `order_id` | 100% | Khóa đúng |
| `order_items` | (`order_id`, `order_item_id`) | 100% | Khóa đúng |
| `order_payments` | (`order_id`, `payment_sequential`) | 100% | Khóa đúng |
| `order_reviews` | `review_id` | **99,18%**, 789 nhóm trùng (1.603 dòng), tối đa 3 dòng/nhóm | **Không phải khóa** (xem mục 6, F-2) |
| `order_reviews` | (`review_id`, `order_id`) | 100% | Khóa tổ hợp đúng |
| `products` | `product_id` | 100% | Khóa đúng |
| `sellers` | `seller_id` | 100% | Khóa đúng |
| `category_translation` | `product_category_name` | 100% | Khóa đúng |
| `geolocation` | (zip, lat, lng) | 72,0% (720.154 / 1.000.163) | Không có khóa tự nhiên. Xem mục 4 |

## 4. Quan hệ

| Quan hệ | Dòng con | Mồ côi | Khớp | Ghi chú |
|---|---|---|---|---|
| `orders` → `customers` | 99.441 | 0 | 100% | N-1 |
| `order_items` → `orders` | 112.650 | 0 | 100% | 775 đơn không có dòng hàng nào (xem F-4) |
| `order_items` → `products` | 112.650 | 0 | 100% | |
| `order_items` → `sellers` | 112.650 | 0 | 100% | |
| `order_payments` → `orders` | 103.886 | 0 | 100% | 1 đơn không có thanh toán |
| `order_reviews` → `orders` | 99.224 | 0 | 100% | 768 đơn không có đánh giá |
| `products` → `category_translation` | 32.951 | **623** | 98,11% | 610 sản phẩm có danh mục rỗng; 13 sản phẩm có danh mục không có bản dịch |
| `customers` → `geolocation` (theo zip) | 99.441 | **278** | 99,72% | Quan hệ theo tiền tố zip, không có khóa duy nhất ở phía cha |
| `sellers` → `geolocation` (theo zip) | 3.095 | **7** | 99,77% | Như trên |

Các quan hệ theo zip: phía cha `geolocation` không duy nhất theo tiền tố zip (`parent_key_unique = False`), nên một khóa cha có nhiều dòng tọa độ. Đây là đặc tính của dữ liệu, không phải lỗi, nhưng nó làm **phép nối theo zip có thể nhân số dòng**. Phải dùng tổng hợp (ví dụ trung bình tọa độ theo zip) trước khi nối.

## 5. Các kiểm tra nghiệp vụ

### 5.1 Thanh toán so với tổng hàng + phí vận chuyển (FR-05)

Phép so: tổng `price` + `freight_value` theo đơn so với tổng `payment_value` theo đơn, trên 98.665 đơn có cả hai.

| Chỉ số | Giá trị |
|---|---|
| Đơn có lệch lớn hơn 0,01 | **380** (0,385%) |
| Trong số đó: thanh toán lớn hơn | 291 |
| Trong số đó: thanh toán nhỏ hơn | 89 |
| Trong số đơn lệch, có trả góp (`payment_installments` > 1) | **313** (82,4%) |
| Trong toàn bộ đơn có cả hai, có trả góp | 50.840 (51,5%) |

**Đối chiếu với số của bên thứ ba:** một bài phân tích khác đã nêu 576 đơn lệch, và 76,7% trong số đó trả góp. Phép đo của mình với ngưỡng 0,01 cho **380 đơn** và 82,4% trả góp. **Không tái tạo được con số 576** bằng phương pháp này. Có thể khác ngưỡng sai số hoặc cách gom đơn. Vì vậy số 576 không được dùng trong tài liệu chính thức.

**Nguyên nhân:** giả thuyết trả góp (có phí lãi) rất hợp lý vì lệch tập trung ở đơn trả góp, nhưng **INSUFFICIENT EVIDENCE**. Bộ dữ liệu không có cột lãi suất hay phí trả góp, nên không thể chứng minh. Đây chính là dạng ambiguity mà FR-05 cần hỏi lại Engineer.

### 5.2 Giá trị thanh toán

| Loại thanh toán | Số dòng | Giá trị không dương |
|---|---|---|
| `boleto` | 19.784 | 0 |
| `credit_card` | 76.795 | 0 |
| `debit_card` | 1.529 | 0 |
| `voucher` | 5.775 | **6** |
| `not_defined` | 3 | **3** |

Có 9 dòng thanh toán với giá trị không dương. Chỉ 3 dòng `not_defined` và 6 dòng `voucher` là đối tượng kiểm thử; cần xác nhận có phải lỗi hay là khuyến mãi/hoàn tiền hợp lệ.

### 5.3 Phí vận chuyển và giá

| Kiểm tra | Kết quả |
|---|---|
| `price` <= 0 | 0 |
| `freight_value` < 0 | 0 |
| `freight_value` = 0 | **383** dòng hàng (hợp lệ, không coi là lỗi; ca đối chứng) |

### 5.4 Ngày và trạng thái đơn

| Kiểm tra | Kết quả |
|---|---|
| Giao hàng trước khi đặt đơn | 0 |
| Đơn `delivered` thiếu ngày giao cho khách | **8** trên 96.478 |
| Đơn `canceled` thiếu ngày giao | 619 trên 625 (hợp lệ: đơn bị hủy không giao) |
| Đơn `canceled` thiếu ngày duyệt | 141 |
| Đơn `created` thiếu ngày duyệt | 5 trên 5 |

Trạng thái và ngày khớp logic nghiệp vụ, trừ 8 đơn `delivered` thiếu ngày giao. Đây là ứng viên tốt cho ràng buộc "đơn đã giao phải có ngày giao", nhưng cần duyệt trước vì 8 dòng có thể là dữ liệu thật.

### 5.5 Số dòng hàng trên mỗi đơn

Không có đơn nào có số thứ tự dòng hàng bị gián đoạn (`order_item_sequence_gaps = 0`).

## 6. Phát hiện cần quyết định

| # | Phát hiện | Bằng chứng | Quyết định đề xuất | Ai duyệt |
|---|---|---|---|---|
| F-1 | `customer_unique_id` không phải khóa khách thật | 96,64% duy nhất; 2.997 nhóm trùng; 96,9% khách có đúng 1 đơn | Dùng `customer_unique_id` làm khóa khách trong dim; không dùng `customer_id` để đếm khách | Cổng 1 |
| F-2 | `review_id` không phải khóa | 789 nhóm trùng, tối đa 3 dòng; khóa (`review_id`, `order_id`) duy nhất 100% | Khóa đánh giá là (`review_id`, `order_id`). Đây là **ca khóa giả** cho FR-03 | Cổng 1 |
| F-3 | Lệch thanh toán so với hàng + phí | 380 đơn; 82,4% trả góp; nguyên nhân chưa biết | Hỏi Engineer (FR-05): `payment_value` là tổng đã gồm lãi trả góp hay không. Không tự cộng/trừ | Cổng 1 (câu hỏi bắt buộc) |
| F-4 | Đơn không có dòng hàng, thanh toán, đánh giá | 775 / 1 / 768 đơn | Giữ đơn; không coi là lỗi FK. Đây là đặc tính (đơn hủy không có dòng hàng) | Cổng 1 |
| F-5 | Dòng `geolocation` trùng theo tọa độ nhưng khác thành phố | 261.831 dòng trùng hoàn toàn (26,2%); 19.015 tiền tố zip; 720.154 bộ (zip, lat, lng) | Không dùng `geolocation` làm dim trực tiếp; tổng hợp theo zip trước khi nối | Cổng 1 |
| F-6 | Danh mục sản phẩm có vấn đề | 610 sản phẩm không có danh mục; 13 sản phẩm có danh mục không có bản dịch | Giữ NULL; ghi nhận số lượng; không tự gán danh mục | Cổng 1 |
| F-7 | 8 đơn `delivered` thiếu ngày giao | 8 / 96.478 | Ca kiểm thử ràng buộc "đã giao phải có ngày giao"; chờ duyệt | Cổng 1 |
| F-8 | 9 dòng thanh toán không dương | 3 `not_defined`, 6 `voucher` | Cần xác nhận có phải lỗi | Cổng 1 |

## 7. Những thay đổi so với tài liệu trước

| Tài liệu trước ghi | Đo được bây giờ |
|---|---|
| `review_id` có thể không duy nhất (Suy luận) | **Xác nhận**: 789 nhóm trùng |
| 576 đơn lệch thanh toán (Nguồn thứ ba) | **Không tái tạo được**; đo được 380 với ngưỡng 0,01 |
| Tổng khoảng 1,3 triệu dòng (Nguồn thứ ba) | **1.550.922 dòng** |
| `customer_unique_id` là khóa khách (Suy luận) | **Sai**: 96,64% duy nhất |
| Thiếu giá trị ở 3 bảng chính (Nguồn thứ ba) | **Sai một phần.** Nội dung đánh giá thiếu nhiều: `review_comment_title` 88,34%, `review_comment_message` 58,71%. Ngày giao cho khách thiếu 2,98%; danh mục và kích thước sản phẩm thiếu 1,85% |

## 8. Việc còn lại

| # | Việc | Điều kiện hoàn thành |
|---|---|---|
| 1 | Nhóm duyệt F-1 đến F-8 | Mỗi mục có Approved hoặc Rejected |
| 2 | Hỏi Engineer về F-3 | Có câu trả lời về `payment_value` và trả góp |
| 3 | Viết data dictionary tiếng Việt cho 9 bảng | Mỗi cột có nhãn độ chắc chắn |
| 4 | Viết danh mục lỗi tiêm cho Olist (dùng cấu trúc OULAD) | Có các lỗi FR-05, khóa giả, mồ côi |
| 5 | Đối chiếu mô tả gốc của Olist để xác nhận ý nghĩa cột | Nâng nhãn "Suy luận" lên "Đã xác nhận" |
