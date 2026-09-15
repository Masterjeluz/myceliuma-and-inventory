import os
from app.database import connection, init_database


def test_init_database_creates_objects_table(tmp_path):
    db_path = str(tmp_path / "test_inventory.db")
    os.environ["INVENTORY_DATABASE_PATH"] = db_path

    init_database()

    with connection() as db:
        tables = [row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "objects" in tables

        columns = [row["name"] for row in db.execute("PRAGMA table_info(objects)").fetchall()]
        assert "id" in columns
        assert "name" in columns
        assert "description" in columns
        assert "quantity" in columns
        assert "provenance" in columns
        assert "created_at" in columns
        assert "updated_at" in columns


def test_wal_mode_and_busy_timeout(tmp_path):
    db_path = str(tmp_path / "test_wal.db")
    os.environ["INVENTORY_DATABASE_PATH"] = db_path

    init_database()

    with connection() as db:
        mode = db.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"

        timeout = db.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout == 15000
