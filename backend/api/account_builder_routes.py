"""Account Hyperliquid authorization and account-control API routes."""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import Account, HyperliquidWallet

logger = logging.getLogger(__name__)
router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/hyperliquid/check-builder-authorization")
def check_builder_authorization(
    wallet_address: str,
    db: Session = Depends(get_db)
):
    """
    Check if a wallet address has authorized the platform's builder fee.

    Args:
        wallet_address: The Hyperliquid wallet address to check

    Returns:
        {
            "authorized": bool,  # True if authorized with sufficient fee
            "max_fee": int,      # Maximum fee approved (in tenths of basis point)
            "required_fee": int  # Required fee by platform (in tenths of basis point)
        }
    """
    try:
        import requests
        from config.settings import HYPERLIQUID_BUILDER_CONFIG

        # Query Hyperliquid API for max builder fee
        response = requests.post(
            "https://api.hyperliquid.xyz/info",
            json={
                "type": "maxBuilderFee",
                "user": wallet_address,
                "builder": HYPERLIQUID_BUILDER_CONFIG.builder_address
            },
            timeout=10
        )

        if response.status_code != 200:
            logger.error(f"Failed to check builder authorization: HTTP {response.status_code}")
            raise HTTPException(
                status_code=500,
                detail="Failed to query Hyperliquid authorization status"
            )

        max_fee = response.json()  # Returns integer (e.g., 30 for 0.03%)
        required_fee = HYPERLIQUID_BUILDER_CONFIG.builder_fee

        return {
            "authorized": max_fee >= required_fee,
            "max_fee": max_fee,
            "required_fee": required_fee,
            "builder_address": HYPERLIQUID_BUILDER_CONFIG.builder_address
        }

    except requests.exceptions.RequestException as e:
        logger.error(f"Network error checking builder authorization: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Network error: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error checking builder authorization: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to check authorization: {str(e)}"
        )


@router.post("/hyperliquid/approve-builder")
def approve_builder_fee(
    account_id: int,
    db: Session = Depends(get_db)
):
    """
    Trigger builder fee approval for a Hyperliquid account.

    This endpoint initiates the approval process where the user's wallet
    will be prompted to sign a transaction approving the platform's builder fee.

    Args:
        account_id: The account ID to approve builder fee for

    Returns:
        {
            "success": bool,
            "message": str,
            "builder_address": str,
            "approved_fee": str  # e.g., "0.03%"
        }
    """
    try:
        print(f"[BUILDER_AUTH] ========== Starting authorization for account_id={account_id} ==========")
        from config.settings import HYPERLIQUID_BUILDER_CONFIG
        from services.hyperliquid_environment import get_hyperliquid_client

        # Get account
        account = db.query(Account).filter(Account.id == account_id, Account.is_deleted != True).first()
        if not account:
            print(f"[BUILDER_AUTH] ERROR: Account {account_id} not found")
            raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

        # Check if account has mainnet wallet configured (new architecture first, then fallback)
        mainnet_wallet = db.query(HyperliquidWallet).filter(
            HyperliquidWallet.account_id == account_id,
            HyperliquidWallet.environment == "mainnet",
            HyperliquidWallet.private_key_encrypted.isnot(None)
        ).first()

        # Fallback to old architecture
        if not mainnet_wallet:
            mainnet_key = getattr(account, "hyperliquid_mainnet_private_key", None)
            if not mainnet_key:
                print(f"[BUILDER_AUTH] ERROR: Account {account_id} does not have a mainnet wallet configured")
                raise HTTPException(
                    status_code=400,
                    detail="Account does not have a mainnet wallet configured"
                )
            print(f"[BUILDER_AUTH] Using old architecture mainnet wallet for account {account_id}")
        else:
            print(f"[BUILDER_AUTH] Using new architecture mainnet wallet for account {account_id}, wallet_address={mainnet_wallet.wallet_address}")

        # Get Hyperliquid client with mainnet environment (regardless of current trading mode)
        client = get_hyperliquid_client(db, account_id, override_environment="mainnet")
        print(f"[BUILDER_AUTH] Got Hyperliquid client for account {account_id}")

        # Calculate fee percentage for display (e.g., 30 -> "0.03%")
        fee_bps = HYPERLIQUID_BUILDER_CONFIG.builder_fee / 10  # Convert to basis points
        fee_percentage = f"{fee_bps / 100}%"  # Convert to percentage string

        print(f"[BUILDER_AUTH] Calling approve_builder_fee: builder={HYPERLIQUID_BUILDER_CONFIG.builder_address}, fee={fee_percentage}")

        # Call approve_builder_fee on the exchange
        # This will trigger wallet signature request
        result = client.sdk_exchange.approve_builder_fee(
            HYPERLIQUID_BUILDER_CONFIG.builder_address,
            fee_percentage
        )

        # Check if authorization was successful based on Hyperliquid response
        is_success = not (isinstance(result, dict) and result.get('status') == 'err')

        if is_success:
            print(f"[BUILDER_AUTH] SUCCESS for account {account_id}: result={result}")
        else:
            print(f"[BUILDER_AUTH] FAILED for account {account_id}: result={result}")

        logger.info(
            f"Builder fee approval initiated for account {account_id}: "
            f"builder={HYPERLIQUID_BUILDER_CONFIG.builder_address}, "
            f"fee={fee_percentage}, result={result}"
        )

        return {
            "success": is_success,
            "message": result.get('response', 'Authorization failed') if not is_success else "Builder fee authorized successfully",
            "builder_address": HYPERLIQUID_BUILDER_CONFIG.builder_address,
            "approved_fee": fee_percentage,
            "result": result
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[BUILDER_AUTH] EXCEPTION for account {account_id}: {type(e).__name__}: {e}")
        logger.error(f"Failed to approve builder fee for account {account_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to approve builder fee: {str(e)}"
        )


@router.get("/hyperliquid/check-mainnet-accounts")
def check_mainnet_accounts(
    db: Session = Depends(get_db)
):
    """
    Check builder fee authorization for all active mainnet trading accounts.

    This endpoint is called on system startup to identify accounts that have:
    - auto_trading_enabled = true
    - hyperliquid_mainnet_private_key configured
    - but builder fee NOT authorized

    Returns:
        {
            "unauthorized_accounts": [
                {
                    "account_id": int,
                    "account_name": str,
                    "wallet_address": str,
                    "max_fee": int,  # Current authorized fee in tenths of basis point
                    "required_fee": int  # Required fee (30 for 0.03%)
                }
            ]
        }
    """
    try:
        import requests
        from config.settings import HYPERLIQUID_BUILDER_CONFIG
        from eth_account import Account as EthAccount
        from services.hyperliquid_environment import decrypt_private_key

        unauthorized_accounts = []
        checked_account_ids = set()

        # === Check new multi-wallet architecture (hyperliquid_wallets table) ===
        # Query accounts with mainnet wallet in hyperliquid_wallets table and trading enabled
        mainnet_wallets = db.query(HyperliquidWallet, Account).join(
            Account, HyperliquidWallet.account_id == Account.id
        ).filter(
            HyperliquidWallet.environment == "mainnet",
            HyperliquidWallet.private_key_encrypted.isnot(None),
            Account.auto_trading_enabled == "true"
        ).all()

        logger.info(f"Found {len(mainnet_wallets)} accounts with mainnet wallet in wallets table")

        for wallet, account in mainnet_wallets:
            checked_account_ids.add(account.id)
            try:
                # For agent_key wallets, check builder fee against master wallet address
                # (builder fee authorization is tied to the master wallet, not the agent)
                if wallet.key_type == "agent_key" and wallet.master_wallet_address:
                    wallet_address = wallet.master_wallet_address.lower()
                else:
                    decrypted_key = decrypt_private_key(wallet.private_key_encrypted)
                    if not decrypted_key:
                        logger.warning(f"Failed to decrypt mainnet key for account {account.id} from wallets table")
                        continue
                    if not decrypted_key.startswith('0x'):
                        decrypted_key = '0x' + decrypted_key
                    eth_account = EthAccount.from_key(decrypted_key)
                    wallet_address = eth_account.address.lower()

                response = requests.post(
                    "https://api.hyperliquid.xyz/info",
                    json={
                        "type": "maxBuilderFee",
                        "user": wallet_address,
                        "builder": HYPERLIQUID_BUILDER_CONFIG.builder_address
                    },
                    timeout=10
                )

                if response.status_code == 200:
                    max_fee = response.json()
                    required_fee = HYPERLIQUID_BUILDER_CONFIG.builder_fee

                    if max_fee < required_fee:
                        unauthorized_accounts.append({
                            "account_id": account.id,
                            "account_name": account.name,
                            "wallet_address": wallet_address,
                            "max_fee": max_fee,
                            "required_fee": required_fee
                        })
                        logger.info(
                            f"Account {account.id} ({account.name}) unauthorized: "
                            f"max_fee={max_fee}, required={required_fee}"
                        )
                else:
                    logger.error(
                        f"Failed to check authorization for account {account.id}: "
                        f"HTTP {response.status_code}"
                    )
            except Exception as account_err:
                logger.error(
                    f"Error checking account {account.id} from wallets table: {account_err}",
                    exc_info=True
                )
                continue

        # === Fallback: Check old architecture (accounts table field) ===
        # Query accounts with mainnet key in accounts table (not already checked)
        old_accounts = db.query(Account).filter(
            Account.auto_trading_enabled == "true",
            Account.hyperliquid_mainnet_private_key.isnot(None),
            Account.hyperliquid_mainnet_private_key != "",
            Account.is_deleted != True
        ).all()

        # Filter out accounts already checked via wallets table
        old_accounts = [a for a in old_accounts if a.id not in checked_account_ids]

        logger.info(f"Found {len(old_accounts)} additional accounts with mainnet key in accounts table")

        for account in old_accounts:
            try:
                decrypted_key = decrypt_private_key(account.hyperliquid_mainnet_private_key)
                if not decrypted_key:
                    logger.warning(f"Failed to decrypt mainnet key for account {account.id}")
                    continue

                if not decrypted_key.startswith('0x'):
                    decrypted_key = '0x' + decrypted_key

                eth_account = EthAccount.from_key(decrypted_key)
                wallet_address = eth_account.address.lower()

                response = requests.post(
                    "https://api.hyperliquid.xyz/info",
                    json={
                        "type": "maxBuilderFee",
                        "user": wallet_address,
                        "builder": HYPERLIQUID_BUILDER_CONFIG.builder_address
                    },
                    timeout=10
                )

                if response.status_code == 200:
                    max_fee = response.json()
                    required_fee = HYPERLIQUID_BUILDER_CONFIG.builder_fee

                    if max_fee < required_fee:
                        unauthorized_accounts.append({
                            "account_id": account.id,
                            "account_name": account.name,
                            "wallet_address": wallet_address,
                            "max_fee": max_fee,
                            "required_fee": required_fee
                        })
                        logger.info(
                            f"Account {account.id} ({account.name}) unauthorized: "
                            f"max_fee={max_fee}, required={required_fee}"
                        )
                else:
                    logger.error(
                        f"Failed to check authorization for account {account.id}: "
                        f"HTTP {response.status_code}"
                    )
            except Exception as account_err:
                logger.error(
                    f"Error checking account {account.id}: {account_err}",
                    exc_info=True
                )
                continue

        total_checked = len(mainnet_wallets) + len(old_accounts)
        logger.info(
            f"Builder fee check complete: {len(unauthorized_accounts)} "
            f"unauthorized out of {total_checked} total"
        )

        return {
            "unauthorized_accounts": unauthorized_accounts
        }

    except Exception as e:
        logger.error(f"Failed to check mainnet accounts: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to check mainnet accounts: {str(e)}"
        )


@router.post("/{account_id}/disable-trading")
def disable_trading(
    account_id: int,
    db: Session = Depends(get_db)
):
    """
    Disable auto trading for an account.

    This endpoint is called when a user refuses to authorize builder fee,
    ensuring that the account cannot place orders without proper authorization.

    Args:
        account_id: The account ID to disable trading for

    Returns:
        {
            "success": bool,
            "message": str,
            "account_id": int,
            "account_name": str
        }
    """
    try:
        # Get account
        account = db.query(Account).filter(Account.id == account_id, Account.is_deleted != True).first()
        if not account:
            raise HTTPException(
                status_code=404,
                detail=f"Account {account_id} not found"
            )

        # Disable auto trading
        account.auto_trading_enabled = "false"
        db.commit()

        logger.info(
            f"Auto trading disabled for account {account_id} ({account.name}) "
            f"due to builder fee authorization refusal"
        )

        return {
            "success": True,
            "message": f"Auto trading disabled for {account.name}",
            "account_id": account_id,
            "account_name": account.name
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to disable trading for account {account_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to disable trading: {str(e)}"
        )


@router.patch("/dashboard-visibility")
def update_dashboard_visibility(
    visibility_updates: List[dict],
    db: Session = Depends(get_db)
):
    """
    Batch update show_on_dashboard for multiple accounts.

    Request body: [{"account_id": 1, "show_on_dashboard": true}, ...]

    Returns:
        {"success": bool, "updated_count": int, "updates": [...]}
    """
    try:
        updated = []
        for item in visibility_updates:
            account_id = item.get("account_id")
            show = item.get("show_on_dashboard", True)

            account = db.query(Account).filter(Account.id == account_id, Account.is_deleted != True).first()
            if account:
                account.show_on_dashboard = show
                updated.append({"account_id": account_id, "show_on_dashboard": show})

        db.commit()

        logger.info(f"Updated dashboard visibility for {len(updated)} accounts")
        return {
            "success": True,
            "updated_count": len(updated),
            "updates": updated
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update dashboard visibility: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update dashboard visibility: {str(e)}"
        )
