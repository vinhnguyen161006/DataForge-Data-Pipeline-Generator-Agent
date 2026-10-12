# Báo cáo spike DuckDB profiling — E1

- **Dự án:** DataForge — Data Pipeline Generator Agent.
- **Người thực hiện:** Tú.
- **Ngày ghi nhận:** 12/10/2026.
- **Giai đoạn:** E1 — Chuẩn bị thí nghiệm nhỏ.
- **Trạng thái:** Đã có metadata môi trường và CLI kiểm tra kết nối; profiling chưa bắt đầu. Chưa có bằng chứng xác nhận phiên bản với Trí hoặc kết quả kiểm tra chất lượng script.

## 1. Mục tiêu và phạm vi

Spike chuẩn bị cách thu thập ba chỉ số phục vụ yêu cầu FR-11: thời gian thực thi, số dòng quét và bộ nhớ đỉnh. Kết quả sẽ làm nền cho đo hiệu năng tuần 3 và đề xuất tối ưu tuần 4.

Phạm vi E1 gồm đọc nơi sử dụng số đo trong code, tạo CLI chạy riêng trong WSL, kiểm tra DuckDB thực thi được SQL và lưu cấu hình thực tế để tái chạy thí nghiệm.

Việc tạo bảng dữ liệu tổng hợp, chạy query mẫu, đọc `EXPLAIN ANALYZE`, thu JSON profile và đo lặp thuộc E2–E4. E1 hiện chưa cung cấp kết quả benchmark hoặc kết luận về hiệu quả của rewrite.

## 2. Nơi sử dụng số đo trong dự án

| Module | Hợp đồng hiện có | Liên hệ với spike |
|---|---|---|
| [worker/runner.py](../../backend/worker/runner.py) | `ModelMetrics` có `seconds`, `rows_scanned`, `peak_memory_bytes`; `run_dbt_build()` dự kiến thu timing từ dbt và tài nguyên từ DuckDB | Xác định nguồn, đơn vị và phạm vi số đo trước khi tích hợp vào worker |
| [compare/benchmark.py](../../backend/app/compare/benchmark.py) | `TimingSamples`, `measure()`, `is_faster()` dự kiến dùng các mẫu thời gian, median và độ nhiễu | E4 cung cấp thí nghiệm đo lặp làm cơ sở triển khai benchmark |
| [agents/optimizer.py](../../backend/app/agents/optimizer.py) | `ModelPerf` nhận SQL, median thời gian, số dòng quét và plan; `propose_rewrites()` đề xuất rewrite | Cung cấp thông tin hiệu năng cho agent; việc phán xét thuộc `optimizer/judge.py` |

Các hàm nghiệp vụ nêu trên vẫn là stub tại thời điểm rà báo cáo. Chưa có tích hợp số đo của spike vào worker, benchmark hoặc optimizer. Hai trường tài nguyên trong `ModelMetrics` cho phép `None`, phù hợp với trường hợp chưa thu được metric.

## 3. Nguồn bằng chứng

| Nguồn | Vai trò |
|---|---|
| [spike_duckdb_profiling.py](../../backend/scripts/spike_duckdb_profiling.py) | CLI mở kết nối, đọc cấu hình, kiểm tra query và ghi metadata |
| [environment.json](../../data/spikes/duckdb/e1/environment.json) | Artifact thực tế dùng để ghi thông tin môi trường trong báo cáo |
| [pyproject.toml](../../backend/pyproject.toml) | Đối chiếu phiên bản dependency được khai báo |
| [uv.lock](../../backend/uv.lock) | Lockfile của môi trường Python dự án |

Báo cáo được lập từ artifact đã có và nội dung script; quá trình viết báo cáo không chạy lại thí nghiệm. Metadata không chứa log stdout, nguyên lệnh CLI đã dùng hoặc kết quả Ruff/mypy.

Thư mục `data/` được bỏ qua trong [.gitignore](../../.gitignore). Bảng môi trường dưới đây lưu các giá trị của artifact để báo cáo vẫn có bằng chứng khi người review chỉ nhận nội dung trong Git.

## 4. Môi trường và cấu hình thực tế

| Thuộc tính | Giá trị ghi trong artifact |
|---|---|
| Thời điểm UTC | `2026-10-12T13:02:48.747379+00:00` |
| DuckDB runtime | `1.5.5` |
| Python runtime | `3.11.14` |
| OS/kernel | `Linux-6.18.33.2-microsoft-standard-WSL2-x86_64-with-glibc2.39` |
| Kiến trúc | `x86_64` |
| Database | `:memory:` |
| Threads yêu cầu | `1` |
| Threads thực tế | `1` |
| Memory limit yêu cầu | `512MB` |
| Memory limit thực tế hiển thị | `488.2 MiB` |
| Số dòng dự kiến | `1000000` |
| Số dòng đã tạo | `null` — chưa tạo dữ liệu trong E1 |
| Trạng thái profiling | `not_started` |
| Kết quả đo | `null` — chưa có phép đo |

Runtime DuckDB `1.5.5` khớp dependency `duckdb==1.5.5`; Python `3.11.14` đáp ứng `requires-python = "==3.11.*"`. Repo còn khai báo `dbt-core==1.12.5` và `dbt-duckdb==1.11.0`; E1 không chạy dbt nên artifact này không xác nhận runtime của hai package đó.

### Diễn giải memory limit

Artifact ghi nguyên hai cách biểu diễn: yêu cầu `512MB`, cấu hình đọc lại `488.2 MiB`. Nếu quy đổi 512 MB theo hệ thập phân sang MiB:

```text
512 × 1,000,000 / 1,048,576 ≈ 488.28 MiB
```

Hai giá trị phù hợp về độ lớn sau quy đổi đơn vị; không có bằng chứng cho thấy cấu hình bị giảm xuống 488.2 MB.

`memory_limit` là cấu hình giới hạn buffer manager, không phải số đo bộ nhớ đỉnh. Tổng bộ nhớ tiến trình có thể gồm phần được cấp phát ngoài buffer manager; vì vậy không dùng giá trị này thay cho peak memory hoặc RSS. [Tài liệu DuckDB về memory limit](https://duckdb.org/docs/current/configuration/pragmas#memory-limit)

## 5. Phương pháp chuẩn bị

Script thực hiện theo thứ tự:

1. Đọc `--rows`, `--threads`, `--memory-limit` và `--output-dir`; từ chối rows hoặc threads nhỏ hơn 1.
2. Mở connection DuckDB riêng với database `:memory:` và cấu hình được truyền vào.
3. Đọc cấu hình thực tế bằng:

   ```sql
   SELECT current_setting('threads'), current_setting('memory_limit');
   ```

4. Chạy kiểm tra thực thi tối thiểu:

   ```sql
   SELECT 1 AS ready;
   ```

   Script fetch toàn bộ kết quả và yêu cầu kết quả bằng `[(1,)]`; nếu khác, script phát sinh lỗi trước khi ghi metadata.

5. Ghi phiên bản, môi trường, cấu hình và trạng thái chuẩn bị vào `environment.json`, rồi in vị trí artifact.

DuckDB hỗ trợ connection riêng, cấu hình qua dictionary `config` và context manager để đóng connection. [Tài liệu Python API](https://duckdb.org/docs/current/clients/python/overview#configuration) Cấu hình đang áp dụng có thể đọc bằng `current_setting()`. [Tài liệu DuckDB về cấu hình](https://duckdb.org/docs/current/configuration/pragmas)

SQL trong E1 là SQL cố định do người phát triển viết. CLI chạy riêng trong WSL; script không import FastAPI hoặc gọi LLM. Tham số `--rows` hiện chỉ ghi kế hoạch dữ liệu, chưa tạo bảng hoặc xác nhận số dòng nguồn.

## 6. Cách tái chạy

Từ thư mục `backend/` trong WSL, chạy lệnh tương ứng với cấu hình ghi nhận:

```bash
uv run --locked python scripts/spike_duckdb_profiling.py \
  --rows 1000000 \
  --threads 1 \
  --memory-limit 512MB \
  --output-dir ../data/spikes/duckdb/e1
```

Artifact được ghi tại `data/spikes/duckdb/e1/environment.json`, tính từ root dự án. Khi dùng lại cùng output directory, script ghi đè metadata của lần trước; để giữ bằng chứng cũ, chọn một output directory khác cho lần chạy tiếp theo.

`uv run --locked` sử dụng lockfile của repo. Sau khi chạy, đối chiếu runtime và cấu hình đọc lại trong JSON, thay vì chỉ dựa vào giá trị truyền trên CLI.

Các lệnh kiểm tra chất lượng script:

```bash
uv run --locked ruff format --check scripts/spike_duckdb_profiling.py
uv run --locked ruff check scripts/spike_duckdb_profiling.py
uv run --locked mypy scripts/spike_duckdb_profiling.py
```

Bộ bằng chứng hiện tại chưa có output của các lệnh này; báo cáo chưa xác nhận chúng pass.

## 7. Kết quả ghi nhận và giới hạn

| Nội dung | Kết quả | Căn cứ |
|---|---|---|
| Có artifact môi trường | Đã ghi nhận | Nội dung `environment.json` |
| Phiên bản DuckDB runtime khớp repo | Đã đối chiếu | JSON ghi `1.5.5`; dependency ghim `1.5.5` |
| Áp dụng số thread | Đã ghi nhận | Requested và effective đều bằng `1` |
| Đọc lại memory limit | Đã ghi nhận | JSON ghi `488.2 MiB` |
| Query kiểm tra kết nối thành công | Suy ra từ luồng script | Artifact được ghi sau bước yêu cầu kết quả `[(1,)]`; chưa có log query riêng |
| Tạo một triệu dòng | Chưa thực hiện | `rows_created = null`; script chưa có bước tạo bảng |
| Lưu EXPLAIN / EXPLAIN ANALYZE | Chưa thực hiện | Script chưa có thao tác tương ứng |
| Thu JSON profile | Chưa thực hiện | `profiling_status = not_started` |
| Xác nhận phiên bản với Trí | Chưa có bằng chứng | Cần Tú xác nhận trước khi chốt E1 |

### Trạng thái ba chỉ số cần nghiên cứu

| Chỉ số | Đơn vị dự kiến | Giá trị | Phần việc tiếp theo |
|---|---|---|---|
| Thời gian query | Giây | Chưa đo | Xác định timing trong plan/profile và phạm vi elapsed phía Python |
| Số dòng quét | Dòng | Chưa đo | Xác nhận metric trên runtime, phân biệt với số dòng trả về |
| Bộ nhớ đỉnh | Byte | Chưa đo | Xác định nguồn, phạm vi buffer memory và nhu cầu đo RSS riêng |

`null` thể hiện chưa có phép đo, không được diễn giải thành 0. Query `SELECT 1` chỉ kiểm tra engine thực thi được SQL, chưa chứng minh khả năng thu đủ ba metric hoặc hiệu năng của pipeline.

Cấu hình và metadata hiện đủ làm đầu vào cho thí nghiệm tiếp theo. Chưa chốt E1 hoàn toàn vì việc xác nhận phiên bản với Trí còn chưa có bằng chứng.

## 8. Các bước tiếp theo

- **E2:** Tạo bảng vật lý từ `range(1000000)` với ID, nhóm và amount; chạy query WHERE + GROUP BY + ORDER BY; lưu nguyên output EXPLAIN và EXPLAIN ANALYZE.
- **E3:** Chạy chính SELECT mẫu với JSON profiling; fetch hết kết quả; xác nhận path, đơn vị và phạm vi ba metric trên runtime `1.5.5`. Metric thiếu được ghi là chưa thu được.
- **E4:** Warmup rồi đo 5 lần với cùng data/query/config; lưu từng mẫu và median; phân biệt thời gian Python với timing DuckDB; đề xuất hợp đồng số đo để bàn giao.

Mỗi bước cập nhật báo cáo bằng artifact thực tế. Chỉ ghi kết luận về số đo hoặc rewrite sau khi có bằng chứng của bước tương ứng.

