# Kiểm chứng giới hạn tài nguyên và timeout của sandbox

Triển khai D2 của Tú ngày **23/10/2026**. Job chạy qua launcher riêng đặt rlimit trên Linux; worker cha giám sát deadline, output và thu hồi process group.

## Đọc code theo luồng

1. [sandbox_limits.py](../../backend/worker/sandbox_limits.py): Limits và SandboxLaunchRequest, contract Pydantic strict/frozen có schema_version=1.
2. [limit_exec.py](../../backend/worker/limit_exec.py): launcher tin cậy, không đọc settings/.env; đặt giới hạn rồi os.execv chương trình.
3. [sandbox.py](../../backend/worker/sandbox.py): run_sandboxed dùng môi trường D1, session riêng và vòng giám sát output/deadline.
4. [test_sandbox_limits.py](../../backend/tests/unit/test_sandbox_limits.py): probe Linux thực thi thật và kiểm tra cleanup.
5. [container_probe.py](../../backend/tests/fixtures/sandbox/container_probe.py): probe cgroup/quyền trong container tạm, số lần spawn hữu hạn.

Limits đã chuyển từ dataclass sang Pydantic model; các import cũ từ worker.sandbox vẫn dùng được. Khởi tạo bằng keyword arguments. Không thêm dependency hoặc nâng phiên bản.

## Contract Limits

| Trường | Đơn vị / chính sách |
|---|---|
| timeout_seconds | Giây thực, parent dùng time.monotonic |
| memory_mb | MiB; RLIMIT_AS soft=hard |
| cpu_seconds | Giây CPU; soft=ngân sách, hard=ngân sách+1 |
| max_file_mb | MiB cho mỗi file; RLIMIT_FSIZE soft=hard |
| max_open_files | RLIMIT_NOFILE soft=hard; contract yêu cầu ít nhất 16 |
| max_processes | RLIMIT_NPROC soft=hard; tính process/thread theo real UID |
| max_output_bytes | Tổng byte thô stdout+stderr giữ lại; mặc định 1 MiB, tối đa 64 MiB |

Các giá trị phải là số nguyên đúng kiểu, không nhận bool, số thực, 0 hoặc âm. Model frozen và revalidate_instances ngăn dùng model_copy để đưa giới hạn sai vào launcher.

Launcher cũng đặt RLIMIT_CORE=(0,0). Nếu yêu cầu vượt hard limit đã kế thừa hoặc đặt rlimit thất bại, launcher dừng trước khi chạy job; không bỏ qua giới hạn.

CPU budget tính trên process launcher/job. Chương trình có thể xử lý SIGXCPU ở soft limit, nhưng hard limit vẫn kết thúc nó. Không dùng rlimit CPU để suy ra tổng CPU của cả cây process.

## Cách khởi chạy

~~~text
Validate argv và Limits
→ nhận yêu cầu hủy sẵn có thì không launch
→ start_child_process với env D1, cwd=workspace, shell=False
→ start_new_session=True
→ Python -I chạy launcher theo đường dẫn tuyệt đối
→ launcher validate JSON version 1, đặt rlimit
→ execv chương trình, giữ nguyên PID
→ parent giám sát
→ thu hồi group, wait child, đóng pipe
~~~

Không dùng preexec_fn. Launcher chạy ở process riêng; việc đặt resource limit không ảnh hưởng worker parent hoặc các sandbox khác. Module resource chỉ được import ở nhánh Linux. run_sandboxed từ chối nền tảng khác thay vì chạy không có bảo vệ; primitive D1 vẫn dùng được cho probe nền tảng.

Launcher chỉ thêm thư mục code tin cậy của repository vào import path để đọc contract; không dùng PYTHONPATH của parent. Không import WorkerSettings, app.core.config hoặc LLM.

## Output, timeout và cleanup

Parent dùng pipe nonblocking và selectors để đọc cả hai stream theo chunk 64 KiB. Chỉ giữ tổng số byte theo ngân sách; đọc được dữ liệu vượt ngân sách thì output_limited=True và thu hồi group. Không gom output vô hạn bằng communicate rồi mới cắt.

Kết quả giải mã UTF-8 với replacement cho byte không hợp lệ. Ngân sách tính trên byte thô đã giữ, không phải kích thước khi encode lại chuỗi có ký tự replacement.

Vòng giám sát tiếp tục khi child còn chạy hoặc pipe còn mở. Nếu child chính thoát nhưng cháu giữ pipe, parent kết thúc descendants cùng group và đọc phần output còn lại.

Parent quan sát trạng thái leader bằng waitid với WNOWAIT, giữ identity của leader đến khi đã gửi tín hiệu cleanup. Sau đó mới wait/reap child chính, tránh nhả PID rồi tiếp tục signal cùng số group.

Timeout, output vượt mức hoặc yêu cầu dừng gửi SIGTERM; khoảng grace là 0,2 giây, sau đó SIGKILL nếu vòng giám sát vẫn cần thu hồi. Cleanup cũng chạy khi collector phát sinh exception. Wait child có timeout 2 giây và các pipe luôn được đóng. Không cho job để lại process nền trong cùng group sau khi kết thúc bình thường.

stop_event là threading.Event tùy chọn. Nó là điểm nối cho D5: hủy coroutine đang chờ asyncio.to_thread không tự dừng subprocess; caller phải đặt event và đợi sandbox cleanup.

## SandboxResult

| Trường | Ý nghĩa |
|---|---|
| returncode | Mã thoát thực tế; None nếu đã hủy trước launch |
| stdout / stderr | Prefix output trong ngân sách |
| timed_out | Parent đã chạm deadline |
| output_limited | Output vượt ngân sách |
| cancelled | Nhận yêu cầu dừng qua stop_event |

timed_out độc lập với returncode: child có thể xử lý SIGTERM và thoát 0 nhưng kết quả vẫn là timeout. Chương trình bắt MemoryError và chủ động thoát 0 cũng vẫn giữ mã 0; caller phải kiểm tra protocol kết quả của job ở D4.

SIGKILL không tự chứng minh hết RAM. Launcher báo lỗi bootstrap bằng message cố định và mã 125; job cũng có thể tự trả mã 125 nên không phân loại nguyên nhân chỉ từ mã thoát.

## Chạy test Linux

Trong backend, Bash WSL:

~~~bash
.venv/bin/python -m pytest \
  tests/unit/test_sandbox_limits.py \
  tests/unit/test_sandbox.py \
  tests/unit/test_guards.py::test_sandbox_env_has_no_credentials \
  -q -rs
~~~

Các probe tài nguyên không cần PostgreSQL hoặc Gemini. Test NPROC yêu cầu user không phải root; bộ thực tế đã chạy bằng UID 1000. Test D2 skip ngoài Linux; không tính skip đó là bằng chứng giới hạn đã hoạt động.

Các trường hợp đã kiểm tra:

- Giá trị sai và protocol version sai bị từ chối.
- Cả năm rlimit thực sự xuất hiện trong chương trình sau exec; parent không bị đổi giới hạn.
- Vòng CPU, bỏ qua SIGXCPU, cấp phát lớn, ghi quá cỡ và mở quá nhiều file.
- Một lần spawn hữu hạn bị NPROC chặn.
- Child ngủ, đóng stdout/stderr rồi ngủ, hoặc xử lý SIGTERM và thoát 0.
- Flood stdout, stderr hoặc đồng thời cả hai; output đúng bằng ngân sách và byte UTF-8 hỏng.
- Child/cháu bỏ qua SIGTERM; leader thoát mà cháu giữ pipe; process nền đã đóng pipe.
- Hủy trước launch và hủy một trong hai sandbox đồng thời.
- Collector lỗi vẫn thu hồi child và đóng pipe.
- Hard limit kế thừa quá thấp: job không được chạy.
- Môi trường D1 vẫn loại credential/injection và giữ đúng HOME/cwd.

## Kiểm tra container/cgroup thật

Đã dùng đúng image Python ghim trong Dockerfile, container tạm không có volume ứng dụng hoặc credential, network=none và tự dọn sau chạy.

Lần thứ nhất dùng memory=3g, cpus=2, pids-limit=256 như Compose. Probe quan sát:

- UID 10001, CapEff=0, NoNewPrivs=1.
- Root filesystem read-only.
- memory.max=3221225472.
- cpu.max có quota=200000, period=100000.
- pids.max=256.
- NPROC=1 thực sự chặn spawn khi chạy nonroot, không có capabilities.

Lần thứ hai dùng pids-limit=16 để kiểm tra bằng số process nhỏ: tạo được 15 child rồi lần tiếp theo bị EAGAIN. Probe luôn terminate/wait các child đã tạo; không dùng vòng fork vô hạn.

Chạy lại từ backend trong Bash WSL, với Docker đang chạy:

~~~bash
sandbox_image='python:3.11.14-slim-bookworm@sha256:65a93d69fa75478d554f4ad27c85c1e69fa184956261b4301ebaf6dbb0a3543d'

docker run --rm --network none --read-only \
  --tmpfs /tmp:rw,nosuid,nodev --user 10001:10001 \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 3g --cpus 2 --pids-limit 256 \
  -i --entrypoint python "$sandbox_image" -I - 256 inspect \
  < tests/fixtures/sandbox/container_probe.py

docker run --rm --network none --read-only \
  --tmpfs /tmp:rw,nosuid,nodev --user 10001:10001 \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 3g --cpus 2 --pids-limit 16 \
  -i --entrypoint python "$sandbox_image" -I - 16 exercise \
  < tests/fixtures/sandbox/container_probe.py
~~~

Probe này cần cgroup v2 và Docker hỗ trợ các limit tương ứng. Nó kiểm tra kernel/container với image nền đã ghim, không phải nghiệm thu toàn stack Compose hoặc profiler/DuckDB.

## Smoke test DuckDB trong cùng ngân sách container

[duckdb_budget_probe.py](../../backend/tests/fixtures/sandbox/duckdb_budget_probe.py) chạy qua run_sandboxed thật trong container với cgroup 3 GiB, 2 CPU và 256 pids. Worker code và site-packages Linux được mount read-only; workspace nằm trong tmpfs, không mount raw hoặc credential.

Kết quả quan sát: DuckDB **1.5.5**, RLIMIT_AS soft/hard **2147483648 byte**, threads **2**; phép sum(range(10000)) trả **49995000**, tạo được file budget.duckdb. DuckDB memory_limit được đặt 512 MiB cho probe này. Đây là bằng chứng cấu hình nhỏ có thể hoạt động cùng rlimit/cgroup, chưa phải sizing cho OULAD hoặc toàn profiler.

Chạy lại từ backend trong Bash WSL với venv Python 3.11 Linux đã cài dependency khóa:

~~~bash
docker run --rm --network none --read-only \
  --tmpfs /tmp:rw,nosuid,nodev --user 10001:10001 \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 3g --cpus 2 --pids-limit 256 \
  --mount "type=bind,src=$PWD/worker,dst=/app/worker,readonly" \
  --mount "type=bind,src=$PWD/.venv/lib/python3.11/site-packages,dst=/usr/local/lib/python3.11/site-packages,readonly" \
  -i --entrypoint python "$sandbox_image" -I - \
  < tests/fixtures/sandbox/duckdb_budget_probe.py
~~~

Biến sandbox_image dùng giá trị ghim ở ví dụ trước. Không dùng site-packages Windows cho probe này. D3 vẫn cần kiểm chứng settings lockdown, thứ tự load CSV và cùng connection thực thi.

## Phạm vi và giới hạn cần giữ rõ

RLIMIT_AS là không gian địa chỉ, không phải RSS và không phải tổng RAM của cây process. NPROC áp dụng theo real UID và có ngoại lệ cho root/capabilities; nhiều job cùng UID ảnh hưởng nhau. CPU rlimit là theo process; quota CPU cgroup là cơ chế khác.

FSIZE chỉ giới hạn từng file. Test đã chứng minh hai file dưới 1 MiB mỗi file có thể vượt tổng 1 MiB. Tổng dung lượng workspace cần quota hoặc cơ chế hạ tầng của Trí; D2 không triển khai disk quota.

Cgroup 3 GiB/2 CPU/256 pids là ngân sách cả container worker, gồm parent và mọi child. D5 cần đối chiếu concurrency. Smoke test DuckDB nhỏ đã qua với ngân sách trên. D3 cần kiểm chứng memory/threads/temp cho workload thực và lockdown; không suy ra RAM vật lý của DuckDB từ AS.

Process group thu hồi descendants còn trong group. Child cố tình đổi session/group cần biện pháp containment khác; process group không thay thế cgroup, filesystem permissions hoặc network isolation. Cháu đã chết có thể chờ init/reaper thu hồi zombie; test phân biệt process đang chạy với zombie, không coi kill(pid,0) là bằng chứng nó còn thực thi.

Chưa triển khai duckdb_lockdown_sql, profile runner hoặc worker loop. Không thay model, migration, dependency hoặc frontend.

Các ngoại lệ lint đều khai báo theo file trong pyproject.toml: S606 cho execv có chủ đích của launcher, S603 cho subprocess hữu hạn của fixture container; ngoại lệ S603 của sandbox từ D1 được giữ nguyên.

Nguồn đối chiếu hành vi hệ điều hành: [Python resource](https://docs.python.org/3.11/library/resource.html), [Python subprocess](https://docs.python.org/3.11/library/subprocess.html), [Linux getrlimit](https://man7.org/linux/man-pages/man2/getrlimit.2.html).

## Kết quả thực tế

| Kiểm chứng | Kết quả |
|---|---|
| test_sandbox_limits.py | **55 passed**, không skip trên Linux |
| D1 + D2 + guard môi trường | **106 passed**, 14,21 giây |
| Toàn bộ backend | **947 passed, 16 skipped**, 355,78 giây |
| Ruff check / format | Qua; 125 file được kiểm tra format |
| mypy strict | Qua, 116 source file |
| check_conventions.py | Qua |
| Probe container cgroup/quyền | Qua cả cấu hình 256 pids và phép thử chặn spawn ở 16 pids |
| Smoke test DuckDB trong container | Qua với AS 2 GiB, threads=2, cgroup 3 GiB/2 CPU |

16 skip là 15 TODO ngoài D2 và test OULAD cần bật riêng. Không có test D2 bị skip trong lần chạy Linux UID 1000 này.

Log và artifact local được Git bỏ qua:

- backend/data/upload-checks/sandbox-limits-regression.log và sandbox-limits-regression.xml.
- backend/data/upload-checks/sandbox-container-checks.log và sandbox-container-checks.json.
- backend/data/upload-checks/sandbox-duckdb-budget.log.

Container probe được tạo tạm và dọn sau chạy; không thay stack hoặc container ứng dụng đang chạy. Không chạy frontend CI hoặc migration vì không đổi các phần đó.
