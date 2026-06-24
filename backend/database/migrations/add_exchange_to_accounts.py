#!/usr/bin/env python3
"""Migration: add an `exchange` column to accounts.

AI traders can be configured per exchange (binance / okx / hyperliquid). The
column is nullable with a 'binance' default so existing rows stay valid.
Idempotent via ADD COLUMN IF NOT EXISTS.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from connection import SessionLocal


def upgrade():
    print("Starting migration: add_exchange_to_accounts")
    db = SessionLocal()
    try:
        db.execute(text(
            "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS exchange VARCHAR(20) DEFAULT 'binance'"
        ))
        db.execute(text(
            "UPDATE accounts SET exchange = 'binance' WHERE exchange IS NULL"
        ))
        db.commit()
        print("  ✓ exchange column ensured on accounts")
    except Exception as e:
        db.rollback()
        print(f"Migration failed: {e}")
        raise
    finally:
        db.close()


def downgrade():
    print("Starting rollback: add_exchange_to_accounts")
    db = SessionLocal()
    try:
        db.execute(text("ALTER TABLE accounts DROP COLUMN IF EXISTS exchange"))
        db.commit()
        print("Rollback completed successfully!")
    except Exception as e:
        db.rollback()
        print(f"Rollback failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Accounts exchange column migration")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    downgrade() if args.rollback else upgrade()
