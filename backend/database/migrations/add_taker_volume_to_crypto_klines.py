#!/usr/bin/env python3
"""
Migration: Add taker buy/sell volume + notional columns to crypto_klines.

The event-contract order-flow signal (CVD-fade) needs per-1m-candle taker
buy/sell volume. Binance klines carry this directly (taker_buy_base/quote);
storing it lets backtests/tuning read order-flow straight from the DB instead
of paging the exchange REST API every call.

All columns are nullable (existing rows / exchanges without taker data stay
NULL). Idempotent via ADD COLUMN IF NOT EXISTS.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from connection import SessionLocal


_COLUMNS = (
    "taker_buy_volume",
    "taker_sell_volume",
    "taker_buy_notional",
    "taker_sell_notional",
)


def upgrade():
    """Apply the migration"""
    print("Starting migration: add_taker_volume_to_crypto_klines")
    db = SessionLocal()
    try:
        for col in _COLUMNS:
            db.execute(text(
                f"ALTER TABLE crypto_klines ADD COLUMN IF NOT EXISTS {col} DECIMAL(24, 8)"
            ))
        db.commit()
        print("  ✓ taker volume/notional columns ensured on crypto_klines")
    except Exception as e:
        db.rollback()
        print(f"Migration failed: {e}")
        raise
    finally:
        db.close()


def downgrade():
    """Rollback the migration"""
    print("Starting rollback: add_taker_volume_to_crypto_klines")
    db = SessionLocal()
    try:
        for col in _COLUMNS:
            db.execute(text(f"ALTER TABLE crypto_klines DROP COLUMN IF EXISTS {col}"))
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
    parser = argparse.ArgumentParser(description="Crypto Klines Taker Volume Migration")
    parser.add_argument("--rollback", action="store_true", help="Rollback the migration")
    args = parser.parse_args()
    downgrade() if args.rollback else upgrade()
