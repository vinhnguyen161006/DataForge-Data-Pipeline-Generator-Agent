# Chọn 2 golden dataset công khai bổ sung cho OULAD (v0.1)

**Trạng thái:** `DRAFT`, Deliverable C, Tuần 1. Chưa được Tuấn xác nhận và chưa tải/đo dữ liệu thật của bất kỳ ứng viên nào.
**Kết luận đề xuất:** chọn **Olist Brazilian E-Commerce** và **TPC-H (sinh bằng DuckDB)**. Loại **Chinook**.

## 0. Cách đọc tài liệu này

Mọi mệnh đề được gắn nhãn nguồn:

| Nhãn | Nghĩa |
|---|---|
| `Đã xác nhận (nguồn)` | Đọc được trong kết quả tìm kiếm ở phiên làm việc này; có ghi nguồn |
| `Nguồn thứ ba` | Lấy từ bài phân tích của người khác; chưa kiểm chứng độc lập |
| `Suy luận` | Từ hiểu biết chung về dataset, chưa đo; cần xác minh sau khi tải về |

**Chưa có con số nào dưới đây được đo từ file thật** của Olist, TPC-H hay Chinook. Các số lượng dòng ghi "xấp xỉ" là phỏng đoán cần đo lại bằng script profiling trước khi đưa vào tài liệu chính thức.

---

## 1. Yêu cầu của Task 2 (nhắc lại)

Dataset được chọn phải: có nhiều bảng hoặc mô hình hóa được thành nhiều bảng; có khóa ghép hoặc khóa liên kết; có quan hệ một-nhiều; đủ lớn để kiểm thử nhưng chạy được trên máy dev; hợp với Data Warehouse + dbt; dễ tái tạo; có giấy phép rõ hoặc nguồn công khai đáng tin; **ít nhất một dataset có trường mơ hồ** kiểu `amount`, `value`, `quantity`, `price` để kiểm thử FR-05. Ưu tiên khả năng kiểm thử DataForge, không ưu tiên độ nổi tiếng.

---

## 2. Ba ứng viên và đánh giá 12 câu hỏi

### 2.1 Ứng viên A: Olist Brazilian E-Commerce Public Dataset

| # | Câu hỏi | Trả lời | Nhãn |
|---|---|---|---|
| 1 | Dataset là gì? | Dữ liệu đơn hàng thật của sàn Olist, khoảng 100.000 đơn từ 2016 đến 2018 trên nhiều marketplace ở Brazil | Đã xác nhận (Kaggle) |
| 2 | Nguồn | https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce (cần tài khoản Kaggle để tải); DOI trích dẫn: 10.34740/KAGGLE/DSV/195341 | Đã xác nhận (Kaggle, Zenodo) |
| 3 | Có những bảng nào? | 9 bảng: customers, geolocation, order_items, order_payments, order_reviews, orders, products, sellers, product_category_name_translation | Đã xác nhận (Kaggle, GitHub) |
| 4 | Grain từng bảng | `orders`: một đơn hàng. `order_items`: một dòng hàng trong đơn. `order_payments`: một lần/phần thanh toán của đơn. `order_reviews`: một đánh giá. `customers`: một mã khách trên một đơn. `products`, `sellers`: một sản phẩm, một người bán. `geolocation`: một bản ghi tọa độ theo tiền tố mã bưu chính, không có khóa. `product_category_name_translation`: một danh mục | Suy luận |
| 5 | PK / FK | `orders.order_id` PK; `orders.customer_id` → `customers`; `order_items` PK ghép (`order_id`, `order_item_id`), FK tới `orders`, `products`, `sellers`; `order_payments` PK ghép (`order_id`, `payment_sequential`), FK tới `orders`; `order_reviews.order_id` → `orders` | Suy luận |
| 6 | Quan hệ 1-N | `orders` 1-N `order_items`; `orders` 1-N `order_payments`; `orders` 1-N `order_reviews`; `products` 1-N `order_items`; `sellers` 1-N `order_items` | Suy luận |
| 7 | Vấn đề dữ liệu dùng để kiểm thử | Xem mục 2.1.1 | Hỗn hợp |
| 8 | Kích thước | `orders` có 99.441 đơn (Nguồn thứ ba); tổng khoảng 1,3 triệu dòng trên 9 bảng (Nguồn thứ ba), phần lớn là `geolocation`. Dung lượng file chưa đo | Nguồn thứ ba, Suy luận |
| 9 | Chạy được trên máy dev? | Có: cùng cỡ với OULAD (OULAD là 10,6 triệu dòng, 443 MiB) hoặc nhỏ hơn | Suy luận |
| 10 | Hợp làm golden? | Có; xem mục 3 | Đánh giá |
| 11 | Tình huống FR kiểm thử được | FR-01 đến FR-05, FR-08, FR-16, FR-17 (xem mục 4) | Đánh giá |
| 12 | Rủi ro | Giấy phép CC BY-NC-SA 4.0: cấm dùng thương mại, bắt buộc ghi nguồn, sản phẩm phái sinh phải cùng giấy phép. Phải đăng nhập Kaggle để tải. Rủi ro rò rỉ mức trung bình vì rất phổ biến trong các bài phân tích | Đã xác nhận (giấy phép, Kaggle) |

#### 2.1.1 Vấn đề dữ liệu có thể dùng để kiểm thử

| Vấn đề | Chi tiết | Nhãn |
|---|---|---|
| **Cột mơ hồ `payment_value`, `price`, `freight_value`** | Một phân tích của bên thứ ba cho thấy 576 đơn (0,58% đơn có mặt ở cả hai phía) có tổng thanh toán khác tổng `price` + `freight_value`; 76,7% trong số đó trả góp so với 51,5% toàn bộ đơn. Tác giả nêu giả thuyết do lãi trả góp và nói rõ dữ liệu không chứa lãi suất. Đây chính là loại mơ hồ "số tiền này là gì" của FR-05 | Nguồn thứ ba |
| `customer_id` và `customer_unique_id` | Mã khách hàng thay đổi theo đơn; mã định danh một khách thật là cột khác. Một bài phân tích ghi bảng `customers` dùng để nhận diện khách duy nhất. Sai khóa sẽ làm sai đếm khách | Nguồn thứ ba, Suy luận |
| Thiếu giá trị | Một bài phân tích ghi thiếu dữ liệu ở 3 bảng chính, phần lớn là bình luận đánh giá bị bỏ trống; hầu hết bảng còn lại "sạch" và toàn vẹn logic mạnh | Nguồn thứ ba |
| `geolocation` không có khóa | Nhiều dòng cho cùng một tiền tố mã bưu chính. Tương tự `studentVle` ở OULAD | Suy luận |
| Tên cột có lỗi chính tả (ví dụ `product_name_lenght`) | Kiểm tra bộ chuẩn hóa tên | Suy luận |
| Tên danh mục tiếng Bồ Đào Nha, bảng dịch riêng | Một bài phân tích ghi nhận điều này; cần phép nối với bảng dịch | Nguồn thứ ba |
| `review_id` có thể không duy nhất | Cần đo; nếu đúng, là ca "khóa ứng viên giả" | Suy luận |

---

### 2.2 Ứng viên B: TPC-H (sinh bằng DuckDB `tpch` extension)

| # | Câu hỏi | Trả lời | Nhãn |
|---|---|---|---|
| 1 | Dataset là gì? | Bộ dữ liệu tổng hợp của benchmark hỗ trợ ra quyết định TPC-H; DuckDB có extension `tpch` sinh dữ liệu bằng `CALL dbgen(sf = 1)` | Đã xác nhận (tài liệu DuckDB) |
| 2 | Nguồn | https://duckdb.org/docs/stable/core_extensions/tpch ; đặc tả TPC-H của Transaction Processing Performance Council | Đã xác nhận |
| 3 | Có những bảng nào? | 8 bảng: region, nation, supplier, customer, part, partsupp, orders, lineitem | Suy luận (kiến thức đặc tả TPC-H) |
| 4 | Grain từng bảng | `lineitem`: một dòng của một đơn. `orders`: một đơn. `partsupp`: một cặp (sản phẩm, nhà cung cấp). Các bảng còn lại: một thực thể | Suy luận |
| 5 | PK / FK | `lineitem` PK ghép (`l_orderkey`, `l_linenumber`); `partsupp` PK ghép (`ps_partkey`, `ps_suppkey`); `lineitem` có khóa ngoại ghép (`l_partkey`, `l_suppkey`) → `partsupp` | Suy luận |
| 6 | Quan hệ | 1-N: `orders` → `lineitem`, `customer` → `orders`, `nation` → `customer`/`supplier`, `region` → `nation`. N-N giữa `part` và `supplier` qua bảng trung gian `partsupp` | Suy luận |
| 7 | Vấn đề dữ liệu dùng để kiểm thử | Dữ liệu sạch và toàn vẹn tuyệt đối; **không** có lỗi tự nhiên để thử bộ test. Tên cột viết tắt khó hiểu (`l_extendedprice`, `l_discount`, `l_tax`); `l_extendedprice` là kết hợp số lượng và giá, một ví dụ của cột mà tên không nói hết nghĩa | Suy luận |
| 8 | Kích thước | Điều chỉnh được bằng hệ số `sf`. Với `sf = 1`, tài liệu bên thứ ba nói khoảng 1 GB CSV (Apache DataFusion). Số dòng cụ thể chưa đo | Đã xác nhận (DataFusion README), Suy luận |
| 9 | Chạy được trên máy dev? | Có: `sf = 0,1` rất nhỏ, `sf = 1` vẫn vừa một máy dev | Suy luận |
| 10 | Hợp làm golden? | Có, nhưng ở vai trò khác OULAD/Olist; xem mục 3 | Đánh giá |
| 11 | Tình huống FR kiểm thử được | FR-03, FR-07, FR-11, FR-12, FR-14, FR-16, FR-18 | Đánh giá |
| 12 | Rủi ro | Giấy phép và thuật ngữ (mục 5); rò rỉ **cao** vì TPC-H xuất hiện khắp nơi trong dự án mã nguồn mở và có thể nằm trong dữ liệu huấn luyện của LLM | Đã xác nhận (fair use), Đánh giá |

**Điểm đặc biệt có giá trị:** DuckDB cung cấp hàm `tpch_answers()` trả về đáp án chuẩn của 22 truy vấn cho `sf` = 0,01; 0,1 và 1. Đây là **bảng kết quả chuẩn có sẵn**, không cần viết tay (Đã xác nhận, tài liệu DuckDB).

---

### 2.3 Ứng viên C: Chinook

| # | Câu hỏi | Trả lời | Nhãn |
|---|---|---|---|
| 1 | Dataset là gì? | Cơ sở dữ liệu mẫu của một cửa hàng nhạc số, hay dùng thay Northwind | Đã xác nhận (nhiều tài liệu hướng dẫn) |
| 2 | Nguồn | https://github.com/lerocha/chinook-database ; tập lệnh ghi giấy phép tại một địa chỉ CodePlex cũ | Đã xác nhận |
| 3 | Có những bảng nào? | 11 bảng: Album, Artist, Customer, Employee, Genre, Invoice, InvoiceLine, MediaType, Playlist, PlaylistTrack, Track | Đã xác nhận (nhiều nguồn) |
| 4 | Grain | `InvoiceLine`: một dòng hàng của hóa đơn; `Invoice`: một hóa đơn; `PlaylistTrack`: một bài trong một playlist | Suy luận |
| 5 | PK / FK | Có FK như `InvoiceLine.InvoiceId` → `Invoice`, `InvoiceLine.TrackId` → `Track`; `PlaylistTrack` khóa ghép | Đã xác nhận (một phần), Suy luận |
| 6 | Quan hệ 1-N | `Customer` 1-N `Invoice`, `Invoice` 1-N `InvoiceLine` | Đã xác nhận |
| 7 | Vấn đề dữ liệu | `UnitPrice` và `Quantity` ở `InvoiceLine` nhưng cũng có `UnitPrice` ở `Track`; mức mơ hồ thấp | Đã xác nhận (lược đồ), Đánh giá |
| 8 | Kích thước | Rất nhỏ (cỡ vài nghìn đến mươi nghìn dòng; chưa đo) | Suy luận |
| 9 | Chạy được trên máy dev? | Có, nhưng quá nhỏ để đo hiệu năng | Suy luận |
| 10 | Hợp làm golden? | Không | Đánh giá |
| 11 | Tình huống FR | FR-01 đến FR-04 ở mức cơ bản; không kiểm thử được FR-11, FR-12 | Đánh giá |
| 12 | Rủi ro | **Giấy phép không xác nhận được**: tập lệnh trỏ tới địa chỉ giấy phép CodePlex cũ, và chỉ một nguồn thứ ba mô tả là "permissive". Rò rỉ cao: Chinook xuất hiện trong nhiều hướng dẫn text-to-SQL (LangChain, Mistral, GridGain...) | Đã xác nhận |

---

## 3. So sánh và quyết định

### 3.1 Chấm điểm theo tiêu chí của Task 2

Thang 0 đến 2 (0 không đạt, 1 đạt một phần, 2 đạt). Điểm là đánh giá của mình dựa trên bằng chứng ở mục 2, không phải số đo; nhóm có thể đổi trọng số.

| Tiêu chí | Olist | TPC-H | Chinook |
|---|---|---|---|
| Nhiều bảng (từ 5 bảng) | 2 (9 bảng) | 2 (8 bảng) | 2 (11 bảng) |
| Khóa ghép / khóa liên kết | 2 | 2 | 1 (chủ yếu `PlaylistTrack`) |
| Quan hệ một-nhiều | 2 | 2 | 2 |
| Đủ lớn nhưng chạy được trên máy dev | 2 | 2 (chỉnh được `sf`) | 0 (quá nhỏ để đo hiệu năng) |
| Hợp Data Warehouse + dbt | 2 | 2 | 1 |
| Dễ tái tạo môi trường | 1 (cần tài khoản Kaggle) | 2 (sinh bằng DuckDB, xác định) | 2 |
| Giấy phép rõ | 2 (CC BY-NC-SA 4.0, nhưng hạn chế) | 1 (EULA và fair-use, ràng buộc cách gọi tên) | 0 (không xác nhận được) |
| Có cột mơ hồ cho FR-05 | 2 | 1 | 1 |
| Có lỗi dữ liệu thật để thử bộ test | 2 | 0 (sạch tuyệt đối) | 0 |
| Có đáp án chuẩn sẵn | 0 (phải viết tay) | 2 (`tpch_answers()`) | 0 |
| Ít nguy cơ rò rỉ | 1 | 0 | 0 |
| **Tổng (tối đa 22)** | **18** | **16** | **9** |

### 3.2 Bảng so sánh theo định dạng yêu cầu

| Dataset | Điểm mạnh | Điểm yếu | Quan hệ | Khóa ghép | Cột mơ hồ | Kích thước | Khả năng kiểm thử | Quyết định |
|---|---|---|---|---|---|---|---|---|
| **Olist** | Dữ liệu thật, có lỗi tự nhiên; có cột tiền mơ hồ; có khác biệt `customer_id`/`customer_unique_id` | Giấy phép phi thương mại; không có đáp án chuẩn; cần tài khoản Kaggle | 1-N từ `orders` sang `order_items`, `order_payments`, `order_reviews`; N-1 sang `customers` | `order_items` (`order_id`, `order_item_id`); `order_payments` (`order_id`, `payment_sequential`) | `payment_value` so với `price` + `freight_value` | 99.441 đơn; khoảng 1,3 triệu dòng tổng (chưa đo) | FR-01 đến FR-05, FR-08, FR-16, FR-17 | **CHỌN** |
| **TPC-H** | Đáp án chuẩn có sẵn cho 22 truy vấn; sinh xác định; co giãn được kích thước; dùng được cho đo hiệu năng | Dữ liệu tổng hợp, sạch, không có lỗi tự nhiên; ràng buộc về cách gọi tên; rò rỉ cao | 1-N nhiều tầng; N-N `part`-`supplier` qua `partsupp` | `lineitem` (`l_orderkey`, `l_linenumber`); `partsupp` (`ps_partkey`, `ps_suppkey`) | Tên cột viết tắt; `l_extendedprice` | Chỉnh bằng `sf`; khoảng 1 GB CSV tại `sf` = 1 | FR-03, FR-07, FR-11, FR-12, FR-14, FR-16, FR-18 | **CHỌN** |
| Chinook | Nhỏ, dễ dùng, nhiều bảng | Quá nhỏ cho đo hiệu năng; giấy phép không xác nhận được; rò rỉ cao | 1-N | `PlaylistTrack` | Mức thấp | Rất nhỏ | FR-01 đến FR-04 cơ bản | LOẠI |

### 3.3 Quyết định: Olist và TPC-H

**Vì sao (Why):** hai dataset bổ sung cho nhau và cùng bổ sung cho OULAD.

| Vai trò | OULAD | Olist | TPC-H |
|---|---|---|---|
| Lĩnh vực | Giáo dục | Thương mại điện tử | Bán hàng tổng hợp |
| Bản chất dữ liệu | Thật, có lỗi tự nhiên (dòng lặp, thiếu giá trị) | Thật, có cột mơ hồ | Tổng hợp, sạch |
| Dùng tốt nhất để kiểm thử | Grain, khóa không tự nhiên, quy tắc làm sạch | **FR-05 (hỏi lại)**, khóa ghép, cột tiền | **FR-11, FR-12 (đo hiệu năng và tương đương)**, đáp án chuẩn |

**Bằng chứng (Evidence):** bảng chấm điểm ở mục 3.1; OULAD không có cột tiền, nên chỉ Olist đáp ứng điều kiện bắt buộc về cột mơ hồ (mục 1); chỉ TPC-H có đáp án chuẩn có sẵn cho 22 truy vấn.

**Đánh đổi (Trade-off):**
- Olist giá phải trả là giấy phép phi thương mại và không có đáp án chuẩn, nên Tuấn phải viết bảng kết quả chuẩn bằng tay (đúng với nhiệm vụ của Tuấn).
- TPC-H giá phải trả là dữ liệu quá sạch; chất lượng bộ test phải đo bằng phương pháp tiêm lỗi (đúng với danh mục lỗi tiêm của Tuấn); nguy cơ rò rỉ cao.

**Khuyến nghị (Recommendation):** chọn Olist và TPC-H. Chinook loại vì quá nhỏ và giấy phép không xác nhận được.

---

## 4. Ma trận FR được kiểm thử

| FR | OULAD | Olist | TPC-H |
|---|---|---|---|
| FR-01 Tải CSV | Có | Có | Có (xuất CSV từ DuckDB) |
| FR-02 Hồ sơ | Có | Có | Có |
| FR-03 Khóa và quan hệ | Có; có khóa giả (`studentVle`) | Có; `order_items` khóa ghép; `review_id` khóa giả cần đo | Có; khóa ghép và khóa ngoại ghép |
| FR-04 Thiết kế | Có | Có | Có |
| FR-05 Hỏi lại | Có (Q1) | **Chính**: `payment_value` | Phụ: tên cột viết tắt |
| FR-07, FR-08 Mã và test | Có | Có | Có |
| FR-11 Đo hiệu năng | Có (10,6 triệu dòng) | Hạn chế | **Chính**: co giãn bằng `sf` |
| FR-12 Rewrite tương đương | Có | Hạn chế | **Chính**: 22 truy vấn có đáp án |
| FR-14, FR-15 Công bố, dashboard | Có | Có | Phụ |
| FR-16 Chạy lại không nhân đôi | Có | Có | Có |
| FR-17 Đổi schema | Dùng bản có cột thêm | Dùng bản có cột thêm | Dùng bản có cột thêm |
| FR-18 Xuất ZIP | Có | Có | Có |

---

## 5. Rủi ro giấy phép và rò rỉ

| Rủi ro | Mức | Xử lý đề xuất |
|---|---|---|
| Olist là CC BY-NC-SA 4.0: không dùng thương mại; bắt buộc ghi nguồn; sản phẩm phái sinh (từ điển dữ liệu, bảng kết quả chuẩn) phải cùng giấy phép | Trung bình | Ghi rõ giấy phép và trích dẫn trong `README.md` của dataset; xác nhận với nhóm rằng dự án chỉ dùng phi thương mại; không phát hành dữ liệu Olist trong gói xuất của DataForge |
| TPC-H: chỉ thành viên TPC được công bố kết quả benchmark chính thức; sản phẩm phái sinh phải gọi là "derived from TPC-H" | Trung bình | Không công bố kết quả dưới tên "TPC-H"; dùng nhãn "derived from TPC-H" trong mọi tài liệu và báo cáo; không so sánh với kết quả chính thức. Cần đọc kỹ chính sách fair-use của TPC trước khi công bố |
| Giấy phép của mã sinh dữ liệu TPC-H qua DuckDB | Chưa xác nhận | Đọc điều khoản của extension trước khi đưa vào gói xuất |
| Rò rỉ: TPC-H, Chinook phổ biến trong dự án dbt/SQL mã nguồn mở, có thể có trong kho mẫu Qdrant | Cao với TPC-H | Gắn thẻ `dataset` cho mọi mẫu trong kho và dùng tham số `exclude_datasets` khi chấm; phối hợp với người phụ trách retrieval |
| Rò rỉ qua bộ nhớ của LLM | Không loại bỏ được | Dùng TPC-H cho việc kiểm chứng máy móc (so sánh tương đương, đo hiệu năng), không dùng làm thước đo chất lượng thiết kế do LLM sinh; chất lượng thiết kế đo bằng OULAD và Olist |
| Phải đăng nhập Kaggle để tải Olist | Thấp | Ghi SHA-256 của file zip, ngày tải và nguồn vào README như đã làm với OULAD |
| TPC-H cần cài extension `tpch` lần đầu | Thấp | Cài trước khi cần dùng offline; ghi phiên bản DuckDB đã dùng |

---

## 6. Việc cần làm tiếp

| # | Việc | Ai | Điều kiện hoàn thành |
|---|---|---|---|
| 1 | Tuấn xác nhận chọn Olist và TPC-H | Tuấn | Có xác nhận |
| 2 | Tải Olist, ghi SHA-256, giải nén vào `eval/golden/olist/raw/` | Tuấn | Có `source_manifest.json` |
| 3 | Tổng quát hóa `profile_oulad.py` thành script nhận cấu hình bảng/khóa (hiện cố định cho OULAD) | Claude | Chạy được trên Olist |
| 4 | Profiling Olist, xác nhận: số dòng, khóa ghép, `review_id`, `payment_value` so với `price` + `freight_value`, `customer_unique_id` | Tuấn và Claude | Có `profile_report.json` |
| 5 | Sinh TPC-H bằng DuckDB ở `sf` = 0,1 (dev) và `sf` = 1 (đo hiệu năng), ghi phiên bản DuckDB và hash dữ liệu | Tuấn | Có hash cố định cho từng `sf` |
| 6 | Đọc chính sách fair-use của TPC và điều khoản extension | Tuấn | Có kết luận trong README |
| 7 | Báo người phụ trách retrieval về `exclude_datasets` cho TPC-H | Tuấn | Có xác nhận |

## 7. Tự kiểm tra

| Câu hỏi | Kết quả |
|---|---|
| Có bịa số liệu không? | Không có số nào được đo. Các số chưa kiểm ghi "Suy luận" hoặc "Nguồn thứ ba" |
| Có dataset nào không đáp ứng điều kiện bắt buộc? | Olist đáp ứng điều kiện cột mơ hồ. Bằng chứng về 0,58% là từ bài của bên thứ ba, cần đo lại |
| Có mâu thuẫn không? | TPC-H điểm kiểm thử cao nhưng điểm rò rỉ 0; đã nêu và đặt vai trò kiểm chứng máy móc |
| Có ảnh hưởng module khác không? | Có: kho mẫu retrieval cần gắn thẻ dataset; script profiling cần tổng quát hóa |
| Việc nào cần người khác xác nhận? | Giấy phép TPC-H và extension; nhóm xác nhận dùng phi thương mại cho Olist |

## 8. Nguồn đã tham khảo

- Kaggle, Brazilian E-Commerce Public Dataset by Olist: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce (giấy phép CC BY-NC-SA 4.0 hiển thị trên trang).
- DuckDB, tài liệu extension TPC-H: https://duckdb.org/docs/stable/core_extensions/tpch (hàm `dbgen`, `tpch_answers()`).
- Apache DataFusion Benchmarks README (chính sách fair-use của TPC, thuật ngữ "derived from TPC-H", quy mô khoảng 1 GB ở hệ số 1).
- Lerocha, Chinook Database (tập lệnh ghi giấy phép CodePlex cũ).
- Các bài phân tích của bên thứ ba về Olist: số đơn hàng, tỉ lệ 576 đơn lệch thanh toán, thiếu giá trị ở 3 bảng.
