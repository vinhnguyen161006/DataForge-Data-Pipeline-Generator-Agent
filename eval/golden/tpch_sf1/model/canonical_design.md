# TPC-H — Thiết kế chuẩn (bản trung gian v0.1)

**Trạng thái:** `DRAFT trung gian`. Chưa đối chiếu với schema `DataDesign` thực tế. Chưa đọc đặc tả TPC-H trong phiên làm việc này; mọi công thức doanh thu là `CẦN XÁC NHẬN`.
**Căn cứ:** `tpch_sf1/metadata/profile_report.json` (sf = 1, đầy đủ), `tpch_sf1/metadata/generation_manifest.json`, `tpch_sf1/README.md`.
**Vai trò:** kiểm chứng máy móc (tương đương rewrite, đo hiệu năng), không đo chất lượng thiết kế do LLM sinh.

## 1. Grain

| Bảng | Một dòng là | Số dòng sf = 1 | Nhãn |
|---|---|---|---|
| lineitem | một dòng hàng trong một đơn | 6.001.215 | ĐÃ ĐO |
| orders | một đơn | 1.500.000 | ĐÃ ĐO |
| partsupp | một cặp (sản phẩm, nhà cung cấp) | 800.000 | ĐÃ ĐO |
| part | một sản phẩm | 200.000 | ĐÃ ĐO |
| customer | một khách | 150.000 | ĐÃ ĐO |
| supplier | một nhà cung cấp | 10.000 | ĐÃ ĐO |
| nation | một quốc gia | 25 | ĐÃ ĐO |
| region | một vùng | 5 | ĐÃ ĐO |

## 2. Khóa

| Bảng | Khóa | Duy nhất | Nhãn |
|---|---|---|---|
| lineitem | (l_orderkey, l_linenumber) | 100% | ĐÃ ĐO |
| partsupp | (ps_partkey, ps_suppkey) | 100% | ĐÃ ĐO |
| orders | o_orderkey | 100% | ĐÃ ĐO |
| customer | c_custkey | 100% | ĐÃ ĐO |
| part | p_partkey | 100% | ĐÃ ĐO |
| supplier | s_suppkey | 100% | ĐÃ ĐO |
| nation | n_nationkey | 100% | ĐÃ ĐO |
| region | r_regionkey | 100% | ĐÃ ĐO |

## 3. Quan hệ

| Quan hệ | Cardinality | Mồ côi | Nhãn |
|---|---|---|---|
| lineitem → orders (l_orderkey) | N-1 | 0 | ĐÃ ĐO |
| orders → customer (o_custkey) | N-1 | 0 | ĐÃ ĐO |
| lineitem → partsupp (l_partkey, l_suppkey) | N-1 | 0 | ĐÃ ĐO |
| partsupp → part (ps_partkey) | N-1 | 0 | ĐÃ ĐO |
| partsupp → supplier (ps_suppkey) | N-1 | 0 | ĐÃ ĐO |
| customer → nation | N-1 | 0 | ĐÃ ĐO |
| supplier → nation | N-1 | 0 | ĐÃ ĐO |
| nation → region | N-1 | 0 | ĐÃ ĐO |

N-N giữa part và supplier được hiện thực qua partsupp. Không đếm `part` hoặc `supplier` qua `lineitem` trực tiếp nếu không qua partsupp.

## 4. Metric

| Metric | Định nghĩa | Nhãn |
|---|---|---|
| Doanh thu sau chiết khấu | SUM(l_extendedprice × (1 − l_discount)) | Xác nhận một phần (định nghĩa truy vấn TPC-H; nguồn thứ cấp) |
| Doanh thu sau thuế | SUM(l_extendedprice × (1 − l_discount) × (1 + l_tax)) | Xác nhận một phần (sum_charge của Q1; nguồn thứ cấp) |
| Số lượng bán | SUM(l_quantity) | ĐỀ XUẤT |
| Giá trung bình dòng hàng | AVG(l_extendedprice) | Xác nhận một phần: l_extendedprice là thành tiền của dòng (Q1 avg_price) |

Không cộng doanh thu từ `lineitem` và `o_totalprice` trong cùng một báo cáo (rủi ro đếm trùng, TPC-03).

## 5. Làm sạch

| Quy tắc | Căn cứ | Nhãn |
|---|---|---|
| Giá trị thiếu | Chưa đọc số giá trị thiếu của bộ TPC-H trong phiên này; cần kiểm tra trong profile_report.json | CHƯA XÁC MINH |
| Không cần loại trùng | 0 dòng trùng hoàn toàn ở cả 8 bảng | ĐÃ ĐO |
| Kiểu ngày | Chuyển l_shipdate, o_orderdate sang DATE | ĐỀ XUẤT |
| Hệ số chiết khấu | Phân số, không chia 100 (truy vấn Q6 dùng .06); xác nhận thêm bằng discount_range | Xác nhận một phần (TPC-04) |

Bộ dữ liệu này sạch về cấu trúc. Không dùng nó để đo khả năng phát hiện lỗi tự nhiên; lỗi phải được tiêm có chủ đích.

## 6. Dashboard (dùng cho kiểm thử tương đương và hiệu năng)

| Câu hỏi | Metric | Dimension | Bảng nguồn | Grain | Tổng hợp |
|---|---|---|---|---|---|
| Doanh thu theo năm | Doanh thu sau chiết khấu | năm của o_orderdate | lineitem ⋈ orders | dòng hàng | SUM |
| Doanh thu theo vùng | Doanh thu sau chiết khấu | region của nation khách | lineitem ⋈ orders ⋈ customer ⋈ nation ⋈ region | dòng hàng | SUM |
| Số đơn theo trạng thái | Số đơn | o_orderstatus | orders | đơn | COUNT |

Các truy vấn này dùng để kiểm tra tương đương rewrite và đo hiệu năng, không phải dashboard sản phẩm.

## 7. Câu hỏi cho Modeler (liên kết ambiguity_cases.csv)
TPC-01 (l_extendedprice), TPC-02 (doanh thu), TPC-03 (o_totalprice), TPC-04 (đơn vị chiết khấu), TPC-05 (không cần hỏi).

## 8. Chưa xác minh
- Tương thích với schema `DataDesign`.
- Công thức doanh thu và định nghĩa cột theo đặc tả TPC-H.
- Điều khoản giấy phép và chính sách công bố của TPC: xem `tpch_sf0_1/README.md`, `tpch_sf1/README.md`.
