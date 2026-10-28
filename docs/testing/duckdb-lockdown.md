# DuckDB riêng cho từng workspace và khóa cấu hình

Lớp runtime trong worker nạp CSV bằng code tin cậy, tạo bảng vật lý rồi mới giao connection đã khóa cho profiler.

## Đọc code theo thứ tự

1. `backend/worker/sandbox.py`: đọc `DUCKDB_LOCKDOWN_SETTINGS` và `duckdb_lockdown_sql()`. Renderer luôn đặt `lock_configuration` cuối cùng.
2. `backend/worker/duckdb_runtime.py`: đọc `DuckDBLimits`, `CsvTableInput` và `create_profile_database()`.
3. Theo các bước `_root()` → `_ownership()` → `_connect()` → `_load()` → `_seal()` → `yield` → `finally`.
4. Đọc `reopen_profile_database()`: không nạp CSV nhưng vẫn đặt tài nguyên và khóa lại trước `yield`.
5. Đọc `LoadedTable` trong `app/profiler/schemas.py` và chữ ký `profile_files()` trong `app/profiler/profile.py`.
6. Đối chiếu với `tests/unit/test_duckdb_lockdown.py`.

`yield` là điểm giao connection cho caller. Nếu load, setting hoặc xác minh chính sách lỗi, caller không nhận connection; `finally` đóng tài nguyên.

## Luồng chạy

```text
Workspace riêng của một attempt
  → kiểm tra đường dẫn, giữ khóa sở hữu
  → mở profile.duckdb, tắt tự cài/nạp extension
  → đặt threads, memory, temp directory và ngân sách temp
  → chuyển từng CSV sang bản UTF-8 tạm trong workspace
  → materialize bảng VARCHAR theo config đã xác nhận
  → xóa CSV tạm
  → tắt external access, khóa cấu hình và xác minh chính sách
  → profiler truy vấn bảng đã nạp
  → đóng connection, nhả khóa
```

Không tạo view trỏ về `read_csv()`: view còn cần đọc nguồn lúc truy vấn, khi external access đã tắt. Bảng vật lý vẫn dùng được khi CSV staging đã bị xóa; test chứng minh điều này.

Các cột được nạp thành `VARCHAR` để giữ mã như `00001`. Suy ra kiểu, min/max theo kiểu nghiệp vụ, khóa và quan hệ thuộc thuật toán profiler; loader không tự ép mã sang số.

## Đầu vào và workspace

`CsvTableInput` chứa tên bảng, đường dẫn CSV staging và `CsvReadConfig` đã xác nhận. Tên bảng dùng chữ thường, chữ số, gạch dưới; bắt đầu bằng chữ, tối đa 63 ký tự. Loader dùng API `read_csv(...).create(...)`, không ghép input vào SQL.

```text
attempt-0001/
  customers.csv
  orders.csv
  .profile.lock
  profile.duckdb
  duckdb-tmp/
```

- Workspace phải có sẵn, không chứa symlink hoặc ký tự glob trong đường dẫn.
- CSV phải là file riêng trong workspace, có tên CSV hợp lệ; đường dẫn tương đối tính từ workspace. Từ chối `..`, symlink/hard link và nguồn hoặc tên bảng trùng.
- Database/WAL và scratch không được trỏ bằng symlink/hard link sang nơi khác.
- `flock` trên Linux ngăn hai caller dùng helper trong cùng attempt. Kernel nhả khóa khi process chết; file `.profile.lock` tồn tại không có nghĩa đang bận. Không xóa lock file khi đang dùng.
- Create yêu cầu chưa có database. Retry dùng workspace attempt mới, không ghi đè attempt lỗi.
- Reopen yêu cầu database tồn tại, không tự tạo database rỗng.

Khóa sở hữu chỉ bảo vệ caller tuân thủ helper; worker/hạ tầng vẫn phải bảo đảm quyền workspace.

Loader chuyển mã theo luồng, dùng codec đã xác nhận rồi ghi UTF-8 tạm, không đọc toàn bộ CSV vào RAM. Hỗ trợ UTF-8 BOM, UTF-16, latin-1 và các text codec trong contract mà không cài extension encoding. Delimiter, quote, escape, header, skip rows, null tokens và định dạng ngày/giờ được truyền vào loader; không sniff lại, không tự bỏ dòng lỗi. Test kiểm tra config và hash file nguồn không đổi.

## Chính sách trên runtime thực tế

Giữ nguyên DuckDB `1.5.5`, dbt-core `1.12.5` và dbt-duckdb `1.11.0`. Test đối chiếu bản cài đặt, `pyproject.toml` và `uv.lock`.

| Setting | Sau khóa | Hành vi kiểm chứng |
|---|---|---|
| `enable_external_access` | `false` | Chặn CSV/text/Parquet, COPY, ATTACH ngoài ngoại lệ nội bộ |
| `autoinstall_known_extensions` | `false` | Không tự cài extension |
| `autoload_known_extensions` | `false` | Không tự nạp extension |
| `lock_configuration` | `true` | Chặn đổi threads/memory/temp, bật external access hoặc mở khóa |
| `allowed_configs` | `[]` | Không setting nào được miễn khóa |

DuckDB dạng file có một chi tiết quan trọng: khi tắt external access, engine 1.5.5 **tự thêm** ngoại lệ cho:

- `profile.duckdb`
- `profile.duckdb.wal`
- `profile.duckdb.wal.checkpoint`
- `profile.duckdb.wal.recovery`
- thư mục `duckdb-tmp/` của chính workspace

Helper xóa ngoại lệ có sẵn trước khi khóa và xác minh **đúng tập đường dẫn nội bộ này** sau khi khóa. Có sai khác thì báo lỗi và đóng connection. Không cho phép CSV nguồn, toàn workspace, storage root hoặc `/tmp`.

Vì vậy không diễn đạt rằng SQL bị cấm mọi filesystem access: file nội bộ và scratch riêng vẫn có ngoại lệ của engine. Không đặt credentials, raw nguồn hoặc artifact attempt khác trong scratch. Test kiểm tra tập ngoại lệ và chặn đọc cả thư mục có tên gần giống scratch. Chủ hạ tầng cần review điểm này khi nối runner/mount thực tế.

Test `INSTALL`/`LOAD` dùng đường dẫn extension giả cục bộ và yêu cầu `PermissionException`; không tải từ Internet. Extension tích hợp sẵn không đồng nghĩa external extension được phép nạp.

## Tài nguyên và thứ tự khởi tạo

Mặc định `DuckDBLimits`: 2 threads, memory 256 MiB, temp tối đa 512 MiB. Đây là ngân sách fixture nhỏ, chưa phải sizing OULAD/TPC-H.

- `memory_limit` là ngân sách DuckDB quản lý, không thay `RLIMIT_AS`/cgroup và không đồng nghĩa RSS.
- `max_temp_directory_size` giới hạn spill do DuckDB quản lý, không thay quota tổng workspace.
- Giới hạn OS, timeout và output vẫn do `run_sandboxed()` quản lý.
- Đặt `temp_directory` cần external access còn bật. Cả create/reopen đều có đoạn khởi tạo tin cậy này; không chạy caller SQL trước khi khóa.
- Không mở lại external access để sửa truy vấn profiler lỗi.

Ví dụ chạy được với CSV đã staging:

```python
from pathlib import Path

from app.ingest.sniff import CsvReadConfig
from worker.duckdb_runtime import CsvTableInput, create_profile_database

workspace = Path("/absolute/path/to/attempt-0001")
sources = [
    CsvTableInput(
        name="customers",
        path=Path("customers.csv"),
        read_config=CsvReadConfig(),
    )
]
with create_profile_database(workspace, sources) as database:
    row_count = database.connection.execute(
        "SELECT count(*) FROM customers"
    ).fetchone()
```

Ra khỏi context luôn đóng connection, kể cả profiler raise exception. Không giữ connection/cursor để dùng sau context.

## Reopen và hợp đồng profiler

Setting bảo mật không lưu bền trong file DuckDB. Test đối chứng mở bằng `duckdb.connect()` sau khi đóng mọi connection cho thấy external access trở về `true`, lock trở về `false`. Worker phải dùng `reopen_profile_database()` để áp dụng lại chính sách.

Cursor thuộc cùng instance chịu setting global; một database/instance mới không được bảo vệ chỉ vì instance trước đã khóa.

Chữ ký profiler đã đổi thành:

```python
profile_files(
    tables: Sequence[LoadedTable],
    *,
    connection: DuckDBPyConnection,
) -> DataProfile
```

`LoadedTable` chỉ mang tên bảng và tên file nguồn để gắn metadata, không cấp quyền đọc file. Worker chịu trách nhiệm load/config/lock/close. Profiler dùng connection được cấp, không tự `duckdb.connect()`, đọc CSV lại hoặc đóng connection của caller.

Profiler và runner đã được triển khai qua child thật; xem [profile-runner.md](profile-runner.md) về giao thức, thống kê và kiểm chứng tích hợp. Reopen trả metadata nguồn rỗng; caller muốn profiling lại phải lấy mapping từ manifest đã kiểm chứng, không đoán từ database.

Runner hiện kiểm tra READY/hash/identity, staging và JSON qua child có giới hạn filesystem. Worker loop, heartbeat và delivery tự động vẫn là phần tích hợp tiếp theo.

## Chạy kiểm chứng

Trong Bash WSL, tại `backend/`:

```bash
.venv/bin/python -m pytest tests/unit/test_duckdb_lockdown.py -q -rs
.venv/bin/python -m pytest tests/unit/test_duckdb_lockdown.py tests/unit/test_sandbox.py tests/unit/test_sandbox_limits.py -q -rs
```

Không cần PostgreSQL cho các test này. Probe child dùng Python isolated mode qua `run_sandboxed()`, AS 2 GiB, CPU 10 giây, wall timeout 20 giây và file limit 32 MiB.

Các tình huống chính: CSV theo config/encoding, mã có số 0 đầu, null/hash; thống kê sau khóa; chặn file/extension/config; reopen và cursor; hai workspace riêng; owner trùng; path escape/symlink/hard link/WAL/scratch; dọn tài nguyên khi load/profiler/lockdown thất bại.

SQL settings là lớp bảo vệ bổ sung, không cách ly mã Python tùy ý và không thay mount, network, user nonroot, cgroup hay kiểm soát tổng dung lượng.

## Bằng chứng đã chạy

Ngày 23/10/2026, trên WSL Ubuntu/Python 3.11.14:

- 74 test DuckDB đạt; tổng bộ DuckDB, môi trường và limits đạt 179 test.
- Ruff check/format, mypy strict (119 source files) và kiểm tra conventions đạt.
- Probe dùng cùng fixture trong container Python đã ghim digest, user 10001, network none, rootfs read-only, bỏ capabilities và no-new-privileges: trả về `duckdb-lockdown-ok` trên DuckDB 1.5.5.
- Container có cgroup 3 GiB, 2 CPU, pids-limit 256; child có AS 2 GiB và các giới hạn như test Linux.
- Probe container chỉ mount code/venv read-only và dùng workspace trong tmpfs; không chứng minh quyền bảo vệ raw volume của Compose thực tế.

Image probe: `python:3.11.14-slim-bookworm@sha256:65a93d69fa75478d554f4ad27c85c1e69fa184956261b4301ebaf6dbb0a3543d`. Log cục bộ ở `backend/data/upload-checks/duckdb-lockdown-container.json`; không chứa dữ liệu nguồn thật hoặc credential.

Hồi quy toàn backend trên database `dataforge_test`: **1021 passed, 16 skipped** trong 445,50 giây. Skip gồm 15 test TODO có sẵn và 1 test OULAD opt-in; không test DuckDB mới nào bị skip. Log/JUnit cục bộ: `backend/data/upload-checks/duckdb-lockdown-regression.log` và `duckdb-lockdown-regression.xml`.
