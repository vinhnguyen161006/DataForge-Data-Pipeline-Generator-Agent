"""Child environment boundaries, including a real subprocess on the current platform."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from worker.sandbox import build_env, start_child_process

BLOCKED_KEYS = (
    "DATAFORGE_APP_DATABASE_URL",
    "DATAFORGE_WAREHOUSE_DSN",
    "DATAFORGE_JWT_SECRET",
    "DATAFORGE_GEMINI_API_KEY",
    "DATAFORGE_GITHUB_TOKEN",
    "DATABASE_URL",
    "PGPASSWORD",
    "AWS_SECRET_ACCESS_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "PYTHONPATH",
    "PYTHONHOME",
    "LD_PRELOAD",
    "LD_LIBRARY_PATH",
    "UNLISTED_VALUE",
)


def test_child_environment_keeps_only_the_declared_parent_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed = {"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C", "TZ": "UTC"}
    for key, value in allowed.items():
        monkeypatch.setenv(key, value)
    for key in BLOCKED_KEYS:
        monkeypatch.setenv(key, "fixture-parent-only")
    env = build_env(tmp_path)
    assert all(env[key] == value for key, value in allowed.items())
    assert set(BLOCKED_KEYS).isdisjoint(env)
    assert all(os.environ[key] == "fixture-parent-only" for key in BLOCKED_KEYS)


def test_home_temp_profiles_and_outputs_are_writable_inside_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in ("HOME", "USERPROFILE", "TMPDIR", "TEMP", "TMP", "DBT_PROFILES_DIR"):
        monkeypatch.setenv(key, str(tmp_path.parent / "parent-only"))
    env = build_env(tmp_path)
    for key in (
        "HOME",
        "USERPROFILE",
        "TMPDIR",
        "TEMP",
        "TMP",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "DBT_PROFILES_DIR",
        "DBT_PROJECT_DIR",
        "DBT_TARGET_PATH",
        "DBT_LOG_PATH",
    ):
        directory = Path(env[key])
        assert directory.is_dir()
        assert directory.is_relative_to(tmp_path.resolve())
    assert env["TMPDIR"] == env["TEMP"] == env["TMP"]
    assert env["HOME"] == env["USERPROFILE"]
    assert env["PYTHONNOUSERSITE"] == "1"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["PYTHONUNBUFFERED"] == "1"


def test_environment_results_and_parent_are_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LANG", "C")
    before = dict(os.environ)
    first = build_env(tmp_path)
    first["LANG"] = "changed"
    first["ADDED_BY_CALLER"] = "local-only"
    second = build_env(tmp_path)
    assert second["LANG"] == "C"
    assert "ADDED_BY_CALLER" not in second
    assert set(os.environ) == set(before)
    assert all(os.environ.get(key) == value for key, value in before.items())


@pytest.mark.parametrize(
    "key", ["DBT_PROFILES_DIR", "DBT_PROJECT_DIR", "DBT_TARGET_PATH", "DBT_LOG_PATH"]
)
def test_only_dbt_directory_overrides_are_supported(tmp_path: Path, key: str) -> None:
    extra = {key: "custom directory/nested"}
    before = dict(extra)
    env = build_env(tmp_path, extra)
    assert env[key] == str(tmp_path.resolve() / "custom directory" / "nested")
    assert Path(env[key]).is_dir()
    assert extra == before


@pytest.mark.parametrize(
    "key",
    [*BLOCKED_KEYS, "PATH", "HOME", "TMPDIR", "TEMP", "DBT_ENV_SECRET_EXAMPLE", "profiles_dir"],
)
def test_overrides_reject_every_key_outside_the_schema(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError, match="Unsupported or invalid") as caught:
        build_env(tmp_path, {key: "fixture-do-not-print"})
    assert "fixture-do-not-print" not in str(caught.value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "../outside",
        "safe/../../outside",
        "/outside/root",
        "C:/outside",
        r"C:\outside",
        r"..\outside",
        "//server/share",
        "bad\x00name",
    ],
)
def test_dbt_overrides_cannot_escape_workspace(tmp_path: Path, value: str) -> None:
    with pytest.raises(ValueError, match=r"workspace|overrides"):
        build_env(tmp_path, {"DBT_PROFILES_DIR": value})


@pytest.mark.skipif(os.name != "posix", reason="Symlink boundary verified on Linux")
@pytest.mark.parametrize("outside", [False, True])
def test_dbt_directory_override_rejects_symlinks_even_inside_workspace(
    tmp_path: Path, outside: bool
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "outside" if outside else workspace / "real"
    target.mkdir()
    (workspace / "linked").symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        build_env(workspace, {"DBT_PROFILES_DIR": "linked/profiles"})
    assert not (target / "profiles").exists()


@pytest.mark.skipif(os.name != "posix", reason="Symlink boundary verified on Linux")
def test_default_home_cannot_redirect_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "home").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        build_env(workspace)
    assert list(outside.iterdir()) == []


def test_environment_requires_an_existing_workspace_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="existing directory"):
        build_env(tmp_path / "missing")
    file = tmp_path / "file"
    file.write_text("occupied")
    with pytest.raises(ValueError, match="existing directory"):
        build_env(file)


def test_file_cannot_be_used_as_a_child_directory(tmp_path: Path) -> None:
    (tmp_path / "home").write_text("occupied")
    with pytest.raises(ValueError, match="occupied"):
        build_env(tmp_path)


def test_separate_workspaces_do_not_share_home_or_temp(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    a = build_env(first)
    b = build_env(second)
    for key in ("HOME", "TMPDIR", "DBT_PROFILES_DIR", "DBT_TARGET_PATH", "DBT_LOG_PATH"):
        assert a[key] != b[key]


@pytest.mark.parametrize("args", [[], ["python"], [""], ["/missing/python"], ["bad\x00name"]])
def test_launch_rejects_missing_or_relative_executables(tmp_path: Path, args: list[str]) -> None:
    with pytest.raises(ValueError, match=r"argv|executable"):
        start_child_process(args, workspace=tmp_path)


def test_invalid_environment_is_rejected_before_a_process_is_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launch = Mock(side_effect=AssertionError("An invalid environment must never start a child"))
    monkeypatch.setattr("worker.sandbox.subprocess.Popen", launch)
    with pytest.raises(ValueError, match="Unsupported or invalid"):
        start_child_process(
            [sys.executable, "-c", "pass"],
            workspace=tmp_path,
            extra_env={"DATAFORGE_APP_DATABASE_URL": "fixture-do-not-print"},
        )
    launch.assert_not_called()


def test_real_child_has_clean_environment_fixed_cwd_and_literal_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "child workspace"
    workspace.mkdir()
    (tmp_path / ".env").write_text("DATAFORGE_APP_DATABASE_URL=fixture-file-only\n")
    for key in BLOCKED_KEYS:
        monkeypatch.setenv(key, "fixture-parent-only")
    literal = "; touch escaped.txt"
    source = """
import json
import os
import sys
import tempfile
from pathlib import Path

blocked = json.loads(sys.argv[1])
home_file = Path.home() / "child.txt"
home_file.write_text("child")
with tempfile.NamedTemporaryFile() as temporary:
    temp_path = str(Path(temporary.name).parent)
print(json.dumps({
    "blocked_present": {key: key in os.environ for key in blocked},
    "cwd": str(Path.cwd()),
    "home": str(Path.home()),
    "temp": temp_path,
    "profiles": os.environ.get("DBT_PROFILES_DIR"),
    "home_write": home_file.read_text(),
    "literal": sys.argv[2],
    "settings_imported": "app.core.config" in sys.modules,
}))
"""
    args = [sys.executable, "-I", "-c", source, json.dumps(BLOCKED_KEYS), literal]
    with start_child_process(args, workspace=workspace) as child:
        try:
            stdout, stderr = child.communicate(timeout=10)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=5)
        assert child.returncode == 0, stderr.decode()
    result = json.loads(stdout)
    assert all(present is False for present in result["blocked_present"].values())
    assert Path(result["cwd"]) == workspace.resolve()
    assert Path(result["home"]).is_relative_to(workspace.resolve())
    assert Path(result["temp"]).is_relative_to(workspace.resolve())
    assert Path(result["profiles"]).is_relative_to(workspace.resolve())
    assert result["home_write"] == "child"
    assert result["literal"] == literal
    assert result["settings_imported"] is False
    assert not (workspace / "escaped.txt").exists()
    assert b"fixture-parent-only" not in stdout + stderr
    assert b"fixture-file-only" not in stdout + stderr
