# TPC-H — Scale factor 1

Bộ dữ liệu tổng hợp TPC-H lớn, dùng để kiểm thử tích hợp và đo hiệu năng. Bộ còn lại: [tpch_sf0_1](../tpch_sf0_1/README.md). Hai scale factor cần được sinh riêng.

## Nguồn và phiên bản

Dữ liệu được sinh bằng [script của dự án](../tools/generate_tpch.py), sử dụng DuckDB `tpch` extension và `CALL dbgen(sf = 1)`.

Theo [manifest tham chiếu](metadata/generation_manifest.json): DuckDB `1.5.5`, extension `v1.5.5`, scale factor `1`. Tài liệu nguồn: [DuckDB TPC-H extension](https://duckdb.org/docs/stable/core_extensions/tpch).

## Cấu trúc và quy mô

```text
tpch_sf1/
├── README.md
├── raw/                          CSV sinh cục bộ, không commit
└── metadata/
    └── generation_manifest.json  Phiên bản, số dòng, kích thước và SHA-256
```

Số liệu dưới đây lấy từ manifest tham chiếu, chưa phải kết quả kiểm tra lại CSV trên máy người đọc.

| File | Số dòng |
|---|---:|
| region.csv | 5 |
| nation.csv | 25 |
| supplier.csv | 10.000 |
| customer.csv | 150.000 |
| part.csv | 200.000 |
| partsupp.csv | 800.000 |
| orders.csv | 1.500.000 |
| lineitem.csv | 6.001.215 |

Tổng dung lượng 8 CSV trong manifest: **1.116.569.309 byte**, khoảng **1,04 GiB**. Các khóa ghép đáng kiểm thử gồm `partsupp(ps_partkey, ps_suppkey)` và `lineitem(l_orderkey, l_linenumber)`.

## Sinh dữ liệu

Chạy trong Bash WSL/Linux tại thư mục gốc repo, sau khi cài dependency backend bằng `uv sync --locked` trong `backend/`. Lần đầu cài extension cần Internet. Cần dung lượng trống cho cả bản sinh trong `data/` và bản chép vào `raw/`.

```bash
backend/.venv/bin/python eval/golden/tools/generate_tpch.py \
  --sf 1 --base data/generated-golden
```

Đợi script ghi `data/generated-golden/tpch_sf1/metadata/generation_manifest.json`, rồi chép CSV:

```bash
mkdir -p eval/golden/tpch_sf1/raw
cp --update=none data/generated-golden/tpch_sf1/raw/*.csv \
  eval/golden/tpch_sf1/raw/
```

`--update=none` giữ các file đích đã tồn tại trên GNU coreutils hỗ trợ tùy chọn này. Nếu file cũ sai hash, xử lý file đó trước khi chép lại; lệnh không tự thay thế nó.

Script còn xuất `metadata/answers/q01.csv` đến `q22.csv` và manifest của lần sinh trong `data/generated-golden/tpch_sf1/`. Các file này là bản ghi đáp án do `tpch_answers()` cung cấp, không phải kết quả chạy 22 truy vấn trên dữ liệu vừa sinh. Giữ nguyên manifest tham chiếu trong `eval/golden/` để đối chiếu.

## Kiểm tra SHA-256

Chạy từ gốc repo. Lệnh chỉ đọc CSV và manifest tham chiếu, không ghi đè metadata.

```bash
python3 - <<'PY'
import hashlib
import json
from pathlib import Path

base = Path("eval/golden/tpch_sf1")
manifest = json.loads((base / "metadata/generation_manifest.json").read_text())
failed = False
for entry in manifest["tables"].values():
    path = base / "raw" / entry["file"]
    if not path.is_file():
        print(f"MISSING: {path.name}")
        failed = True
        continue
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    matched = actual == entry["sha256"]
    print(f"{'OK' if matched else 'MISMATCH'}: {path.name}")
    failed |= not matched
raise SystemExit(1 if failed else 0)
PY
```

Cần Python 3.11 trở lên. Cả 8 file `OK` nghĩa là CSV khớp từng byte với manifest. Khi có `MISMATCH`, kiểm tra phiên bản DuckDB/extension và cách xuất CSV trước khi kết luận về bộ dữ liệu; giữ manifest tham chiếu để đối chiếu.

## Quy ước Git

Commit README và metadata đã được review. `raw/`, ZIP trong `eval/golden/` và thư mục `data/` đã được `.gitignore` bỏ qua. Sau khi clone/pull, mỗi thành viên tự sinh lại CSV hoặc nhận bản dữ liệu từ nhóm, rồi đối chiếu hash.
