
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.database.connection import (
    get_connection, DB_PATH
)
from backend.database.models import SCHEMA


def main():
    with get_connection() as conn:
        conn.executescript(SCHEMA)

        tabelas = conn.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """).fetchall()

    print("\nBanco SQLite inicializado!")
    print(f"Local: {DB_PATH}")
    print("\nTabelas encontradas:")

    for tabela in tabelas:
        print(f"  - {tabela['name']}")

    print(f"\nTotal: {len(tabelas)} tabelas")


if __name__ == "__main__":
    main()
