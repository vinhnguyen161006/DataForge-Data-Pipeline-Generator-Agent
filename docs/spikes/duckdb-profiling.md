# Báo cáo spike DuckDB profiling — E1–E4

- **Dự án:** DataForge — Data Pipeline Generator Agent.
- **Người thực hiện:** Tú.
- **Ngày ghi nhận:** 12/10/2026.
- **Giai đoạn:** E1–E3 có artifact; E4 đã triển khai và chờ chạy.
- **Trạng thái:** Đã đối chiếu metadata E1, plan/kết quả E2 và JSON profile/memory study E3. Code E4 có warmup, đo lặp, median và record bàn giao; chưa có mẫu E4. Việc xác nhận với nhóm và kết quả kiểm tra code mới vẫn chờ bằng chứng.

## 1. Mục tiêu và phạm vi

Spike chuẩn bị cách thu thập ba chỉ số phục vụ yêu cầu FR-11: thời gian thực thi, số dòng quét và bộ nhớ đỉnh. Kết quả sẽ làm nền cho đo hiệu năng tuần 3 và đề xuất tối ưu tuần 4.

Phạm vi E1 gồm đọc nơi sử dụng số đo trong code, tạo CLI chạy riêng trong WSL, kiểm tra DuckDB thực thi được SQL và lưu cấu hình thực tế để tái chạy thí nghiệm.

E2 có query mẫu và EXPLAIN ANALYZE ở mục 8. E3 đã thu JSON profile và khảo sát memory; phương pháp ở mục 9 và số thật ở mục 10. E4 đã triển khai ở mục 11, chờ chạy để điền 5 mẫu và median. Chưa có kết luận về hiệu quả của rewrite.

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

## 4. Môi trường E1 đã ghi nhận

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

## 5. Phương pháp E1 đã chạy

Phiên bản E1 thực hiện theo thứ tự:

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

SQL trong E1 là SQL cố định do người phát triển viết. CLI chạy riêng trong WSL; script không import FastAPI hoặc gọi LLM. Trong phiên bản E1, tham số `--rows` chỉ ghi kế hoạch dữ liệu; script hiện tại đã bổ sung tạo bảng và profiling ở E2/E3.

## 6. Cách tái chạy script hiện tại — E3

Từ `backend/` trong WSL, chạy toàn bộ khảo sát E3:

```bash
uv run --locked python scripts/spike_duckdb_profiling.py \
  --rows 1000000 \
  --threads 1 \
  --memory-limit 512MB \
  --memory-study \
  --output-dir ../data/spikes/duckdb/e3
```

Script tạo thư mục con có timestamp UTC và ID riêng, rồi in đường dẫn. File dữ liệu được tạo tại `RUN_DIR/sample.duckdb`; mỗi lần chạy có artifact riêng. Lệnh này chạy phiên bản script E3, không tái tạo nguyên trạng script E1 cũ.

Nếu các metric bắt buộc thiếu, chạy lại với `--explicit-metrics` để yêu cầu metric qua `custom_profiling_settings`:

```bash
uv run --locked python scripts/spike_duckdb_profiling.py \
  --rows 1000000 \
  --threads 1 \
  --memory-limit 512MB \
  --memory-study \
  --explicit-metrics \
  --output-dir ../data/spikes/duckdb/e3-explicit
```

Nếu DuckDB báo lỗi cấu hình hoặc thực thi, script ghi `failure.json` với phiên bản, loại lỗi và message trước khi phát sinh lại exception. Các lỗi đọc JSON hoặc validation giữ nguyên exception; raw profile đã được engine ghi vẫn là nguồn để kiểm tra. Không tự nâng dependency hoặc điền metric bị thiếu bằng 0.

### So sánh với một tiến trình CLI mới

Lấy giá trị `database` từ `environment.json` của lần đầu và dùng cho một lệnh CLI riêng:

```bash
uv run --locked python scripts/spike_duckdb_profiling.py \
  --database "../data/spikes/duckdb/e3/RUN_ID/sample.duckdb" \
  --threads 1 \
  --memory-limit 512MB \
  --output-dir ../data/spikes/duckdb/e3-new-process
```

Thay `RUN_ID` bằng thư mục thực tế hoặc dùng nguyên đường dẫn tuyệt đối trong metadata. Nếu lần đầu bật `--explicit-metrics`, bật cùng flag ở lần so sánh. `--database` mở dữ liệu có sẵn ở chế độ read-only; `source_rows` ghi số dòng đọc được, còn `rows_created = null` vì lần này không tạo dữ liệu.

Đối chiếu `process_id`, DuckDB version, query hash, result hash, threads, memory limit và peak buffer. Cache hệ điều hành có thể còn dữ liệu; tiến trình mới không bảo đảm một lần đọc hoàn toàn cold.

Các lệnh kiểm tra chất lượng script:

```bash
uv run --locked ruff format --check scripts/spike_duckdb_profiling.py
uv run --locked ruff check scripts/spike_duckdb_profiling.py
uv run --locked mypy scripts/spike_duckdb_profiling.py
```

E3 đã có artifact được đối chiếu ở mục 10. Code E4 mới chưa chạy thí nghiệm, lint hay mypy trong lần cập nhật báo cáo này; lệnh E4 nằm ở mục 11.


## 7. Kết quả E1 đã ghi nhận và giới hạn

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

### Trạng thái ba chỉ số ở E1

| Chỉ số | Đơn vị dự kiến | Giá trị | Phần việc tiếp theo |
|---|---|---|---|
| Thời gian query | Giây | Chưa đo | Xác định timing trong plan/profile và phạm vi elapsed phía Python |
| Số dòng quét | Dòng | Chưa đo | Xác nhận metric trên runtime, phân biệt với số dòng trả về |
| Bộ nhớ đỉnh | Byte | Chưa đo | Xác định nguồn, phạm vi buffer memory và nhu cầu đo RSS riêng |

`null` thể hiện chưa có phép đo, không được diễn giải thành 0. Query `SELECT 1` chỉ kiểm tra engine thực thi được SQL, chưa chứng minh khả năng thu đủ ba metric hoặc hiệu năng của pipeline.

Cấu hình và metadata hiện đủ làm đầu vào cho thí nghiệm tiếp theo. Chưa chốt E1 hoàn toàn vì việc xác nhận phiên bản với Trí còn chưa có bằng chứng.

## 8. Kết quả E2 đã ghi nhận

Nguồn: [environment.json E2](../../data/spikes/duckdb/e2/environment.json), [EXPLAIN](../../data/spikes/duckdb/e2/explain.txt), [EXPLAIN ANALYZE](../../data/spikes/duckdb/e2/explain_analyze.txt) và [result.json](../../data/spikes/duckdb/e2/result.json).

| Nội dung | Bằng chứng thực tế |
|---|---|
| Thời điểm metadata UTC | `2026-10-12T13:34:14.065248+00:00` |
| Môi trường | DuckDB `1.5.5`, Python `3.11.14`, WSL2, 1 thread |
| Dữ liệu | 1.000.000 dòng, database `:memory:` |
| Query | Lọc `amount >= 501`, GROUP BY `group_id`, ORDER BY tổng amount giảm dần |
| Scan | Sequential scan; chỉ đưa `amount`, `group_id` vào đầu ra; filter nằm trong scan |
| Cardinality đầu ra scan | Ước lượng khoảng 200.000; thực tế 500.000 |
| Aggregation | `PERFECT_HASH_GROUP_BY`, xuất 10 dòng |
| Sort | `ORDER_BY`, xuất 10 dòng |
| Kết quả | 10 nhóm, mỗi nhóm 50.000 dòng thỏa điều kiện |
| Timing tổng của lần EXPLAIN ANALYZE | `0.0043s` — khoảng 4,3 ms |
| Timing từng operator | Hiển thị `0.00s`; không đủ độ phân giải để xác định operator chậm nhất |
| JSON profiling của SELECT | Chưa có trong bộ artifact E2 |

500.000 là số dòng scan xuất sau lọc, chưa xác nhận số dòng được quét. Các projection sau aggregation có ước lượng khoảng 11 dòng, thực tế 10. Projection trên cùng hiển thị `~0 rows`; không diễn giải giá trị ước lượng này thành kết quả query rỗng.

Timing 4,3 ms là một mẫu EXPLAIN ANALYZE, chưa phải median benchmark. E3 dùng database dạng file để mở connection riêng, nên cần ghi nhận môi trường lưu trữ khác E2 khi đối chiếu timing.

## 9. E3 — Triển khai thu JSON profile

**Trạng thái:** Đã có run E3 thành công trên DuckDB 1.5.5, thu đủ ba metric ở chế độ default. Giá trị và path thực tế được ghi ở mục 10. Giới hạn reset buffer, tiến trình mới và nhu cầu RSS vẫn chưa được chốt.

### 9.1. Thứ tự thực thi

1. Tạo thư mục run riêng; tạo database dạng file hoặc mở file đã có qua `--database`.
2. Chuẩn bị dữ liệu, kiểm tra số dòng, lưu plan và kết quả tham chiếu; profiling JSON chưa bật.
3. Đóng connection chuẩn bị trước khi mở connection profiling read-only.
4. Chọn một file profile mới, đặt coverage SELECT và cấu hình metrics nếu được yêu cầu; bật JSON profiling trước khi đặt đường dẫn output có đuôi .json. Đặt đường dẫn trong try/finally để tắt profiling nếu bước này lỗi.
5. Đo `perf_counter()` quanh execute + fetchall của chính SELECT mẫu; đọc JSON trước câu SQL tiếp theo.
6. Kiểm tra query name, kiểu/range metric, rows returned nếu có và hash kết quả so với query tham chiếu.
7. Tắt profiling; lưu snapshot raw JSON, measurement và vị trí các node scan.
8. Chạy các trường hợp memory nếu có flag; đóng connection trước trường hợp reopened; ghi metadata và bảng quan sát.

SQL và dữ liệu do người phát triển định nghĩa. CLI không gọi LLM, không chạy trong FastAPI và không thay đổi hợp đồng metric của worker.

### 9.2. Mapping đã thu được trên runtime E3

| Chỉ số | Path JSON | Đơn vị | Cách đối chiếu |
|---|---|---|---|
| DuckDB query latency | `$.latency` | Giây | Giữ riêng với elapsed phía Python |
| Tổng dòng quét | `$.cumulative_rows_scanned` | Dòng | Không cộng lại với giá trị ở children |
| Dòng quét tại scan | `operator_rows_scanned` trong node scan | Dòng | Measurement ghi `json_path` đầy đủ để mở đúng node |
| Dòng xuất tại scan | `operator_cardinality` trong node scan | Dòng | Đối chiếu 500.000 dòng sau filter ở E2 |
| Peak buffer memory | `$.system_peak_buffer_memory` | Byte | Buffer memory của DuckDB; không gán thành RSS worker |

Đây là mapping theo [tài liệu metrics DuckDB](https://duckdb.org/docs/current/dev/metrics); code kiểm tra dữ liệu trên runtime khi chạy. Metric thiếu giữ `null` và được liệt kê trong `missing_metrics`. Giá trị sai kiểu, âm hoặc timing không hữu hạn bị từ chối, không bị chuyển thành 0.

Raw profile luôn được giữ để kiểm tra bằng tay. Metadata có `metric_mapping` cho các trường root; mỗi scan có đường dẫn dạng `$.children[...]` trong measurement.

### 9.3. Phạm vi timing và memory

`python_elapsed_seconds` bao gồm execute và fetch kết quả sang Python; không bao gồm tạo dữ liệu, mở connection hoặc đọc JSON. `latency` là timing engine ghi trong profile. Lưu riêng hai giá trị, chưa coi chúng là cùng một phép đo.

Peak buffer bao gồm bộ nhớ buffer của engine trong phạm vi thực tế của metric; không gọi đây là phần tăng thêm riêng cho query hoặc toàn bộ RSS worker. Việc dùng file và connection riêng giảm ảnh hưởng trực tiếp của bước tạo bảng trong instance chuẩn bị, nhưng vẫn cần khảo sát cache và trạng thái được giữ lại. Phạm vi FR-11 cần buffer peak hay thêm đỉnh RSS chưa được nhóm xác nhận.

### 9.4. Các trường hợp khảo sát bộ nhớ

| Label | Query | Trạng thái connection |
|---|---|---|
| `fresh` | SELECT mẫu | Connection profiling mới sau khi đóng preparation |
| `reused` | SELECT mẫu | Tái dùng cùng connection sau fresh |
| `pressure` | Gom theo từng ID rồi tổng hợp lại | Tạo nhiều nhóm hơn query mẫu; chưa mặc định peak sẽ cao hơn |
| `after-pressure` | SELECT mẫu | Cùng connection sau query pressure |
| `reopened` | SELECT mẫu | Đóng connection trước, rồi mở lại cùng database |
| Tiến trình mới | SELECT mẫu | CLI riêng qua `--database`; so bằng process ID và metadata |

`memory-study.json` ghi các peak quan sát và phép so sánh, không tự kết luận reset. `reset_status = "not_established"` yêu cầu người đọc diễn giải bằng chứng: peak cao sau pressure có thể liên quan đến high-water mark hoặc buffer/cache còn giữ. Hai peak bằng nhau không đủ để chứng minh reset; nếu pressure không tạo ra khác biệt, ghi thí nghiệm chưa phân biệt được.

### 9.5. Artifact sau khi chạy

Trong thư mục run do CLI in ra:

- `sample.duckdb`: dữ liệu nguồn nếu run tự tạo database.
- `environment.json`: môi trường, cấu hình, mapping, metric và trạng thái thiếu.
- `query.sql`, `result.json`, `explain*.json/txt`: bằng chứng chuẩn bị và plan.
- `profile-fresh.json`, `measurement-fresh.json`, `query-fresh.sql`: profile chính, record có kiểu và đúng SQL được đo.
- `samples.json`: danh sách record của các lần profile trong run.
- Khi bật memory study: profile/measurement/query riêng cho reused, pressure, after-pressure và reopened; thêm `memory-study.json`.
- `failure.json`: lỗi DuckDB nếu cấu hình hoặc SQL không thực thi được; không được coi là một run thành công.

Artifact E3 đã được đối chiếu và ghi ở mục 10. Những giới hạn còn chưa xác nhận được giữ rõ trong báo cáo; code hoặc artifact riêng lẻ không xác nhận toàn bộ hợp đồng FR-11.

## 10. Kết quả E3 đã đối chiếu trên runtime 1.5.5

Nguồn: [metadata E3](../../data/spikes/duckdb/e3/20261012T143650277181Z-ee699155/environment.json), [profile fresh](../../data/spikes/duckdb/e3/20261012T143650277181Z-ee699155/profile-fresh.json) và [memory study](../../data/spikes/duckdb/e3/20261012T143650277181Z-ee699155/memory-study.json). Không chạy lại E3 khi cập nhật báo cáo.

| Thuộc tính | Giá trị thực tế |
|---|---|
| Run ID | `20261012T143650277181Z-ee699155` |
| Thời điểm metadata UTC | `2026-10-12T14:36:50.476981+00:00` |
| Runtime | DuckDB `1.5.5`, Python `3.11.14`, WSL2 x86_64 |
| PID | `1452676` |
| Cấu hình | 1 thread; yêu cầu `512MB`, đọc lại `488.2 MiB` |
| Dữ liệu | 1.000.000 dòng trong file `sample.duckdb` |
| Metric mode | `default` |
| Trạng thái | `json_profile_captured`; `missing_metrics = []` |
| Query hash | `73c2f82c7eb07c5b60c051312605b4dcdc146413ee6b53c69b6d12739bc8cce0` |
| Result hash | `550682ff4d3242a6575d2e8ff1676055ad2bce2902fa1ea8e580919efc0ed9ae` |

### 10.1. Path, giá trị, đơn vị và phạm vi

| Chỉ số | Path thật trong profile fresh | Giá trị | Đơn vị / phạm vi |
|---|---|---:|---|
| Python elapsed | `measurements.python_elapsed_seconds` trong metadata | `0.005458026003907435` | Giây; execute + fetch |
| DuckDB latency | `$.latency` | `0.005390047` | Giây; timing engine |
| Dòng quét | `$.cumulative_rows_scanned` | `1000000` | Dòng; tổng của query |
| Peak buffer | `$.system_peak_buffer_memory` | `6103040` | Byte; buffer peak, không phải RSS |
| Dòng trả về | `$.rows_returned` | `10` | Dòng kết quả |
| Dòng scan xuất | Node scan: `operator_cardinality` | `500000` | Dòng sau filter |
| Dòng scan quét | Node scan: `operator_rows_scanned` | `1000000` | Dòng quét tại scan |
| Timing scan | Node scan: `operator_timing` | `0.0029929850000000014` | Giây |

Node scan có đường dẫn:

```text
$.children[0].children[0].children[0].children[0].children[0].children[0].children[0].children[0]
```

`operator_name = SEQ_SCAN`, `operator_type = TABLE_SCAN`, filter `amount>=501`, projections `amount` và `group_id`. Giá trị này xác nhận sự khác nhau giữa một triệu dòng quét, 500.000 dòng sau lọc và 10 dòng trả về; không cộng root rows scanned với scan child.

Hai timing là một mẫu E3, chưa phải median. E2 ghi 4,3 ms cho EXPLAIN ANALYZE trên database trong bộ nhớ, còn E3 dùng file và SELECT profiling; chưa dùng chênh lệch này để kết luận nhanh/chậm.

### 10.2. Bộ nhớ qua các workload

| Trường hợp | Peak buffer thực tế, byte |
|---|---:|
| Fresh connection | `6103040` |
| Reused connection | `6103040` |
| Query gom nhóm theo từng ID | `86839296` |
| SELECT mẫu sau query trên cùng connection | `86839296` |
| Đóng rồi mở lại connection | `6103040` |

Peak của SELECT mẫu sau pressure vẫn bằng peak pressure, và giảm khi mở lại connection. Đây là bằng chứng trạng thái/histories có thể ảnh hưởng đến peak; chưa phân biệt hoàn toàn high-water mark với buffer/cache còn giữ. Giữ `reset_status = not_established`, không gọi mỗi giá trị này là bộ nhớ tăng thêm riêng của SELECT.

Bộ artifact đã đối chiếu chứa các trường hợp trong cùng PID; chưa có bằng chứng đối chiếu tiến trình CLI mới trên cùng file. Phạm vi FR-11 cần thêm RSS và xác nhận phiên bản với Trí vẫn cần nhóm chốt.

## 11. E4 — Warmup, đo lặp và record bàn giao

**Trạng thái:** Code E4 đã triển khai; chưa chạy benchmark E4 hoặc lint/mypy trong lần cập nhật này. Chưa có 5 mẫu E4 hoặc median để ghi vào báo cáo. Script được định dạng bằng Ruff format trước khi bàn giao.

### 11.1. Cách chạy

Từ `backend/` trong WSL:

```bash
uv run --locked python scripts/spike_duckdb_profiling.py \
  --benchmark \
  --warmup 1 \
  --repeats 5 \
  --rows 1000000 \
  --threads 1 \
  --memory-limit 512MB \
  --output-dir ../data/spikes/duckdb/e4
```

Nếu bỏ `--output-dir`, script chọn `data/spikes/duckdb/e4` khi bật benchmark và `data/spikes/duckdb/e3` khi chạy E3. Mỗi lần chạy tạo thư mục con riêng. Có thể dùng `--database` để tái sử dụng file dữ liệu hoặc `--explicit-metrics` để yêu cầu metric; giữ các lựa chọn giống nhau khi so mẫu.

Các lệnh kiểm tra:

```bash
uv run --locked ruff check scripts/spike_duckdb_profiling.py
uv run --locked ruff format --check scripts/spike_duckdb_profiling.py
uv run --locked mypy scripts/spike_duckdb_profiling.py
```

### 11.2. Phương pháp và điều kiện hợp lệ

1. Hoàn tất và đóng các connection E3; tính SHA-256 file dữ liệu ngoài khoảng thời gian query.
2. Mở một connection benchmark riêng ở chế độ read-only; đọc lại cấu hình thực tế.
3. Warmup mặc định 1 lần; lưu profile và record riêng. Không đưa mẫu warmup vào median.
4. Thực thi đúng SELECT mẫu 5 lần trên cùng connection; mỗi lần fetch hết và snapshot profile trước SQL tiếp theo.
5. Mỗi capture xác nhận query name, hash kết quả tham chiếu và kiểu metric như E3.
6. Giữ thứ tự từng mẫu, values và profile path; tính median Python elapsed riêng với median DuckDB latency.
7. Median latency chỉ được ghi khi đủ toàn bộ số mẫu yêu cầu; metric thiếu giữ null và được ghi theo sample. Không công bố median của 4 mẫu như kết quả 5 mẫu.
8. Đóng benchmark connection rồi ghi record đề xuất để nhóm review.

Median được tính bằng `statistics.median()`, lấy giá trị giữa của 5 mẫu hợp lệ. [Tài liệu Python](https://docs.python.org/3.11/library/statistics.html#statistics.median)

Đây là đo trên connection đã warmup. Profiling được bật ở mọi mẫu; timer Python gồm execute + fetch, loại trừ tạo dữ liệu, mở connection, cấu hình profiler và parse/lưu JSON phía Python. Chi phí instrumentation trong thực thi query vẫn có thể ảnh hưởng timing. OS cache không được kiểm soát.

Connection benchmark riêng tránh dùng trực tiếp instance vừa chạy pressure của E3. Các peak vẫn có thể chứa history từ warmup/các trial trên cùng instance; lưu từng peak với scope, không cộng peak hoặc gọi đó là memory riêng của từng query.

### 11.3. Artifact E4

| Artifact | Nội dung |
|---|---|
| `benchmark-warmup.json` | Record warmup; mặc định 1 mẫu |
| `benchmark-samples.json` | Record của các trial; mặc định 5 mẫu |
| `benchmark-summary.json` | Mẫu thời gian, median riêng, coverage latency, rows scanned, peak từng trial, hạn chế |
| `benchmark-record.json` | Record đề xuất có schema version, dataset, config, method, summary và từng sample |
| `profile-benchmark-warmup-1.json` | Raw profile warmup |
| `profile-benchmark-trial-1.json` đến `profile-benchmark-trial-5.json` | Raw profile từng trial |
| `measurement-benchmark-*.json`, `query-benchmark-*.sql` | Measurement có kiểu và SQL tương ứng từng capture |

`environment.json.benchmark` chứa summary E4. `environment.json.measurements` tiếp tục là mẫu fresh E3 và không được đọc như median E4. `samples.json` vẫn dành cho các trường hợp E3; mẫu benchmark nằm trong `benchmark-samples.json`.

Khi chạy xong, đối chiếu `warmup_count = 1`, `measured_count = 5`, `latency_sample_count = 5`, `all_required_metrics_present`, query/result hash và số profile riêng. Ghi từng mẫu trước khi ghi median; không điền số minh họa làm kết quả.

### 11.4. Hợp đồng record đề xuất

Record có `schema_version = 1` và `contract_status = proposal`; chưa thay đổi API/schema của worker.

| Nhóm | Trường / ý nghĩa |
|---|---|
| Định danh | `run_id`, `query_id = sample-amount-groupby-v1`, `model_id = null` vì chưa ánh xạ dbt model |
| SQL và kết quả | `query_sha256`, `result_sha256`; hash kết quả kiểm tra query mẫu cố định, không thay bộ kiểm chứng rewrite |
| Workload | `workload_kind = select_fetch_all` |
| Engine và môi trường | DuckDB version, Python, OS, architecture, PID |
| Dataset | Database path, SHA-256 file và source rows; file hash nhận diện snapshot vật lý, không chứng minh hai dataset khác file tương đương |
| Config | Threads và memory limit yêu cầu/thực tế |
| Method | Warmup, repeats, profiling mode, connection/cache policy, timing/memory scope, trạng thái chưa chốt reset |
| Units | Elapsed/latency: giây; rows scanned: dòng; peak buffer: byte |
| Summary | Median riêng và coverage đầy đủ; danh sách metric thiếu theo sample |
| Samples | Index, thời điểm, SQL/result hash, raw profile/SQL path, values và exact scan paths |
| Limitations | Overhead profiler, history memory, OS cache, khác biệt SELECT/dbt và phạm vi RSS chưa chốt |

Bàn giao record để Vinh/Tuấn Anh/Trí review scope và cách tích hợp. Hợp đồng đang ở trạng thái đề xuất, chưa có bằng chứng nhóm chấp thuận.

## 12. Câu hỏi bàn giao tuần 3 và tiêu chí chốt

| Vấn đề | Nhận định / đề xuất | Cần chốt hoặc kiểm chứng |
|---|---|---|
| SELECT so với CTAS/dbt materialization | SELECT hiện đo execute + fetch. CTAS/materialization có thêm thao tác tạo/ghi dữ liệu; cần gắn workload kind và đo riêng | SQL nào thuộc một lượt build, phạm vi timing, coverage profiling cho statement ngoài SELECT |
| Một model có nhiều SQL | Giữ record từng statement và timing toàn model riêng. Không cộng các peak memory | Cách cộng timing khi có song song, retry và overhead adapter; quan hệ statement ID ↔ model ID |
| `run_results.json` | dbt ghi `execution_time` của node và `timing` theo các bước, thường compile/execute | Đối chiếu artifact thực tế của dbt-core 1.12.5/dbt-duckdb 1.11.0; không gọi node timing là latency SELECT |
| Memory reset và RSS | E3 cho thấy peak cao sau pressure còn được báo ở SELECT nhỏ; mở lại connection giảm peak | Phân biệt history với retained buffers; thử tiến trình mới; chốt buffer peak hay thêm RSS cho FR-11 |

Theo [tài liệu run results của dbt](https://docs.getdbt.com/reference/artifacts/run-results-json), node có timing theo từng bước; cần đối chiếu với run thật của repo. Spike chưa thực thi dbt build nên chưa xác nhận timing/materialization của dbt trong môi trường này.

Chốt E4 sau khi có 5 mẫu thật, median đúng scope, record bàn giao tái chạy được và ghi rõ giới hạn. Hiện E3 có số thật; E4 mới hoàn thành phần triển khai và cần Tú chạy để xác nhận. Chưa kết luận rewrite nhanh hơn hoặc tương đương, chưa xác nhận CI toàn dự án.

