# Kiểm chứng môi trường tiến trình con

Hoàn thiện D1 của Tú ngày **23/10/2026**. Phần này xây dựng môi trường riêng cho child và kiểm chứng cách khởi chạy bằng một tiến trình Python thật.

## Đọc code theo thứ tự

1. ENV_ALLOWLIST trong [sandbox.py](../../backend/worker/sandbox.py): chỉ kế thừa PATH, LANG, LC_ALL, TZ và SYSTEMROOT nếu parent có.
2. ChildEnvOverrides: schema Pydantic strict, extra=forbid; chỉ chấp nhận bốn đường dẫn dbt được khai báo.
3. _workspace_root và _workspace_directory: yêu cầu workspace đã có, kiểm tra đường dẫn tương đối và từ chối symlink.
4. build_env: tạo dict mới, chuẩn bị thư mục trong workspace, không sửa os.environ hoặc dict extra của caller.
5. start_child_process: executable tuyệt đối, argv dạng list, cwd cố định, shell=False, stdin đóng và stdout/stderr qua pipe.

Parent tiếp tục giữ app DB credential để claim/heartbeat job. Child chỉ nhận dict do build_env tạo.

## Biến môi trường trong workspace

| Key | Giá trị mặc định, tương đối với workspace |
|---|---|
| HOME, USERPROFILE | home/ |
| XDG_CACHE_HOME | home/.cache/ |
| XDG_CONFIG_HOME | home/.config/ |
| TMPDIR, TEMP, TMP | tmp/ |
| DBT_PROFILES_DIR | dbt/profiles/ |
| DBT_PROJECT_DIR | workspace gốc |
| DBT_TARGET_PATH | dbt/target/ |
| DBT_LOG_PATH | dbt/logs/ |

Các thư mục được tạo nếu chưa có. Workspace gốc phải tồn tại; caller cấp workspace sau khi kiểm tra identity/storage ở D4. File hoặc symlink chiếm vị trí thư mục sẽ bị từ chối.

PYTHONNOUSERSITE=1, PYTHONDONTWRITEBYTECODE=1 và PYTHONUNBUFFERED=1 do worker đặt cố định. PYTHONPATH, PYTHONHOME, LD_PRELOAD và LD_LIBRARY_PATH không được kế thừa.

HOME riêng giữ vị trí cấu hình/cache mặc định của child trong workspace. TMPDIR hỗ trợ thư viện dùng thư mục tạm của hệ điều hành. Giới hạn và temp_directory của DuckDB vẫn phải đặt trên connection ở D3; không có biến môi trường DuckDB tự tạo nào thay thế việc đó.

## Contract extra_env

Chỉ nhận:

- DBT_PROFILES_DIR.
- DBT_PROJECT_DIR.
- DBT_TARGET_PATH.
- DBT_LOG_PATH.

Ví dụ hợp lệ:

~~~python
env = build_env(
    workspace,
    {"DBT_PROFILES_DIR": "config/profiles", "DBT_TARGET_PATH": "artifacts/target"},
)
~~~

Giá trị phải là đường dẫn tương đối dùng dấu /, nằm trong workspace. Từ chối chuỗi rỗng, NUL, đường dẫn tuyệt đối, dấu .., đường dẫn Windows/UNC và symlink trong các thành phần đường dẫn.

Mọi key ngoài schema đều bị từ chối, kể cả key không có chữ password/token/DSN. Caller không được thêm PATH, HOME, biến injection hoặc credential thông qua extra_env.

Lỗi schema dùng thông báo cố định, không đưa giá trị bị từ chối vào message. Không log toàn bộ môi trường parent hoặc child.

## Chạy test

Trong backend, Bash WSL:

~~~bash
.venv/bin/python -m pytest   tests/unit/test_sandbox.py   tests/unit/test_guards.py::test_sandbox_env_has_no_credentials   -q -rs
~~~

Bộ tập trung này không cần PostgreSQL, Gemini hoặc Docker.

Để chạy hồi quy đầy đủ với cấu hình test hiện có:

~~~bash
set -a
source .env.upload-checks
set +a

.venv/bin/python -m pytest -q -rs   --junitxml=data/upload-checks/sandbox-env-regression.xml
~~~

## Bằng chứng từ test

test_sandbox.py kiểm tra:

- Credential DATAFORGE_APP_DATABASE_URL, warehouse DSN, JWT/Gemini/GitHub key và credential không có prefix đều bị loại.
- Các biến điều khiển Python/loader không được truyền xuống.
- Chỉ kế thừa các biến nền tảng đã khai báo; môi trường parent giữ nguyên.
- HOME/temp/dbt nằm trong đúng workspace, tồn tại và ghi được.
- Các lần gọi và các workspace không dùng chung dict hoặc đường dẫn riêng.
- Extra key ngoài schema và đường dẫn thoát workspace bị từ chối.
- Symlink ra ngoài hoặc symlink tới nơi khác trong workspace đều bị từ chối.
- Môi trường sai bị từ chối trước khi khởi tạo process.
- Executable thiếu hoặc tương đối bị từ chối.

Ca child thật đặt credential giả trong parent, tạo file .env giả ở thư mục cha, rồi khởi chạy Python với argv list và cwd là workspace có khoảng trắng. Child chỉ báo boolean cho các key cần kiểm tra cùng các đường dẫn làm việc; không dump môi trường.

Child ghi file qua Path.home(), tạo tempfile và trả lại một đối số chứa ký tự shell. Test xác nhận credential không xuất hiện, thư mục nằm trong workspace, đối số giữ nguyên và không tạo file do shell diễn giải.

Test guard cũ test_sandbox_env_has_no_credentials đã được thay TODO/skip bằng kiểm tra thật.

## Ranh giới của D1 và bước tiếp theo

start_child_process là primitive khởi chạy, chưa áp dụng rlimit, timeout, giới hạn output hoặc dừng cây process. run_sandboxed vẫn là stub cho D2. Khi triển khai D2, cần nối đầy đủ các cơ chế đó vào quá trình khởi chạy và quản lý child; không dùng primitive này trực tiếp cho job không tin cậy.

Ruff S603 được ngoại lệ riêng cho worker/sandbox.py trong pyproject.toml vì hàm này có chủ đích chạy argv do worker cấp với shell=False và executable tuyệt đối. Không thêm ngoại lệ inline hoặc tắt rule cho cả repository.

Child probe không import app.core.config hoặc khởi tạo settings. Entry point profiler ở D4 cũng phải giữ contract này. Môi trường sạch không ngăn một chương trình chủ động đọc file .env/secret còn truy cập được trên filesystem.

D1 không chứng minh raw volume read-only, chặn truy cập mạng hoặc cô lập filesystem. Các phần đó cần quyền/mount/container phù hợp và kiểm chứng riêng ở D3/D4 với Trí. Workspace phải được runner cấp từ identity đã kiểm tra; build_env không tự xác nhận một workspace bất kỳ thuộc run nào.

Không thay model, migration, dependency hoặc frontend trong D1.

## Kết quả thực tế

| Kiểm chứng | Kết quả |
|---|---|
| test_sandbox.py | **50 passed**, không skip trên Linux |
| Guard môi trường cũ được thay TODO | **1 passed** |
| Nhóm D1 tập trung | **51 passed**, 0,65 giây |
| Toàn bộ backend | **892 passed, 16 skipped**, 356,36 giây |
| Ruff check / format | Qua; 120 file được kiểm tra format |
| mypy strict | Qua, 111 source file |
| check_conventions.py | Qua |

16 skip gồm 15 TODO ngoài D1 và test OULAD cần bật riêng. Test child và symlink của D1 đều chạy thật trên Linux, không bị skip. Các assertion kiểm tra parent không in toàn bộ os.environ khi thất bại.

Log và JUnit local được Git bỏ qua:

- backend/data/upload-checks/sandbox-env-regression.log.
- backend/data/upload-checks/sandbox-env-regression.xml.

Không chạy lại frontend CI hoặc migration vì D1 không thay các phần đó.

