# OULAD Golden Dataset

**Trạng thái:** `v1.0-draft`. Đã tải, giải nén, profiling đầy đủ 7 file (10,9 triệu dòng) và có tài liệu thiết kế. Chờ nhóm duyệt các phát hiện và quyết định về Git.

## 1. Nguồn gốc (provenance)

| Mục | Giá trị | Độ chắc chắn |
|---|---|---|
| Tên | Open University Learning Analytics Dataset (OULAD) | Confirmed |
| Đơn vị công bố | Knowledge Media Institute, The Open University (UK) | Confirmed |
| Trang mô tả hiện hành | https://research.stem.open.ac.uk/ouanalyse/dataset/ (nút tải trên trang cũ trả về 404) | Confirmed |
| Nguồn thực tế đã tải | figshare, bài của nhóm tác giả: https://figshare.com/articles/dataset/OULAD_Open_University_Learning_Analytics_Dataset/5081998 | Confirmed (theo Tuấn) |
| Giấy phép | CC-BY 4.0 (phải ghi nguồn khi dùng lại) | Confirmed |
| Bài báo mô tả | Kuzilek J., Hlosta M., Zdrahal Z. (2017), Open University Learning Analytics dataset, Scientific Data | Confirmed |
| Quy mô theo nguồn | 22 module-presentation, 32.593 sinh viên, 10.655.280 dòng click VLE | Confirmed (khớp số đo) |
| Ngày tải | 06/10/2026 | Confirmed |
| Tên file zip | `anonymisedData.zip` | Confirmed |
| Kích thước zip | 46.750.706 byte | Confirmed |
| SHA-256 của zip | `90dda45037939953f979072fa70a809ebe07e90ec783c408762af7698a3825ec` | Confirmed (chép từ ảnh chụp màn hình; cần đối chiếu lại bằng copy/paste) |

Bản đăng lại trên Kaggle (zip 44.203.263 byte) có kích thước khác bản figshare, nên **không** dùng làm nguồn.

## 2. Cấu trúc thư mục

```text
eval/golden/oulad/
├── raw/            7 file CSV, giữ nguyên byte như tải về, không sửa
├── metadata/       source_manifest.json, profile_report.json, data_quality_report.md
├── dictionary/     data_dictionary.md
├── model/          canonical_design.md, metrics_and_dashboards.md
├── expected/       bảng kết quả chuẩn (làm ở tuần sau)
├── errors/         error_catalogue.md, error_catalogue.csv
└── README.md

eval/golden/tools/  profile_dataset.py, configs/oulad.json (profile_oulad.py là bản cũ, giữ để đối chiếu)
```

## 3. Bảy file trong `raw/`

| File | Số dòng | Kích thước (byte) | SHA-256 |
|---|---|---|---|
| `courses.csv` | 22 | 526 | `4f16eee7454b15e109b0a21a0e43be820e6846ed6f9301bb7feb5ab5ad737a75` |
| `assessments.csv` | 206 | 8.200 | `8cc738fb88ad760571d6f2a23059bfee0ffcae3bcd830514c9cbd5c6d5a046f1` |
| `vle.csv` | 6.364 | 260.126 | `d1b28303dea802ad87b4484e1196e878e06824850b9a4fe8aa34693439fe87e9` |
| `studentInfo.csv` | 32.593 | 3.461.652 | `7e6f3e474a5eee00639d2a414a6c7e928745823c2d2c2563ca1780145f99b0d6` |
| `studentRegistration.csv` | 32.593 | 1.109.984 | `0d32676285372aaf2e7a80304e5b274b4fba24313e2ca4c04317225e1ec90170` |
| `studentAssessment.csv` | 173.912 | 5.690.310 | `fd5320786328d05af841ee7dd4b5871b9dada3b9fe9d6a3642b2f42635510a6e` |
| `studentVle.csv` | 10.655.280 | 453.836.331 | `52668253d876c5becbcb72185977152700cecab2942aca807fecc3dd54b937f0` |
| **Tổng** | **10.900.970** | **464.367.129** (khoảng 442,9 MiB) | |

Mọi số liệu lấy từ `metadata/source_manifest.json` (lần chạy đầy đủ ngày 08/10/2026, DuckDB 1.5.5).

## 4. Kết quả chính (chi tiết: `metadata/data_quality_report.md`)

- 6/7 bảng có khóa chính duy nhất 100%; `studentVle` **không có khóa tự nhiên** (khóa 5 cột chỉ duy nhất 79,39%).
- 0 dòng mồ côi ở cả 10 quan hệ đã đo.
- Giá trị thiếu luôn là chuỗi rỗng; không có token `?`, `NA`, `NULL`.
- `id_student` không phải khóa riêng: 28.785 sinh viên trên 32.593 lượt học.
- Cả 7 file là UTF-8, không BOM, kết thúc dòng CRLF.

## 5. Quyết định

| # | Quyết định | Đề xuất | Trạng thái |
|---|---|---|---|
| D1 | Tên file trong `raw/` | Giữ nguyên tên gốc (camelCase); tên bảng chuẩn đặt ở lớp `model/` | Chờ Tuấn xác nhận |
| D2 | Chuẩn hóa ở đâu | Không sửa `raw/`; mọi chuẩn hóa là rule trong `dictionary/` và `model/`, áp dụng ở silver | Chờ nhóm duyệt |
| D3 | Có commit `raw/` không | **Không.** `studentVle.csv` nặng 432,8 MiB, vượt giới hạn 100 MB mỗi file của GitHub. Loại trừ bằng `.git/info/exclude` (cục bộ) hoặc `.gitignore` (dùng chung, cần nhóm đồng ý). Chỉ commit manifest, hash và hướng dẫn tải | Chờ chủ repo |
| D4 | Token thiếu | Bronze giữ nguyên chuỗi rỗng; chuyển NULL ở silver | Chờ nhóm duyệt |

## 6. Cách chạy lại profiling

Chạy ở thư mục gốc repo, trong môi trường dự án có DuckDB đã ghim (không cài thêm gói):

```bash
python eval/golden/tools/profile_dataset.py --config eval/golden/tools/configs/oulad.json --max-rows 1000
python eval/golden/tools/profile_dataset.py --config eval/golden/tools/configs/oulad.json
```

Hai file kết quả nằm ở `eval/golden/oulad/metadata/`. Lần chạy `--max-rows 1000` chỉ để bắt lỗi sớm; không dùng số liệu của lần chạy thử cho kết luận nào (mẫu 1.000 dòng cho kết quả mồ côi sai).

Báo cáo của `profile_dataset.py` lưu khóa ứng viên dưới tên `candidate_keys` (danh sách), khác `candidate_key` của `profile_oulad.py` cũ.

## 7. Điều kiện hoàn thành

- [x] 7 CSV đủ, header khớp, số dòng khớp nguồn, SHA-256 từng file đã ghi.
- [x] Data dictionary 40 cột có số liệu (`dictionary/data_dictionary.md`).
- [x] Báo cáo chất lượng, thiết kế chuẩn, metric và danh mục lỗi ở dạng draft.
- [ ] Đối chiếu lại SHA-256 của zip bằng copy/paste.
- [ ] Nhóm duyệt các phát hiện F1 đến F4 (`dictionary/data_dictionary.md` mục 10) và Q1 (`model/canonical_design.md` mục 8).
- [ ] Đối chiếu ý nghĩa cột với tài liệu mô tả gốc để nâng từ `Inferred` lên `Confirmed`.
- [ ] Chủ repo quyết định D3.
