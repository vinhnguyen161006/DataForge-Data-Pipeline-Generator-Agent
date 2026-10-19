"""Prepare CSV fixtures and verify isolated project permissions."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import secrets
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import duckdb
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.api.routes import auth, projects
from app.core import eventloop
from app.core.config import get_api_settings
from app.db.models import Project, ProjectMember, User
from app.db.session import make_engine, make_sessionmaker
from app.ingest.sniff import sniff_csv

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

BACKEND = Path(__file__).resolve().parents[1]
LOCAL = BACKEND / "data" / "upload-checks"
FIXTURES = BACKEND / "tests" / "fixtures" / "upload"


def prepare_inputs() -> dict[str, Any]:
    """Copy immutable fixtures locally and verify their known statistical properties."""
    expected = json.loads((FIXTURES / "expected.json").read_text())
    inventory: dict[str, Any] = {}
    for case in ("complete", "missing", "semicolon"):
        files = {}
        for source in sorted((FIXTURES / case).glob("*.csv")):
            target = LOCAL / "input" / case / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            content = source.read_bytes()
            if target.exists() and target.read_bytes() != content:
                raise ValueError(f"Local input was changed: {target}")
            target.write_bytes(content)
            files[source.name] = hashlib.sha256(content).hexdigest()
        inventory[case] = {
            "files": files,
            "missing": sorted(set(expected["required_files"]) - set(files)),
        }
    complete = LOCAL / "input" / "complete"
    with (complete / "customers.csv").open(newline="") as stream:
        customers = list(csv.DictReader(stream))
    with (complete / "orders.csv").open(newline="") as stream:
        orders = list(csv.DictReader(stream))
    identifiers = [row["customer_id"] for row in customers]
    order_customers = {row["customer_id"] for row in orders}
    observed = {
        "customers_rows": len(customers),
        "orders_rows": len(orders),
        "orphan_orders": sum(row["customer_id"] not in identifiers for row in orders),
        "customers_without_orders": sorted(set(identifiers) - order_customers),
        "total_amount": str(sum(Decimal(row["amount"]) for row in orders)),
        "customer_ids": identifiers,
    }
    if observed != expected["expected"]:
        raise ValueError(f"Fixture results differ from expected.json: {observed}")
    semicolon = LOCAL / "input" / "semicolon" / "orders.csv"
    detected = sniff_csv(semicolon)
    if detected.config.delimiter != ";" or len(detected.columns) != 3:
        raise ValueError("The semicolon fixture did not sniff as three columns")
    with semicolon.open(newline="") as stream:
        wrong_columns = csv.DictReader(stream, delimiter=",").fieldnames
    if wrong_columns is None or len(wrong_columns) != 1:
        raise ValueError("The deliberately wrong delimiter did not produce one column")
    with duckdb.connect() as connection:
        configured = connection.execute(
            "SELECT customer_id, city FROM read_csv(?, all_varchar=true, nullstr=['', 'NA'])",
            [str(complete / "customers.csv")],
        ).fetchall()
        unconfigured = connection.execute(
            "SELECT city FROM read_csv(?, all_varchar=true, nullstr=['']) "
            "WHERE customer_id = '002'",
            [str(complete / "customers.csv")],
        ).fetchone()
    if configured != [("001", "Hanoi"), ("002", None), ("003", "Hue")]:
        raise ValueError("Explicit CSV configuration lost identifiers or null semantics")
    if unconfigured != ("NA",):
        raise ValueError("The unconfigured NA token should remain text")
    return {"inventory": inventory, "observed": observed, "delimiter_and_null_checks": "passed"}


def local_accounts(verify_only: bool) -> dict[str, str]:
    """Keep local-only credentials stable across independent verification processes."""
    path = LOCAL / "accounts.json"
    if not path.exists():
        if verify_only:
            raise FileNotFoundError("Run preparation before verification")
        path.write_text(
            json.dumps(
                {"namespace": secrets.token_hex(4), "password": secrets.token_urlsafe(24)}, indent=2
            )
            + "\n"
        )
        path.chmod(0o600)
    saved = json.loads(path.read_text())
    return {"namespace": str(saved["namespace"]), "password": str(saved["password"])}


async def account_headers(
    client: AsyncClient, email: str, password: str, verify_only: bool
) -> dict[str, str]:
    if not verify_only:
        response = await client.post(
            "/api/auth/register", json={"email": email, "password": password}
        )
        if response.status_code not in (200, 409):
            raise RuntimeError(f"Account setup returned HTTP {response.status_code}")
    response = await client.post("/api/auth/token", data={"username": email, "password": password})
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def project_id(
    client: AsyncClient, headers: dict[str, str], slug: str, name: str, verify_only: bool
) -> UUID:
    response = await client.get("/api/projects", headers=headers)
    response.raise_for_status()
    for project in response.json():
        if project["slug"] == slug:
            return UUID(project["id"])
    if verify_only:
        raise LookupError(f"Project was not committed: {slug}")
    response = await client.post(
        "/api/projects",
        headers=headers,
        json={"name": name, "slug": slug, "review_mode": "team"},
    )
    response.raise_for_status()
    return UUID(response.json()["id"])


async def check_visibility(
    factory: async_sessionmaker[AsyncSession], ids: dict[str, UUID], emails: dict[str, str]
) -> list[dict[str, str]]:
    async with factory() as observer:
        rows = (
            await observer.execute(
                select(User.email, Project.slug, ProjectMember.role)
                .select_from(ProjectMember)
                .join(User, User.id == ProjectMember.user_id)
                .join(Project, Project.id == ProjectMember.project_id)
                .where(Project.id.in_(ids.values()))
            )
        ).all()
        outsider = await observer.scalar(select(User.id).where(User.email == emails["outsider"]))
    expected = {
        (emails["tu"], "a", "engineer"),
        (emails["vinh"], "a", "reviewer"),
        (emails["vinh"], "b", "engineer"),
        (emails["tu"], "b", "reviewer"),
    }
    actual = {
        (email, "a" if slug.startswith("upload-check-project-a-") else "b", role.value)
        for email, slug, role in rows
    }
    if actual != expected or outsider is None:
        raise ValueError("A fresh session did not observe the committed accounts and role matrix")
    return [
        {"email": email, "project": slug, "role": role.value} for email, slug, role in sorted(rows)
    ]


async def prepare(verify_only: bool) -> dict[str, Any]:
    settings = get_api_settings()
    app_url = make_url(settings.app_database_url)
    test_url = make_url(os.environ["DATAFORGE_TEST_DATABASE_URL"])
    checkpoint_url = make_url(settings.checkpoint_database_url)
    if (
        app_url.database != "dataforge_test"
        or app_url != test_url
        or checkpoint_url.set(drivername=app_url.drivername) != app_url
    ):
        raise ValueError("APP, TEST and CHECKPOINT must identify the same dataforge_test database")
    storage = settings.storage_root.resolve()
    if storage != LOCAL / "storage":
        raise ValueError("Upload check storage must be backend/data/upload-checks/storage")
    storage.mkdir(parents=True, exist_ok=True)
    inputs = prepare_inputs()
    accounts = local_accounts(verify_only)
    emails = {
        name: f"upload-check-{name}-{accounts['namespace']}@example.test"
        for name in ("tu", "vinh", "outsider")
    }
    engine = make_engine(settings.app_database_url)
    factory = make_sessionmaker(engine)
    app = FastAPI()
    app.state.sessionmaker = factory
    app.include_router(auth.router, prefix="/api")
    app.include_router(projects.router, prefix="/api")
    checks: list[dict[str, Any]] = []
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://upload-checks.test"
        ) as client:
            headers = {
                name: await account_headers(client, email, accounts["password"], verify_only)
                for name, email in emails.items()
            }
            ids = {
                name: await project_id(
                    client,
                    headers[owner],
                    f"upload-check-project-{name}-{accounts['namespace']}",
                    f"Upload Check Project {name.upper()}",
                    verify_only,
                )
                for name, owner in (("a", "tu"), ("b", "vinh"))
            }
            if verify_only:
                await check_visibility(factory, ids, emails)
            cases = [
                ("engineer_a_grants_reviewer", "POST", "a", "tu", 204, "vinh"),
                ("engineer_b_grants_reviewer", "POST", "b", "vinh", 204, "tu"),
                ("reviewer_b_cannot_grant", "POST", "b", "tu", 403, "outsider"),
                ("reviewer_a_cannot_grant", "POST", "a", "vinh", 403, "outsider"),
                ("outsider_cannot_grant", "POST", "a", "outsider", 403, "vinh"),
                ("engineer_reads_history", "GET", "a", "tu", 200, None),
                ("reviewer_reads_history", "GET", "b", "tu", 200, None),
                ("outsider_cannot_read", "GET", "a", "outsider", 403, None),
                ("missing_token", "GET", "a", None, 401, None),
            ]
            for label, method, project, actor, expected, target in cases:
                path = f"/api/projects/{ids[project]}"
                selected_headers = headers[actor] if actor else {}
                if method == "POST":
                    response = await client.post(
                        path + "/members",
                        headers=selected_headers,
                        json={"email": emails[str(target)], "role": "reviewer"},
                    )
                else:
                    response = await client.get(path + "/approvals", headers=selected_headers)
                if response.status_code != expected:
                    raise ValueError(
                        f"{label}: expected HTTP {expected}, got {response.status_code}"
                    )
                checks.append(
                    {"check": label, "expected": expected, "actual": response.status_code}
                )
        memberships = await check_visibility(factory, ids, emails)
    finally:
        await engine.dispose()
    return {
        "report_version": 1,
        "verify_only": verify_only,
        "process_id": os.getpid(),
        "database": app_url.database,
        "inputs": inputs,
        "projects": {k: str(v) for k, v in ids.items()},
        "memberships": memberships,
        "checks": checks,
        "new_session_visibility": "passed",
        "scope": "Auth/projects, session visibility and CSV checks; excludes FR-21 and worker",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    result = eventloop.run(prepare(args.verify_only))
    path = LOCAL / ("checks-verify.json" if args.verify_only else "checks.json")
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Upload checks passed: {len(result['checks'])} permissions; sessions and CSV verified")
    print(f"Report: {path.relative_to(BACKEND)}")


if __name__ == "__main__":
    main()
