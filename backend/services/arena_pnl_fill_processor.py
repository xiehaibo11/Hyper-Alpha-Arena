"""
PnL fill processing helpers for Arena exchange synchronization.

This module keeps exchange fill aggregation and database update logic out of
the HTTP route layer.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional

from sqlalchemy.orm import Session

from database.models import AIDecisionLog, ProgramExecutionLog
from database.snapshot_models import HyperliquidTrade
from services.hyperliquid_environment import get_hyperliquid_client

logger = logging.getLogger(__name__)


def process_fills_for_environment(
    db: Session,
    snapshot_db: Session,
    environment: str,
    fills: List[dict],
    wallet_configs: dict,
    exchange: str = "hyperliquid",
) -> dict:
    """
    Process fills for a specific environment and update database records.

    This function:
    1. Updates existing HyperliquidTrade records with fee data
    2. Creates missing HyperliquidTrade records for resting orders that later filled
    3. Updates AIDecisionLog/ProgramExecutionLog.realized_pnl for closed positions

    Args:
        exchange: "hyperliquid" or "binance" - determines which wallet to use for API calls

    Returns summary of updates.
    """
    result = {
        "fills_count": len(fills),
        "unique_orders": 0,
        "trades_updated": 0,
        "trades_created": 0,
        "decisions_updated": 0,
        "program_logs_updated": 0,
        "skipped": 0,
    }

    if not fills:
        return result

    order_aggregates = defaultdict(
        lambda: {
            "total_fee": Decimal("0"),
            "total_pnl": Decimal("0"),
            "fills": [],
        }
    )

    # Binance TP/SL triggered orders can have different order IDs from the
    # stored algo order IDs, so keep a link back to the main order.
    binance_tpsl_to_main = {}

    for fill in fills:
        oid = str(fill.get("oid", ""))
        if not oid:
            continue

        fee = Decimal(str(fill.get("fee", "0")))
        closed_pnl = Decimal(str(fill.get("closedPnl", "0")))

        order_aggregates[oid]["total_fee"] += fee
        order_aggregates[oid]["total_pnl"] += closed_pnl
        order_aggregates[oid]["fills"].append(fill)

        if exchange == "binance" and fill.get("main_order_id"):
            binance_tpsl_to_main[oid] = fill.get("main_order_id")

    result["unique_orders"] = len(order_aggregates)

    trades = snapshot_db.query(HyperliquidTrade).filter(
        HyperliquidTrade.environment == environment
    ).all()

    for trade in trades:
        order_id = str(trade.order_id)
        if order_id in order_aggregates:
            agg = order_aggregates[order_id]
            if trade.fee != agg["total_fee"]:
                trade.fee = agg["total_fee"]
                result["trades_updated"] += 1
        else:
            result["skipped"] += 1

    existing_trade_order_ids = {str(t.order_id) for t in trades if t.order_id}
    existing_trades_by_order_id = {str(t.order_id): t for t in trades if t.order_id}

    def get_order_trigger_time(account_id: int, order_id: str) -> Optional[datetime]:
        """Get actual trigger time for TP/SL order from Hyperliquid API."""
        if exchange != "hyperliquid":
            return None
        key = (account_id, environment)
        if key not in wallet_configs:
            return None
        try:
            client = get_hyperliquid_client(db, account_id, override_environment=environment)
            return client.get_order_trigger_time(db, int(order_id))
        except Exception as e:
            logger.warning(f"Failed to get trigger time for order {order_id}: {e}")
            return None

    decisions = db.query(AIDecisionLog).filter(
        AIDecisionLog.operation.in_(["buy", "sell", "close"]),
        AIDecisionLog.executed == "true",
        AIDecisionLog.hyperliquid_environment == environment,
    ).all()

    order_to_decision = {}
    for decision in decisions:
        for oid in [decision.hyperliquid_order_id, decision.tp_order_id, decision.sl_order_id]:
            if oid:
                order_to_decision[str(oid)] = decision

    if exchange == "binance":
        for triggered_oid, main_oid in binance_tpsl_to_main.items():
            decision = order_to_decision.get(main_oid)
            if decision and triggered_oid not in order_to_decision:
                order_to_decision[triggered_oid] = decision

    program_logs = db.query(ProgramExecutionLog).filter(
        ProgramExecutionLog.success == True,
        ProgramExecutionLog.decision_action.in_(["buy", "sell", "close"]),
    ).all()

    order_to_program_log = {}
    for program_log in program_logs:
        for oid in [program_log.hyperliquid_order_id, program_log.tp_order_id, program_log.sl_order_id]:
            if oid:
                order_to_program_log[str(oid)] = program_log

    if exchange == "binance":
        for triggered_oid, main_oid in binance_tpsl_to_main.items():
            program_log = order_to_program_log.get(main_oid)
            if program_log and triggered_oid not in order_to_program_log:
                order_to_program_log[triggered_oid] = program_log

    for oid, agg in order_aggregates.items():
        existing_trade = existing_trades_by_order_id.get(oid) if exchange == "binance" else None

        if oid in existing_trade_order_ids and exchange != "binance":
            continue

        decision = order_to_decision.get(oid)
        program_log = order_to_program_log.get(oid)

        if not decision and not program_log:
            continue
        fills_list = agg["fills"]
        if not fills_list:
            continue

        total_qty = Decimal("0")
        total_value = Decimal("0")
        latest_time = None

        for fill in fills_list:
            qty = Decimal(str(fill.get("sz", "0")))
            px = Decimal(str(fill.get("px", "0")))
            total_qty += qty
            total_value += qty * px

            fill_time = fill.get("time")
            if fill_time and (latest_time is None or fill_time > latest_time):
                latest_time = fill_time

        if total_qty == 0:
            continue

        avg_price = total_value / total_qty

        if decision:
            side = decision.operation.lower() if decision.operation else "sell"
        elif program_log:
            side = program_log.decision_action.lower() if program_log.decision_action else "sell"
        else:
            fill_side = fills_list[0].get("side", "B")
            side = "buy" if fill_side == "B" else "sell"

        trade_time = None
        if latest_time:
            try:
                trade_time = datetime.fromtimestamp(latest_time / 1000, tz=timezone.utc)
            except Exception:
                trade_time = datetime.utcnow()
        else:
            trade_time = datetime.utcnow()

        if decision:
            account_id = decision.account_id
            wallet_address = decision.wallet_address
            symbol = decision.symbol or fills_list[0].get("coin", "")
            source_info = f"decision {decision.id}"
        else:
            account_id = program_log.account_id
            wallet_address = program_log.wallet_address
            symbol = program_log.decision_symbol or fills_list[0].get("coin", "")
            source_info = f"program_log {program_log.id}"

        if existing_trade and exchange == "binance":
            existing_trade.quantity = total_qty
            existing_trade.price = avg_price
            existing_trade.trade_value = total_value
            existing_trade.fee = agg["total_fee"]
            existing_trade.order_status = "filled"
            if trade_time:
                existing_trade.trade_time = trade_time
            result["trades_updated"] += 1
            logger.info(f"Updated HyperliquidTrade for Binance order {oid} with official fill data")
            continue

        new_trade = HyperliquidTrade(
            account_id=account_id,
            environment=environment,
            wallet_address=wallet_address,
            symbol=symbol,
            side=side,
            quantity=total_qty,
            price=avg_price,
            leverage=1,
            order_id=oid,
            order_status="filled",
            trade_value=total_value,
            fee=agg["total_fee"],
            trade_time=trade_time,
        )
        snapshot_db.add(new_trade)
        existing_trade_order_ids.add(oid)
        result["trades_created"] += 1
        logger.info(f"Created missing HyperliquidTrade for order {oid}, {source_info}")

    for decision in decisions:
        updated = False
        total_pnl = Decimal("0")
        matched_order_ids = set()

        order_ids_to_check = [
            decision.hyperliquid_order_id,
            decision.tp_order_id,
            decision.sl_order_id,
        ]

        for oid in order_ids_to_check:
            if oid:
                order_id_str = str(oid)
                if order_id_str in order_aggregates and order_id_str not in matched_order_ids:
                    agg = order_aggregates[order_id_str]
                    total_pnl += agg["total_pnl"]
                    matched_order_ids.add(order_id_str)

        if exchange == "binance" and decision.hyperliquid_order_id:
            main_oid = str(decision.hyperliquid_order_id)
            for tpsl_oid, linked_main_oid in binance_tpsl_to_main.items():
                if linked_main_oid == main_oid and tpsl_oid not in matched_order_ids:
                    if tpsl_oid in order_aggregates:
                        agg = order_aggregates[tpsl_oid]
                        total_pnl += agg["total_pnl"]
                        matched_order_ids.add(tpsl_oid)
                        logger.info(
                            f"[Binance] Matched TP/SL order {tpsl_oid} to main order {main_oid}, "
                            f"pnl={agg['total_pnl']}, total_pnl={total_pnl}"
                        )

        if matched_order_ids:
            decision.realized_pnl = total_pnl

            trigger_time = None
            for oid in [decision.tp_order_id, decision.sl_order_id]:
                if oid and str(oid) in matched_order_ids:
                    trigger_time = get_order_trigger_time(decision.account_id, str(oid))
                    if trigger_time:
                        logger.info(f"Got trigger time {trigger_time} for order {oid}")
                        break

            decision.pnl_updated_at = trigger_time if trigger_time else datetime.utcnow()
            updated = True

        if not updated and decision.decision_time:
            time_window = timedelta(minutes=5)

            matching_trade = snapshot_db.query(HyperliquidTrade).filter(
                HyperliquidTrade.account_id == decision.account_id,
                HyperliquidTrade.symbol == decision.symbol,
                HyperliquidTrade.environment == environment,
                HyperliquidTrade.trade_time >= decision.decision_time - time_window,
                HyperliquidTrade.trade_time <= decision.decision_time + time_window,
            ).first()

            if matching_trade:
                order_id = str(matching_trade.order_id)
                if order_id in order_aggregates:
                    agg = order_aggregates[order_id]
                    decision.realized_pnl = agg["total_pnl"]
                    decision.pnl_updated_at = matching_trade.trade_time or datetime.utcnow()
                    updated = True

                    if not decision.hyperliquid_order_id:
                        decision.hyperliquid_order_id = order_id

        if updated:
            result["decisions_updated"] += 1

    for program_log in program_logs:
        if program_log.environment and program_log.environment != environment:
            continue

        updated = False
        total_pnl = Decimal("0")
        matched_order_ids = set()

        order_ids_to_check = [
            program_log.hyperliquid_order_id,
            program_log.tp_order_id,
            program_log.sl_order_id,
        ]

        for oid in order_ids_to_check:
            if oid:
                order_id_str = str(oid)
                if order_id_str in order_aggregates and order_id_str not in matched_order_ids:
                    agg = order_aggregates[order_id_str]
                    total_pnl += agg["total_pnl"]
                    matched_order_ids.add(order_id_str)

        if exchange == "binance" and program_log.hyperliquid_order_id:
            main_oid = str(program_log.hyperliquid_order_id)
            for tpsl_oid, linked_main_oid in binance_tpsl_to_main.items():
                if linked_main_oid == main_oid and tpsl_oid not in matched_order_ids:
                    if tpsl_oid in order_aggregates:
                        agg = order_aggregates[tpsl_oid]
                        total_pnl += agg["total_pnl"]
                        matched_order_ids.add(tpsl_oid)
                        logger.info(f"[Binance] Matched TP/SL order {tpsl_oid} to program main order {main_oid}")

        if matched_order_ids:
            program_log.realized_pnl = total_pnl
            if not program_log.environment:
                program_log.environment = environment

            trigger_time = None
            for oid in [program_log.tp_order_id, program_log.sl_order_id]:
                if oid and str(oid) in matched_order_ids:
                    trigger_time = get_order_trigger_time(program_log.account_id, str(oid))
                    if trigger_time:
                        break

            program_log.pnl_updated_at = trigger_time if trigger_time else datetime.utcnow()
            updated = True

        if updated:
            result["program_logs_updated"] += 1

    result["historical_fixed"] = 0
    for decision in decisions:
        if not decision.tp_order_id and not decision.sl_order_id:
            continue
        if not decision.pnl_updated_at:
            continue

        for oid in [decision.tp_order_id, decision.sl_order_id]:
            if not oid:
                continue
            trigger_time = get_order_trigger_time(decision.account_id, str(oid))
            if trigger_time and trigger_time != decision.pnl_updated_at:
                time_diff = abs((trigger_time - decision.pnl_updated_at).total_seconds())
                if time_diff > 60:
                    logger.info(
                        f"Fixing historical pnl_updated_at for decision {decision.id}: "
                        f"{decision.pnl_updated_at} -> {trigger_time}"
                    )
                    decision.pnl_updated_at = trigger_time
                    result["historical_fixed"] += 1
                    break

    return result
