"""Market and historical backtest query tools for AI program coding."""

import json
from typing import List, Optional
from sqlalchemy.orm import Session

from database.models import AccountProgramBinding, BacktestResult, BacktestTriggerLog

def _query_market_data(db: Session, symbol: str, period: str, exchange: str = "hyperliquid") -> str:
    """Query current market data for AI to understand indicator value ranges.

    Args:
        db: Database session
        symbol: Trading symbol (e.g., BTC, ETH)
        period: Time period for indicators (e.g., 1h, 5m)
        exchange: Exchange to query from ('hyperliquid', 'binance', or 'okx')
    """
    try:
        from program_trader.data_provider import DataProvider
        import requests

        # Get current price based on exchange
        if exchange == "binance":
            # Use Binance public API to get price
            binance_symbol = f"{symbol.upper()}USDT"
            resp = requests.get(
                "https://fapi.binance.com/fapi/v1/ticker/price",
                params={"symbol": binance_symbol},
                timeout=5
            )
            if resp.status_code == 200:
                price = float(resp.json().get("price", 0))
            else:
                price = None
        elif exchange == "okx":
            from services.exchanges.okx_adapter import OKXAdapter
            price = OKXAdapter().fetch_price(symbol)
        else:
            from services.hyperliquid_market_data import get_last_price_from_hyperliquid
            price = get_last_price_from_hyperliquid(symbol, "mainnet")

        # Create data provider with exchange parameter
        data_provider = DataProvider(db=db, account_id=0, environment="mainnet", exchange=exchange)

        # Get all indicators
        indicators = {}
        for ind in ["RSI14", "RSI7", "MA5", "MA10", "MA20", "EMA20", "EMA50", "EMA100",
                    "MACD", "BOLL", "ATR14", "VWAP", "STOCH", "OBV"]:
            result = data_provider.get_indicator(symbol, ind, period)
            if result:
                indicators[ind] = result

        # Get all flow metrics
        flow_metrics = {}
        for metric in ["CVD", "OI", "OI_DELTA", "TAKER", "FUNDING", "DEPTH", "IMBALANCE"]:
            result = data_provider.get_flow(symbol, metric, period)
            if result:
                flow_metrics[metric] = result

        # Get regime
        regime = data_provider.get_regime(symbol, period)

        # Format response
        result = {
            "symbol": symbol,
            "period": period,
            "exchange": exchange,
            "current_price": float(price) if price else None,
            "indicators": indicators,
            "flow_metrics": flow_metrics,
            "regime": {"regime": regime.regime, "confidence": regime.conf}
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})

def _get_backtest_history(db: Session, program_id: Optional[int], user_id: int, limit: int = 10) -> str:
    """Get backtest history for the current program."""
    try:
        if not program_id:
            return json.dumps({"error": "No program selected. This tool only works when editing an existing program."})

        # Find all bindings for this program (a program can have multiple bindings)
        bindings = db.query(AccountProgramBinding).filter(
            AccountProgramBinding.program_id == program_id,
            AccountProgramBinding.is_deleted != True
        ).all()

        if not bindings:
            return json.dumps({"error": "No binding found for this program. Run a backtest first."})

        binding_ids = [b.id for b in bindings]

        # Get backtest history from all bindings
        backtests = db.query(BacktestResult).filter(
            BacktestResult.binding_id.in_(binding_ids),
            BacktestResult.status == "completed"
        ).order_by(BacktestResult.created_at.desc()).limit(limit).all()

        if not backtests:
            return json.dumps({"error": "No backtest results found. Run a backtest first."})

        results = []
        for bt in backtests:
            results.append({
                "id": bt.id,
                "time_range": f"{bt.start_time.strftime('%Y-%m-%d %H:%M') if bt.start_time else 'N/A'} ~ {bt.end_time.strftime('%Y-%m-%d %H:%M') if bt.end_time else 'N/A'}",
                "initial_balance": bt.initial_balance,
                "final_equity": round(bt.final_equity, 2) if bt.final_equity else 0,
                "total_pnl": round(bt.total_pnl, 2) if bt.total_pnl else 0,
                "total_pnl_percent": round(bt.total_pnl_percent, 2) if bt.total_pnl_percent else 0,
                "max_drawdown_percent": round(bt.max_drawdown_percent, 2) if bt.max_drawdown_percent else 0,
                "total_triggers": bt.total_triggers,
                "total_trades": bt.total_trades,  # Closed trades count
                "winning_trades": bt.winning_trades,  # TP count
                "losing_trades": bt.losing_trades,  # SL count
                "win_rate": round(bt.win_rate, 2) if bt.win_rate else 0,  # Already 0-100 scale
                "profit_factor": round(bt.profit_factor, 2) if bt.profit_factor else 0,
                "created_at": bt.created_at.strftime('%Y-%m-%d %H:%M') if bt.created_at else None
            })

        return json.dumps({
            "note": "Use these official stats directly. Do NOT recalculate from trigger list.",
            "backtests": results
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})

def _get_trigger_list(db: Session, backtest_id: int) -> str:
    """Get trigger summary list for a backtest."""
    try:
        triggers = db.query(BacktestTriggerLog).filter(
            BacktestTriggerLog.backtest_id == backtest_id
        ).order_by(BacktestTriggerLog.trigger_index).all()

        if not triggers:
            return json.dumps({"error": f"No triggers found for backtest {backtest_id}"})

        results = []
        for t in triggers:
            pnl = t.realized_pnl or 0
            results.append({
                "index": t.trigger_index,
                "time": t.trigger_time.strftime('%Y-%m-%d %H:%M:%S') if t.trigger_time else None,
                "type": t.trigger_type,
                "symbol": t.symbol,
                "action": t.decision_action,
                "side": t.decision_side,
                "size": round(t.decision_size, 4) if t.decision_size else None,
                "equity": f"${t.equity_before:.2f} -> ${t.equity_after:.2f}" if t.equity_before and t.equity_after else None,
                "pnl": round(pnl, 2) if pnl != 0 else None,
                "reason": t.decision_reason[:80] if t.decision_reason else None
            })

        return json.dumps({"total": len(results), "triggers": results}, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})

def _get_trigger_details(db: Session, backtest_id: int, indexes: List[int], fields: List[str] = None) -> str:
    """Get detailed info for specific triggers."""
    try:
        if not indexes:
            return json.dumps({"error": "indexes is required"})

        # Default to all fields
        if not fields:
            fields = ["summary", "input", "output", "queries", "logs"]

        triggers = db.query(BacktestTriggerLog).filter(
            BacktestTriggerLog.backtest_id == backtest_id,
            BacktestTriggerLog.trigger_index.in_(indexes)
        ).order_by(BacktestTriggerLog.trigger_index).all()

        if not triggers:
            return json.dumps({"error": f"No triggers found for indexes {indexes}"})

        results = []
        for t in triggers:
            detail = {"index": t.trigger_index}

            if "summary" in fields:
                detail["summary"] = {
                    "time": t.trigger_time.strftime('%Y-%m-%d %H:%M:%S') if t.trigger_time else None,
                    "type": t.trigger_type,
                    "symbol": t.symbol,
                    "action": t.decision_action,
                    "side": t.decision_side,
                    "size": t.decision_size,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "equity_before": t.equity_before,
                    "equity_after": t.equity_after,
                    "unrealized_pnl": t.unrealized_pnl,
                    "realized_pnl": t.realized_pnl,
                    "fee": t.fee,
                    "reason": t.decision_reason
                }

            if "input" in fields and t.decision_input:
                try:
                    detail["input"] = json.loads(t.decision_input)
                except:
                    detail["input"] = t.decision_input

            if "output" in fields and t.decision_output:
                try:
                    detail["output"] = json.loads(t.decision_output)
                except:
                    detail["output"] = t.decision_output

            if "queries" in fields and t.data_queries:
                try:
                    detail["queries"] = json.loads(t.data_queries)
                except:
                    detail["queries"] = t.data_queries

            if "logs" in fields and t.execution_logs:
                try:
                    detail["logs"] = json.loads(t.execution_logs)
                except:
                    detail["logs"] = t.execution_logs

            results.append(detail)

        return json.dumps({"triggers": results}, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})
