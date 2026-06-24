#!/usr/bin/env python3
"""Migration: create event_contract_config table and seed one default row.

Idempotent: creates the table only if missing, seeds only if empty.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from connection import SessionLocal


def upgrade():
    print("Starting migration: seed_event_contract_config")
    db = SessionLocal()
    try:
        exists = db.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'event_contract_config'
            )
        """)).scalar()
        if not exists:
            print("Creating event_contract_config table...")
            db.execute(text("""
                CREATE TABLE event_contract_config (
                    id SERIAL PRIMARY KEY,
                    data TEXT NOT NULL DEFAULT '{}',
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """))
            db.commit()

        count = db.execute(text("SELECT COUNT(*) FROM event_contract_config")).scalar()
        if count == 0:
            print("Seeding default event_contract_config row...")
            db.execute(text("INSERT INTO event_contract_config (data) VALUES ('{}')"))
            db.commit()
        else:
            print("  event_contract_config already seeded, skipping")
    except Exception as e:
        db.rollback()
        print(f"  migration error (non-fatal): {e}")
    finally:
        db.close()


if __name__ == "__main__":
    upgrade()
