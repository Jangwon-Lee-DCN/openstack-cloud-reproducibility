import os
from pathlib import Path

import psycopg


def main():
    url = os.environ.get("CORE_DATABASE_URL")
    if not url: raise RuntimeError("CORE_DATABASE_URL is required")
    with psycopg.connect(url) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        if connection.execute("SELECT to_regclass('public.operations')").fetchone()[0]:
            connection.execute("INSERT INTO schema_migrations(version) VALUES('001_core') ON CONFLICT DO NOTHING")
        for path in sorted(Path("/app/migrations/postgresql").glob("*.sql")):
            version = path.stem
            if connection.execute("SELECT 1 FROM schema_migrations WHERE version=%s", (version,)).fetchone(): continue
            connection.execute(path.read_text())
            connection.execute("INSERT INTO schema_migrations(version) VALUES(%s)", (version,))
        connection.commit()
    print("POSTGRES_MIGRATION_OK")


if __name__ == "__main__": main()
