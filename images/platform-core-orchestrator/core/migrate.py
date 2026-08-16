import os
from pathlib import Path

import psycopg


def main():
    url = os.environ.get("CORE_DATABASE_URL")
    if not url: raise RuntimeError("CORE_DATABASE_URL is required")
    migration = Path("/app/migrations/postgresql/001_core.sql").read_text()
    with psycopg.connect(url) as connection:
        exists = connection.execute("SELECT to_regclass('public.operations')").fetchone()[0]
        if not exists: connection.execute(migration)
        connection.commit()
    print("POSTGRES_MIGRATION_OK")


if __name__ == "__main__": main()
