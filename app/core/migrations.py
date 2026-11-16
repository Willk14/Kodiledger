"""Apply db/migrations/*.sql in order and record each in schema_migrations.

Usage (owner connection, never the app or system role):
    MIGRATION_DATABASE_URL=postgresql://owner@host/db python -m app.core.migrations
    ... python -m app.core.migrations --baseline 0020   # existing DB, already migrated by hand
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"
_VERSION = re.compile(r"^(\d{4})_[a-z0-9_]+$")
_LAST_COMMIT = re.compile(r"^\s*COMMIT\s*;\s*$", re.IGNORECASE | re.MULTILINE)
_LOCK_KEY = 7_412_002  # arbitrary advisory-lock id for this runner

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def migration_files() -> list[Path]:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    for path in files:
        if not _VERSION.match(path.stem):
            raise RuntimeError(f"Unexpected migration file name: {path.name}")
    return files


def pending(applied: set[str]) -> list[str]:
    return [p.stem for p in migration_files() if p.stem not in applied]


def with_record(sql: str, version: str) -> str:
    """Record the version inside the migration's own transaction.

    Files with explicit BEGIN/COMMIT get the insert before their last COMMIT;
    files without run as one implicit transaction in the simple query protocol.
    """
    record = f"INSERT INTO schema_migrations (version) VALUES ('{version}');\n"
    commits = list(_LAST_COMMIT.finditer(sql))
    if commits:
        at = commits[-1].start()
        return sql[:at] + record + sql[at:]
    return sql.rstrip() + "\n" + record


async def migrate(url: str, baseline: str | None = None) -> list[str]:
    import asyncpg

    conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    try:
        await conn.execute("SELECT pg_advisory_lock($1)", _LOCK_KEY)
        await conn.execute(CREATE_TABLE)
        applied = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")}

        if baseline:
            marked = [v for v in pending(applied) if v[:4] <= baseline]
            await conn.executemany(
                "INSERT INTO schema_migrations (version) VALUES ($1)", [(v,) for v in marked]
            )
            return marked

        if not applied and await conn.fetchval("SELECT to_regclass('public.landlords')"):
            raise RuntimeError(
                "Schema exists but no migrations are recorded. Run with --baseline <last applied "
                "number> first (check the database before choosing it)."
            )

        done = []
        for path in migration_files():
            if path.stem in applied:
                continue
            await conn.execute(with_record(path.read_text(encoding="utf-8"), path.stem))
            done.append(path.stem)
            print(f"applied {path.name}", flush=True)
        return done
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", help="mark migrations up to this number (e.g. 0020) as applied without running them")
    args = parser.parse_args()
    if args.baseline and not re.fullmatch(r"\d{4}", args.baseline):
        parser.error("--baseline takes a 4-digit migration number, e.g. 0020")
    url = os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        parser.error("set MIGRATION_DATABASE_URL to the database owner connection")
    result = asyncio.run(migrate(url, args.baseline))
    print(("baselined: " if args.baseline else "applied: ") + (", ".join(result) or "nothing pending"))


if __name__ == "__main__":
    main()
