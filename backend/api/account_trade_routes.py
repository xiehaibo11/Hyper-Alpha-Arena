"""Account AI trade trigger API routes."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import Account, Position, Trade

logger = logging.getLogger(__name__)
router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/{account_id}/trigger-ai-trade")
def trigger_ai_trade(
    account_id: int,
    force_operation: str = None,  # Optional: "buy", "sell", "close", "hold"
    symbol: str = None,  # Optional: specific symbol to trade
    db: Session = Depends(get_db)
):
    """
    Manually trigger AI trading for a specific account.

    Args:
        account_id: The account ID to trigger trading for
        force_operation: Optional operation to force ("buy", "sell", "close", "hold")
        symbol: Optional specific symbol to trade (default: auto-detect from sampling pool)

    Returns:
        Trade execution result
    """
    try:
        from services.trading_commands import place_ai_driven_crypto_order

        # Validate account exists and is active
        account = db.query(Account).filter(Account.id == account_id, Account.is_deleted != True).first()
        if not account:
            raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

        if account.is_active != "true":
            raise HTTPException(status_code=400, detail=f"Account {account.name} is inactive")

        if account.account_type != "AI":
            raise HTTPException(status_code=400, detail=f"Only AI accounts can trigger AI trading")

        logger.info(f"Manually triggering AI trade for account {account.name} (ID: {account_id})")
        if force_operation:
            logger.info(f"  Force operation: {force_operation}")
        if symbol:
            logger.info(f"  Target symbol: {symbol}")

        # If forcing a specific operation, we need to mock the AI decision
        samples = None
        if force_operation:
            # Prepare mock samples to force specific operation
            if force_operation.lower() == "close":
                # For CLOSE operation, we need to find a position to close
                positions = db.query(Position).filter(
                    Position.account_id == account_id,
                    Position.market == "CRYPTO",
                    Position.available_quantity > 0
                ).all()

                if not positions:
                    return {
                        "success": False,
                        "message": "No open positions to close",
                        "account_id": account_id,
                        "account_name": account.name
                    }

                # Use the first available position if symbol not specified
                if not symbol:
                    symbol = positions[0].symbol

                # Mock AI decision for CLOSE operation
                samples = [{
                    "operation": "close",
                    "symbol": symbol,
                    "target_portion_of_balance": 1.0,  # Close 100%
                    "reason": f"Manual CLOSE trigger via API for {account.name}"
                }]

            elif force_operation.lower() in ["buy", "sell"]:
                if not symbol:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Symbol is required when forcing {force_operation} operation"
                    )

                samples = [{
                    "operation": force_operation.lower(),
                    "symbol": symbol,
                    "target_portion_of_balance": 0.2,  # Default 20%
                    "reason": f"Manual {force_operation.upper()} trigger via API for {account.name}"
                }]

            elif force_operation.lower() == "hold":
                samples = [{
                    "operation": "hold",
                    "symbol": symbol or "BTC",
                    "target_portion_of_balance": 0,
                    "reason": f"Manual HOLD trigger via API for {account.name}"
                }]

        # Check if account has Hyperliquid environment configured
        hyperliquid_environment = getattr(account, "hyperliquid_environment", None)

        print(
            f"[DEBUG] Trigger API: account_id={account_id} "
            f"hyperliquid_environment={hyperliquid_environment}"
        )

        # Trigger AI trading based on account configuration
        if hyperliquid_environment in ["testnet", "mainnet"]:
            print(f"[DEBUG] ENTERING HYPERLIQUID BRANCH")
            try:
                from services.trading_commands import place_ai_driven_hyperliquid_order
                print(f"[DEBUG] Successfully imported place_ai_driven_hyperliquid_order")
                print(f"[DEBUG] Calling place_ai_driven_hyperliquid_order for account {account_id}")
                place_ai_driven_hyperliquid_order(
                    account_id=account_id,
                    bypass_auto_trading=True,
                )
                print(f"[DEBUG] place_ai_driven_hyperliquid_order completed for account {account_id}")
            except Exception as hyperliquid_err:
                print(f"[DEBUG] Error in Hyperliquid trading: {hyperliquid_err}")
                logger.error(f"Error in Hyperliquid trading for account {account_id}: {hyperliquid_err}", exc_info=True)
        else:
            place_ai_driven_crypto_order(
                max_ratio=0.2,
                account_id=account_id,
                symbol=symbol,
                samples=samples
            )

        # Check for new trades
        recent_trades = db.query(Trade).filter(
            Trade.account_id == account_id
        ).order_by(Trade.trade_time.desc()).limit(1).all()

        if recent_trades:
            latest_trade = recent_trades[0]
            return {
                "success": True,
                "message": f"AI trading triggered successfully for {account.name}",
                "account_id": account_id,
                "account_name": account.name,
                "trade": {
                    "id": latest_trade.id,
                    "symbol": latest_trade.symbol,
                    "side": latest_trade.side,
                    "quantity": float(latest_trade.quantity),
                    "price": float(latest_trade.price),
                    "trade_time": latest_trade.trade_time.isoformat() if latest_trade.trade_time else None
                }
            }
        else:
            return {
                "success": True,
                "message": f"AI trading triggered for {account.name}, but no trade was executed (AI may have decided to HOLD)",
                "account_id": account_id,
                "account_name": account.name
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to trigger AI trade for account {account_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to trigger AI trade: {str(e)}"
        )
