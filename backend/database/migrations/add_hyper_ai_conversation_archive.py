#!/usr/bin/env python3
"""Add archive metadata for Hyper AI conversations."""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import create_engine, text

from database.connection import DATABASE_URL


def migrate():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        for ddl in (
            """
            ALTER TABLE hyper_ai_conversations
            ADD COLUMN IF NOT EXISTS is_archived BOOLEAN DEFAULT FALSE
            """,
            """
            ALTER TABLE hyper_ai_conversations
            ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP
            """,
            """
            ALTER TABLE hyper_ai_conversations
            ADD COLUMN IF NOT EXISTS archive_object_key TEXT
            """,
            """
            ALTER TABLE hyper_ai_conversations
            ADD COLUMN IF NOT EXISTS archive_url TEXT
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_hyper_ai_conversations_archived
            ON hyper_ai_conversations(is_archived, updated_at DESC)
            """,
        ):
            conn.execute(text(ddl))
        conn.execute(text(
            "UPDATE hyper_ai_conversations SET is_archived = FALSE WHERE is_archived IS NULL"
        ))
        conn.commit()
        print("Migration completed: Hyper AI conversation archive metadata ready")


def upgrade():
    migrate()


if __name__ == "__main__":
    migrate()
