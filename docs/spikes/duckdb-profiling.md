# Báo cáo spike DuckDB profiling — E1–E3

- **Dự án:** DataForge — Data Pipeline Generator Agent.
- **Người thực hiện:** Tú.
- **Ngày ghi nhận:** 12/10/2026.
- **Giai đoạn:** E1/E2 có bằng chứng; E3 đã triển khai và chờ chạy.
- **Trạng thái:** Đã có artifact môi trường E1 và plan/kết quả E2. E3 đã có code thu JSON profile và khảo sát memory, chưa có số đo E3. Việc xác nhận phiên bản với Trí và các kiểm tra chất lượng chưa có bằng chứng trong báo cáo.

## 1. Mục tiêu và phạm vi

Spike chuẩn bị cách thu thập ba chỉ số phục vụ yêu cầu FR-11: thời gian thực thi, số dòng quét và bộ nhớ đỉnh. Kết quả sẽ làm nền cho đo hiệu năng tuần 3 và đề xuất tối ưu tuần 4.

Phạm vi E1 gồm đọc nơi sử dụng số đo trong code, tạo CLI chạy riêng trong WSL, kiểm tra DuckDB thực thi được SQL và lưu cấu hình thực tế để tái chạy thí nghiệm.

E2 đã có bảng tổng hợp, query mẫu và EXPLAIN ANALYZE; kết quả được ghi ở mục 8. E3 đã triển khai thu JSON profile và khảo sát memory, mô tả ở mục 9; chưa chạy để điền giá trị. Đo lặp và median thuộc E4. Chưa có kết luận về hiệu quả của rewrite.

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

Code E3 chưa được chạy thí nghiệm, lint hay mypy trong lần cập nhật báo cáo này. Kết quả chạy được Tú cung cấp hoặc artifact mới sẽ bổ sung sau.


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

**Trạng thái:** Code đã triển khai; chưa có artifact E3 để xác nhận giá trị, path thực tế hoặc hành vi reset memory. Toàn bộ giá trị E3 vẫn để trống cho đến khi CLI chạy.

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

### 9.2. Mapping cần xác nhận trên runtime

| Chỉ số | Path dự kiến | Đơn vị | Cách đối chiếu |
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

Khi nhận artifact E3, bổ sung bảng: run ID, profile path, giá trị từng metric, đơn vị, scan path, nhận xét so E2 và giới hạn memory. Chưa đánh dấu E3 hoàn thành chỉ vì code đã có.

## 10. Phần còn lại và bước E4

- Chạy E3 trên môi trường WSL đã ghim, đọc raw JSON và xác nhận đủ ba metric cùng đơn vị/phạm vi.
- Chạy so sánh memory và CLI mới trên cùng database; ghi quan sát thật, giữ giới hạn chưa phân biệt được.
- Xác nhận với nhóm phạm vi bộ nhớ cho FR-11 và phiên bản với Trí; chưa có bằng chứng các việc này hoàn tất.
- E4: warmup rồi đo 5 mẫu cùng query/data/config, lưu từng mẫu và median; chuẩn bị hợp đồng bàn giao, phân biệt SELECT với dbt materialization/CTAS.
- Kết quả E3 không tự chứng minh rewrite nhanh hơn hoặc tương đương. Quyết định đó thuộc benchmark và bộ phán xét sau này.

