"""
Set account_strategy_configs.scheduled_trigger_enabled default to FALSE.

The Decision AI should primarily run from realtime signal-pool triggers.
Scheduled triggering remains available as an explicit fallback, but new traders
must not opt into interval decisions by default.
"""
import os
import sys

from sqlalchemy import inspect, text

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
sys.path.insert(0, PROJECT_ROOT)

from database.connection import engine  # noqa: E402


def upgrade() -> None:
    inspector = inspect(engine)
    table = "account_strategy_configs"
    column = "scheduled_trigger_enabled"

    if column not in {col["name"] for col in inspector.get_columns(table)}:
        print(f"⏭️ Column {column} does not exist in {table}, skipping")
        return

    if engine.dialect.name != "postgresql":
        print(f"⏭️ Dialect {engine.dialect.name} does not support ALTER COLUMN DEFAULT here, skipping")
        return

    with engine.connect() as conn:
        conn.execute(text(
            f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT FALSE"
        ))
        conn.commit()
        print(f"✅ Set {table}.{column} default to FALSE")


if __name__ == "__main__":
    print("Running migration: set_strategy_scheduled_default_false")
    upgrade()
    print("Migration completed")
