"""Exercise clean and abrupt backend restarts using isolated Compose drill resources."""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[2]
DATABASE = "dataforge_recovery"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def event_count(snapshot: dict[str, Any], kind: str) -> int:
    return sum(event["kind"] == kind for event in snapshot["events"])


def assert_gate(snapshot: dict[str, Any], view: dict[str, Any]) -> None:
    require(view["status"] == "waiting_design_approval", "The API has not reached gate 1")
    checkpoint = snapshot["checkpoint"]
    require(checkpoint["thread_id"] == view["id"], "The checkpoint thread changed")
    require(
        checkpoint["interrupts"] == [{"id": view["interrupt_id"], "value": view["pending"]}],
        "The persisted interrupt differs from the polling projection",
    )
    require(snapshot["run"]["status"] == view["status"], "The database status differs")
    require(snapshot["batch"]["marker_exists"], "The READY marker is missing")
    require(snapshot["batch"]["status"] == "ready", "The batch is not READY")
    require(len(snapshot["jobs"]) == 1, "Profile must have exactly one job")
    job = snapshot["jobs"][0]
    require(
        job["kind"] == "profile"
        and job["status"] == "succeeded"
        and job["attempts"] == 1
        and job["delivered"],
        "The native profile job was not completed and delivered exactly once",
    )
    counts = sorted((table["source_file"], table["row_count"]) for table in job["result"]["tables"])
    require(
        counts == [("customers.csv", 3), ("orders.csv", 3)],
        "The worker did not profile the expected fixture rows",
    )
    require(len(snapshot["designs"]) == 1, "The run must have one presented design")
    require(
        snapshot["designs"][0]["id"] == view["pending"]["design_version_id"],
        "The presented design identity differs",
    )
    require(not snapshot["approvals"] and not snapshot["intents"], "The gate already has a reply")
    require(event_count(snapshot, "modeler_called") == 1, "Modeler ran more than once")
    require(event_count(snapshot, "codegen_probe") == 0, "Codegen ran before approval")


def assert_resumed(before: dict[str, Any], after: dict[str, Any], actor_id: str) -> None:
    require(after["jobs"] == before["jobs"], "Approval repeated the profile job")
    require(after["designs"] == before["designs"], "Approval changed the design")
    require(len(after["approvals"]) == 1, "Approval must be recorded once")
    approval = after["approvals"][0]
    require(approval["decision"] == "approved", "The design was not approved")
    require(approval["actor_id"] == actor_id, "The approver differs from the authenticated user")
    require(
        approval["fingerprint"] == before["designs"][0]["hash"]
        and approval["parts"]["design_version_id"] == before["designs"][0]["id"],
        "Approval is not bound to the presented design",
    )
    require(
        len(after["intents"]) == 1 and after["intents"][0]["delivered"],
        "The accepted decision has not been delivered",
    )
    require(event_count(after, "modeler_called") == 1, "Resume repeated Modeler")
    require(event_count(after, "codegen_probe") == 1, "Resume did not execute one codegen probe")
    modeler_boot = next(
        event["boot_id"] for event in after["events"] if event["kind"] == "modeler_called"
    )
    probe_boot = next(
        event["boot_id"] for event in after["events"] if event["kind"] == "codegen_probe"
    )
    require(modeler_boot != probe_boot, "The decision did not resume in a new backend process")


class Drill:
    def __init__(self, output: Path, base_url: str) -> None:
        self.output = output
        self.output.mkdir(parents=True, exist_ok=False)
        executable = shutil.which("docker")
        if executable is None:
            raise RuntimeError("Docker is not installed")
        self.docker = executable
        self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=15)
        self.actor_id = ""
        self.project_id = ""
        self.started = False

    def command(self, args: list[str], *, input_text: str | None = None) -> str:
        result = subprocess.run(
            [self.docker, *args],
            cwd=ROOT,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=600,
            check=False,
        )
        with (self.output / "compose-output.log").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"command": args, "exit_code": result.returncode}) + "\n")
            stream.write(result.stdout + result.stderr + "\n")
        require(result.returncode == 0, "Docker command failed; inspect compose-output.log")
        return result.stdout.strip()

    def compose(self, args: list[str], *, default: bool = False) -> str:
        files = ["-f", str(ROOT / "docker-compose.yml")]
        if not default:
            files += ["-f", str(ROOT / "docker-compose.recovery.yml")]
        return self.command(["compose", *files, *args])

    def state(self, service: str) -> dict[str, Any]:
        identity = self.compose(["ps", "-aq", service])
        require(bool(identity) and "\n" not in identity, "Expected one container per service")
        state = json.loads(self.command(["inspect", "--format", "{{json .State}}", identity]))
        mounts = json.loads(self.command(["inspect", "--format", "{{json .Mounts}}", identity]))
        return {
            "id": identity,
            "status": state["Status"],
            "pid": state["Pid"],
            "started_at": state["StartedAt"],
            "finished_at": state["FinishedAt"],
            "exit_code": state["ExitCode"],
            "mounts": sorted(
                [
                    {
                        "type": mount["Type"],
                        "name": mount.get("Name"),
                        "source": mount["Source"],
                        "destination": mount["Destination"],
                    }
                    for mount in mounts
                ],
                key=lambda mount: str(mount["destination"]),
            ),
        }

    def wait_health(self) -> None:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                response = self.http.get("/api/health", timeout=3)
                if response.status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(1)
        raise RuntimeError("The backend did not become healthy within 180 seconds")

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.http.request(method, "/api" + path, **kwargs)
        require(
            response.status_code == 200,
            f"{method} {path} returned HTTP {response.status_code}",
        )
        result: dict[str, Any] = response.json()
        return result

    def setup(self, *, build: bool) -> None:
        print("Preparing the isolated recovery database and Compose application", flush=True)
        if build:
            self.compose(["build", "backend"])
        self.compose(["up", "-d", "--wait", "--wait-timeout", "90", "postgres"])
        existing = self.compose(
            [
                "exec",
                "-T",
                "postgres",
                "psql",
                "-X",
                "-U",
                "postgres",
                "-d",
                "postgres",
                "-At",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                "SELECT 1 FROM pg_database WHERE datname = 'dataforge_recovery'",
            ]
        )
        if existing != "1":
            self.compose(
                [
                    "exec",
                    "-T",
                    "postgres",
                    "psql",
                    "-X",
                    "-U",
                    "postgres",
                    "-d",
                    "postgres",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-c",
                    "CREATE DATABASE dataforge_recovery OWNER dataforge",
                ]
            )
        self.started = True
        self.compose(["up", "-d", "backend", "sandbox-worker"])
        self.wait_health()
        account = self.request(
            "POST",
            "/auth/register",
            json={
                "email": f"recovery-{uuid4().hex}@example.test",
                "password": secrets.token_urlsafe(32),
            },
        )
        token = str(account["access_token"])
        self.http.headers["Authorization"] = "Bearer " + token
        import base64

        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        self.actor_id = claims["sub"]
        project = self.request(
            "POST",
            "/projects",
            json={
                "name": "Backend restart drill",
                "slug": "recovery-" + uuid4().hex,
                "review_mode": "solo",
            },
        )
        self.project_id = project["id"]

    def prepare_run(self) -> str:
        prefix = f"/projects/{self.project_id}"
        batch = self.request(
            "POST", prefix + "/batches", json={"required_files": ["customers.csv", "orders.csv"]}
        )
        batch_path = prefix + "/batches/" + batch["id"]
        for filename in ("customers.csv", "orders.csv"):
            path = ROOT / "backend/tests/fixtures/upload/complete" / filename
            with path.open("rb") as stream:
                uploaded = self.request(
                    "POST", batch_path + "/files", files={"file": (filename, stream, "text/csv")}
                )
            require(
                len(uploaded["preview"]) == 3 and len(uploaded["columns"]) == 3,
                "The uploaded fixture preview differs from the expected rows",
            )
            confirmed = self.request(
                "PUT",
                batch_path + "/files/" + uploaded["id"] + "/read-config",
                json={"read_config": uploaded["read_config"]},
            )
            require(confirmed["read_config_confirmed"], "The CSV configuration was not confirmed")
        ready = self.request("POST", batch_path + "/ready")
        require(ready["status"] == "ready", "The uploaded batch is not READY")
        run = self.request(
            "POST",
            prefix + "/runs",
            json={"batch_id": batch["id"], "request_text": "Count fixture orders per snapshot"},
        )
        return str(run["id"])

    def run_path(self, run_id: str) -> str:
        return f"/projects/{self.project_id}/runs/{run_id}"

    def view(self, run_id: str) -> dict[str, Any]:
        view = self.request("GET", self.run_path(run_id))
        require(view["status"] != "failed", "The recovery run failed; inspect backend.log")
        return {key: value for key, value in view.items() if key != "updated_at"}

    def snapshot(self, run_id: str) -> dict[str, Any]:
        source = (
            "import asyncio,json; from recovery_app import snapshot; "
            f"print(json.dumps(asyncio.run(snapshot('{run_id}')),sort_keys=True))"
        )
        result: dict[str, Any] = json.loads(
            self.compose(["exec", "-T", "backend", "python", "-c", source])
        )
        return result

    def wait_gate(self, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            view = self.view(run_id)
            if view["status"] == "waiting_design_approval":
                snapshot = self.snapshot(run_id)
                if snapshot["jobs"][0]["delivered"]:
                    assert_gate(snapshot, view)
                    return view, snapshot
            time.sleep(1)
        raise RuntimeError("The run did not reach gate 1 within 90 seconds")

    def execute_case(self, mode: str) -> dict[str, Any]:
        folder = self.output / mode
        folder.mkdir()
        print(f"Running {mode} backend restart with a fresh HTTP-created run", flush=True)
        run_id = self.prepare_run()
        before_view, before = self.wait_gate(run_id)
        before_process = self.state("backend")
        dependencies = {service: self.state(service) for service in ("postgres", "sandbox-worker")}
        write_json(folder / "before-api.json", before_view)
        write_json(folder / "before-state.json", before)
        write_json(folder / "before-processes.json", {"backend": before_process, **dependencies})
        if mode == "clean":
            self.compose(["stop", "backend"])
        else:
            self.compose(["kill", "-s", "SIGKILL", "backend"])
        stopped = self.state("backend")
        require(stopped["status"] == "exited", "The backend process is still running")
        expected_exit = 0 if mode == "clean" else 137
        require(stopped["exit_code"] == expected_exit, "The backend did not stop as expected")
        write_json(folder / "stopped-process.json", stopped)
        try:
            response = self.http.get("/api/health", timeout=2)
        except httpx.TransportError:
            response = None
        require(response is None or response.status_code != 200, "The stopped API is still serving")
        self.compose(["start", "backend"])
        self.wait_health()
        after_process = self.state("backend")
        write_json(folder / "after-process.json", after_process)
        require(
            before_process["id"] == after_process["id"]
            and before_process["started_at"] != after_process["started_at"],
            "The backend did not start a new process in the preserved container",
        )
        require(before_process["mounts"] == after_process["mounts"], "Backend mounts changed")
        for service, baseline in dependencies.items():
            require(self.state(service) == baseline, f"{service} changed during backend restart")
        after_view = self.view(run_id)
        after = self.snapshot(run_id)
        write_json(folder / "after-api.json", after_view)
        write_json(folder / "after-state.json", after)
        require(after_view == before_view, "The polling projection changed after restart")
        require(after == before, "Committed state, checkpoint or call counts changed after restart")
        body = {
            "interrupt_id": after_view["interrupt_id"],
            "design_version_id": after_view["pending"]["design_version_id"],
            "decision": "approve",
        }
        accepted = self.request("POST", self.run_path(run_id) + "/design-decision", json=body)
        write_json(folder / "decision-response.json", accepted)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            self.view(run_id)
            resumed = self.snapshot(run_id)
            if (
                event_count(resumed, "codegen_probe") == 1
                and all(intent["delivered"] for intent in resumed["intents"])
                and resumed["intents"]
            ):
                break
            time.sleep(1)
        else:
            raise RuntimeError("Approval was not delivered within 30 seconds")
        assert_resumed(before, resumed, self.actor_id)
        repeated = self.http.post("/api" + self.run_path(run_id) + "/design-decision", json=body)
        require(repeated.status_code == 409, "A duplicate decision was accepted")
        require(self.snapshot(run_id) == resumed, "A duplicate decision changed persisted state")
        write_json(folder / "after-decision.json", resumed)
        write_json(folder / "duplicate-response.json", {"status_code": repeated.status_code})
        result = {
            "mode": mode,
            "run_id": run_id,
            "batch_id": before["run"]["batch_id"],
            "thread_id": before["checkpoint"]["thread_id"],
            "design_version_id": before["designs"][0]["id"],
            "design_hash": before["designs"][0]["hash"],
            "interrupt_id": before_view["interrupt_id"],
            "stop_exit_code": stopped["exit_code"],
            "backend_started_before": before_process["started_at"],
            "backend_started_after": after_process["started_at"],
            "job_count": len(resumed["jobs"]),
            "profile_attempts": resumed["jobs"][0]["attempts"],
            "modeler_calls": event_count(resumed, "modeler_called"),
            "codegen_probe_calls": event_count(resumed, "codegen_probe"),
            "approval_count": len(resumed["approvals"]),
            "duplicate_status": repeated.status_code,
            "checks_passed": True,
        }
        write_json(folder / "result.json", result)
        print(
            f"PASS {mode}: gate preserved, one profile, one approval, one codegen probe", flush=True
        )
        return result

    def collect_logs(self) -> None:
        if not self.started:
            return
        for service in ("backend", "sandbox-worker"):
            try:
                text = self.compose(["logs", "--no-color", service])
                (self.output / (service + ".log")).write_text(text + "\n", encoding="utf-8")
            except (RuntimeError, subprocess.SubprocessError):
                print(f"Could not collect {service} logs", flush=True)

    def restore(self) -> None:
        if self.started:
            print("Restoring the default backend and worker Compose configuration", flush=True)
            self.compose(["up", "-d", "backend", "sandbox-worker"], default=True)
            self.wait_health()
            identity = self.compose(["ps", "-q", "backend"], default=True)
            command = json.loads(
                self.command(["inspect", "--format", "{{json .Config.Cmd}}", identity])
            )
            require(
                "app.main:create_app" in command and "recovery_app:create_app" not in command,
                "The default backend command was not restored",
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-build", action="store_true")
    options = parser.parse_args()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = options.output or ROOT / "data/restart-checks" / (stamp + "-" + uuid4().hex[:8])
    drill = Drill(output.resolve(), options.base_url)
    summary: dict[str, Any] = {
        "schema_version": 1,
        "started_at": datetime.now(UTC).isoformat(),
        "database": DATABASE,
        "project_id": None,
        "cases": [],
        "restored_default_backend": False,
        "scenario_checks_passed": False,
        "passed": False,
    }
    try:
        drill.setup(build=not options.skip_build)
        summary["project_id"] = drill.project_id
        for mode in ("clean", "abrupt"):
            summary["cases"].append(drill.execute_case(mode))
        summary["scenario_checks_passed"] = True
    finally:
        try:
            drill.collect_logs()
            drill.restore()
            summary["restored_default_backend"] = drill.started
            summary["passed"] = bool(summary["scenario_checks_passed"] and drill.started)
        finally:
            drill.http.close()
            summary["finished_at"] = datetime.now(UTC).isoformat()
            write_json(output / "summary.json", summary)
            print(f"Evidence: {output}", flush=True)
    print("Both backend restart scenarios passed", flush=True)


if __name__ == "__main__":
    main()
