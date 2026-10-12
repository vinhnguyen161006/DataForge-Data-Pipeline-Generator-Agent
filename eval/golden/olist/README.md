# Olist Golden Dataset

**Trạng thái:** `v0.4-draft`. Đã tải, giải nén, profiling đầy đủ 9 file (1.550.922 dòng), báo cáo chất lượng và data dictionary tiếng Việt (`dictionary/data_dictionary.md`). Chưa có thiết kế chuẩn và danh mục lỗi cho Olist.

## 1. Nguồn gốc (provenance)

| Mục | Giá trị | Độ chắc chắn |
|---|---|---|
| Tên | Brazilian E-Commerce Public Dataset by Olist | Confirmed (trang Kaggle) |
| Đơn vị công bố | Olist (đăng trên Kaggle) | Confirmed |
| Trang tải | https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce (cần tài khoản Kaggle) | Confirmed |
| Giấy phép | CC BY-NC-SA 4.0: phải ghi nguồn, **phi thương mại**, sản phẩm phái sinh phải cùng giấy phép | Confirmed (ảnh chụp mục License trên trang) |
| Mô tả theo nguồn | Thông tin khoảng 100.000 đơn hàng từ 2016 đến 2018 tại nhiều marketplace ở Brazil; dữ liệu thương mại thật đã ẩn danh; tên công ty và đối tác trong nội dung đánh giá đã thay bằng tên các dòng họ trong Game of Thrones | Confirmed |
| Tần suất cập nhật dự kiến | Never (dữ liệu tĩnh) | Confirmed |
| Ngày tải | 08/10/2026 | Confirmed |
| Tên file zip | `archive.zip` | Confirmed |
| Kích thước zip | 44.717.580 byte | Confirmed |
| SHA-256 của zip | `967e41e04fc306fe604e2a693f488995a8b41e5047418f8a5c8e4abd6deca784` | Confirmed (chép từ ảnh chụp màn hình; cần đối chiếu lại bằng copy/paste) |
| DOI trích dẫn | 10.34740/KAGGLE/DSV/195341 | Needs validation (chưa đối chiếu trên trang) |

Mọi file trong zip có ngày sửa đổi 01/10/2021 (Needs validation: chưa đối chiếu với phiên bản trên Kaggle).

## 2. Cấu trúc thư mục

```text
eval/golden/olist/
├── raw/            9 file CSV, giữ nguyên byte như tải về, không sửa
├── metadata/       source_manifest.json, profile_report.json, data_quality_report.md
├── dictionary/     data_dictionary.md
├── model/          canonical design (chưa có)
├── expected/       kết quả chuẩn (chưa có)
├── errors/         danh mục lỗi tiêm (chưa có)
└── README.md

eval/golden/tools/  profile_dataset.py, configs/olist.json
```

## 3. Chín file trong `raw/`

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
| **Tổng** | **1.550.922** | **126.186.995** (khoảng 120,3 MiB) | |

Mọi số liệu lấy từ `metadata/source_manifest.json` (lần chạy đầy đủ ngày 09/10/2026, DuckDB 1.5.5). Số dòng `orders` (99.441) khớp mô tả công khai khoảng 100.000 đơn.

## 4. Kết quả chính (chi tiết: `metadata/data_quality_report.md`)

- 9/9 file đúng header, UTF-8; `order_reviews` và `category_translation` dùng CRLF, các file còn lại dùng LF; `category_translation` có BOM UTF-8.
- `review_id` **không phải khóa**: 789 nhóm trùng; khóa đúng là (`review_id`, `order_id`).
- `customer_unique_id` không phải khóa khách thật (duy nhất 96,64%).
- 380 đơn có tổng `payment_value` khác tổng `price` + `freight_value` (ngưỡng 0,01); 82,4% trong số đó trả góp. Nguyên nhân chưa chứng minh được (INSUFFICIENT EVIDENCE); đây là câu hỏi cho FR-05. Con số 576 của một bài phân tích bên thứ ba **không tái tạo được**.
- `geolocation` không có khóa tự nhiên; 26,2% dòng trùng hoàn toàn.
- Mọi quan hệ khóa ngoại giữa các bảng giao dịch khớp 100%; quan hệ theo zip và theo danh mục sản phẩm có một số dòng không khớp.

## 5. Quy tắc bắt buộc theo giấy phép

- Không dùng dữ liệu cho mục đích thương mại.
- Sản phẩm phái sinh (từ điển dữ liệu, bảng kết quả chuẩn, danh mục lỗi sinh từ dữ liệu này) phải phát hành cùng giấy phép CC BY-NC-SA 4.0 và ghi nguồn Olist, Kaggle.
- Không đưa dữ liệu Olist vào gói xuất (ZIP) của DataForge.

## 6. Git

Tổng `raw/` khoảng 120,3 MiB; file lớn nhất `olist_geolocation_dataset.csv` khoảng 58,4 MiB, không vượt giới hạn 100 MB mỗi file của GitHub. Dù vậy, không nên commit `raw/` khi chưa có quyết định của chủ repo và nhóm về giấy phép. Loại trừ bằng `.git/info/exclude` hoặc `.gitignore`.

## 7. Cách chạy lại profiling

Chạy ở thư mục gốc repo, trong môi trường dự án có DuckDB đã ghim (không cài thêm gói):

```bash
python eval/golden/tools/profile_dataset.py --config eval/golden/tools/configs/olist.json --max-rows 1000
python eval/golden/tools/profile_dataset.py --config eval/golden/tools/configs/olist.json
```

Hai file kết quả nằm ở `eval/golden/olist/metadata/`. Lần chạy `--max-rows 1000` chỉ để bắt lỗi script sớm; mẫu 1.000 dòng cho tỉ lệ mồ côi rất cao vì các bảng không chứa cùng các đơn hàng, nên không dùng cho kết luận.

## 8. Điều kiện hoàn thành

- [x] 9 CSV đủ, header khớp, số dòng và SHA-256 từng file đã ghi.
- [x] Profiling đầy đủ: 14/14 truy vấn chẩn đoán chạy không lỗi.
- [x] Báo cáo chất lượng với số đo thật.
- [ ] Đối chiếu lại SHA-256 của zip bằng copy/paste.
- [ ] Nhóm duyệt F-1 đến F-8 (`metadata/data_quality_report.md` mục 6).
- [ ] Trả lời câu hỏi F-3 (`payment_value` có gồm lãi trả góp không) từ Engineer.
- [x] Data dictionary tiếng Việt cho 9 bảng (52 cột), có nhãn độ chắc chắn. Ý nghĩa cột còn là `Suy luận`.
- [ ] Danh mục lỗi tiêm cho Olist (dùng cấu trúc của OULAD).
- [ ] Đối chiếu mô tả gốc của Olist để xác nhận ý nghĩa cột.
