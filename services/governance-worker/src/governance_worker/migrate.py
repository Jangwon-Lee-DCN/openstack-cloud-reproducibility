from __future__ import annotations

import os
from pathlib import Path


def apply_migrations(connection, migration_dir: str | None = None) -> list[int]:
    """Apply ordered PostgreSQL migrations, using their durable version table."""
    root = Path(migration_dir or os.getenv("GOVERNANCE_MIGRATIONS", "/app/migrations"))
    paths = sorted(root.glob("[0-9][0-9][0-9]_*.sql"))
    if not paths:
        raise RuntimeError(f"no governance migrations found under {root}")
    applied = []
    table_exists = connection.execute(
        "SELECT to_regclass('public.governance_schema_version') IS NOT NULL").fetchone()[0]
    known = set()
    if table_exists:
        known = {row[0] for row in connection.execute(
            "SELECT version FROM governance_schema_version").fetchall()}
    for path in paths:
        version = int(path.name.split("_", 1)[0])
        if version in known:
            continue
        connection.execute(path.read_text(encoding="utf-8"))
        applied.append(version)
        known.add(version)
    return applied
