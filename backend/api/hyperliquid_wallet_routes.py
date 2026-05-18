"""Hyperliquid wallet configuration API routes."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.hyperliquid_agent_wallet_routes import router as hyperliquid_agent_wallet_router
from api.hyperliquid_wallet_admin_routes import router as hyperliquid_wallet_admin_router
from database.connection import get_db
from services.hyperliquid_environment import get_hyperliquid_client
from services.hyperliquid_trading_client import clear_trading_client_cache

logger = logging.getLogger(__name__)
router = APIRouter()
router.include_router(hyperliquid_wallet_admin_router)
router.include_router(hyperliquid_agent_wallet_router)


# ========== Wallet Management API (New Multi-Wallet Architecture) ==========

class WalletConfigRequest(BaseModel):
    """Request model for wallet configuration"""
    private_key: str = Field(..., min_length=64, max_length=66, description="Hyperliquid private key (0x...)", alias="privateKey")
    max_leverage: int = Field(3, ge=1, le=50, description="Maximum allowed leverage", alias="maxLeverage")
    default_leverage: int = Field(1, ge=1, le=50, description="Default leverage", alias="defaultLeverage")
    environment: str = Field("testnet", description="Trading environment: testnet or mainnet")

    class Config:
        populate_by_name = True


class WalletConfigResponse(BaseModel):
    """Response model for wallet configuration"""
    success: bool
    wallet_id: Optional[int] = Field(None, alias="walletId")
    wallet_address: Optional[str] = Field(None, alias="walletAddress")
    message: str
    requires_authorization: Optional[bool] = False

    class Config:
        populate_by_name = True


@router.get("/accounts/{account_id}/wallet")
def get_account_wallet(
    account_id: int,
    db: Session = Depends(get_db)
):
    """
    Get wallet configurations for an AI Trader account (both testnet and mainnet)

    Returns both testnet and mainnet wallet configurations with balance information.
    """
    from database.models import HyperliquidWallet, Account
    from services.hyperliquid_environment import get_global_trading_mode

    try:
        # Check if account exists
        account = db.query(Account).filter(Account.id == account_id, Account.is_deleted != True).first()
        if not account:
            raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

        # Get all wallets for this account (testnet and mainnet)
        wallets = db.query(HyperliquidWallet).filter(
            HyperliquidWallet.account_id == account_id
        ).all()

        # Organize wallets by environment
        testnet_wallet = None
        mainnet_wallet = None

        for wallet in wallets:
            wallet_data = {
                'id': wallet.id,
                'walletAddress': wallet.wallet_address,
                'maxLeverage': wallet.max_leverage,
                'defaultLeverage': wallet.default_leverage,
                'isActive': wallet.is_active == "true",
                'createdAt': wallet.created_at.isoformat() if wallet.created_at else None,
                'updatedAt': wallet.updated_at.isoformat() if wallet.updated_at else None,
                'environment': wallet.environment,
                'keyType': getattr(wallet, 'key_type', 'private_key') or 'private_key',
                'masterWalletAddress': getattr(wallet, 'master_wallet_address', None),
                'agentValidUntil': wallet.agent_valid_until.isoformat() if getattr(wallet, 'agent_valid_until', None) else None,
            }

            # Try to get balance for this specific wallet
            try:
                # Use override_environment to get client for this wallet's environment
                client = get_hyperliquid_client(db, account_id, override_environment=wallet.environment)
                account_state = client.get_account_state(db)
                wallet_data['balance'] = {
                    'totalEquity': float(account_state.get('total_equity', 0)),
                    'availableBalance': float(account_state.get('available_balance', 0)),
                    'marginUsagePercent': float(account_state.get('margin_usage_percent', 0))
                }
            except Exception as e:
                logger.warning(f"Failed to fetch balance for {wallet.environment} wallet: {e}")
                wallet_data['balance'] = None

            if wallet.environment == 'testnet':
                testnet_wallet = wallet_data
            elif wallet.environment == 'mainnet':
                mainnet_wallet = wallet_data

        # Get global trading mode
        trading_mode = get_global_trading_mode(db)

        return {
            'success': True,
            'configured': testnet_wallet is not None or mainnet_wallet is not None,
            'accountId': account_id,
            'accountName': account.name,
            'testnetWallet': testnet_wallet,
            'mainnetWallet': mainnet_wallet,
            'globalTradingMode': trading_mode
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get wallets for account {account_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get wallet configuration: {str(e)}")


@router.post("/accounts/{account_id}/wallet")
def configure_account_wallet(
    account_id: int,
    request: WalletConfigRequest,
    db: Session = Depends(get_db)
):
    """
    Configure or update wallet for an AI Trader account

    Creates a new wallet record or updates existing one for the specified environment.
    The private key will be encrypted before storage.
    """
    from database.models import HyperliquidWallet, Account
    from utils.encryption import encrypt_private_key
    from eth_account import Account as EthAccount

    try:
        # Validate environment
        if request.environment not in ['testnet', 'mainnet']:
            raise HTTPException(status_code=400, detail="Environment must be 'testnet' or 'mainnet'")

        # Check if account exists
        account = db.query(Account).filter(Account.id == account_id, Account.is_deleted != True).first()
        if not account:
            raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

        # Validate and parse private key
        private_key = request.private_key.strip()
        if private_key.startswith('0x'):
            private_key = private_key[2:]

        if len(private_key) != 64:
            raise HTTPException(
                status_code=400,
                detail="Invalid private key format. Must be 64 hex characters (with or without 0x prefix)"
            )

        # Parse wallet address from private key
        try:
            eth_account = EthAccount.from_key('0x' + private_key)
            wallet_address = eth_account.address
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid private key: {str(e)}")

        # Encrypt private key
        try:
            encrypted_key = encrypt_private_key('0x' + private_key)
        except Exception as e:
            logger.error(f"Failed to encrypt private key: {e}")
            raise HTTPException(status_code=500, detail="Failed to encrypt private key")

        # Check if wallet already exists for this account and environment
        existing_wallet = db.query(HyperliquidWallet).filter(
            HyperliquidWallet.account_id == account_id,
            HyperliquidWallet.environment == request.environment
        ).first()

        if existing_wallet:
            # Update existing wallet
            existing_wallet.private_key_encrypted = encrypted_key
            existing_wallet.wallet_address = wallet_address
            existing_wallet.max_leverage = request.max_leverage
            existing_wallet.default_leverage = request.default_leverage
            existing_wallet.is_active = "true"

            db.commit()
            db.refresh(existing_wallet)

            # Clear cached trading client since credentials changed
            clear_trading_client_cache(account_id=account_id, environment=request.environment)

            logger.info(f"Updated {request.environment} wallet for account {account.name} (ID: {account_id}), address: {wallet_address}")

            # Builder binding for mainnet wallet after successful save
            requires_auth = False
            if request.environment == 'mainnet':
                try:
                    print(f"[BUILDER_AUTH] Checking authorization after wallet save for account {account_id}, wallet={wallet_address}")
                    from config.settings import HYPERLIQUID_BUILDER_CONFIG
                    import requests

                    # Check authorization status
                    response = requests.post(
                        "https://api.hyperliquid.xyz/info",
                        json={
                            "type": "maxBuilderFee",
                            "user": wallet_address,
                            "builder": HYPERLIQUID_BUILDER_CONFIG.builder_address
                        },
                        timeout=10
                    )
                    max_fee = response.json()

                    if max_fee < HYPERLIQUID_BUILDER_CONFIG.builder_fee:
                        print(f"[BUILDER_AUTH] Not authorized (max_fee={max_fee} < required={HYPERLIQUID_BUILDER_CONFIG.builder_fee}), triggering authorization")

                        # Execute authorization
                        client = get_hyperliquid_client(db, account_id, override_environment="mainnet")
                        fee_percentage = f"{HYPERLIQUID_BUILDER_CONFIG.builder_fee / 10 / 100}%"
                        result = client.sdk_exchange.approve_builder_fee(
                            HYPERLIQUID_BUILDER_CONFIG.builder_address,
                            fee_percentage
                        )

                        # Check if authorization failed
                        is_success = not (isinstance(result, dict) and result.get('status') == 'err')
                        if is_success:
                            print(f"[BUILDER_AUTH] Authorization completed for account {account_id}: {result}")
                        else:
                            print(f"[BUILDER_AUTH] Authorization FAILED for account {account_id}: {result}")
                            requires_auth = True
                    else:
                        print(f"[BUILDER_AUTH] Already authorized for account {account_id} (max_fee={max_fee})")
                except Exception as e:
                    print(f"[BUILDER_AUTH] Authorization failed for account {account_id}: {type(e).__name__}: {e}")
                    requires_auth = True

            return WalletConfigResponse(
                success=True,
                wallet_id=existing_wallet.id,
                wallet_address=wallet_address,
                message=f"{request.environment.capitalize()} wallet updated for {account.name}",
                requires_authorization=requires_auth
            )
        else:
            # Create new wallet
            new_wallet = HyperliquidWallet(
                account_id=account_id,
                environment=request.environment,
                private_key_encrypted=encrypted_key,
                wallet_address=wallet_address,
                max_leverage=request.max_leverage,
                default_leverage=request.default_leverage,
                is_active="true"
            )

            db.add(new_wallet)
            db.commit()
            db.refresh(new_wallet)

            # Clear cached trading client (in case there was an old cached client)
            clear_trading_client_cache(account_id=account_id, environment=request.environment)

            logger.info(f"Created {request.environment} wallet for account {account.name} (ID: {account_id}), address: {wallet_address}")

            # Builder binding for mainnet wallet after successful save
            requires_auth = False
            if request.environment == 'mainnet':
                try:
                    print(f"[BUILDER_AUTH] Checking authorization after wallet save for account {account_id}, wallet={wallet_address}")
                    from config.settings import HYPERLIQUID_BUILDER_CONFIG
                    import requests

                    # Check authorization status
                    response = requests.post(
                        "https://api.hyperliquid.xyz/info",
                        json={
                            "type": "maxBuilderFee",
                            "user": wallet_address,
                            "builder": HYPERLIQUID_BUILDER_CONFIG.builder_address
                        },
                        timeout=10
                    )
                    max_fee = response.json()

                    if max_fee < HYPERLIQUID_BUILDER_CONFIG.builder_fee:
                        print(f"[BUILDER_AUTH] Not authorized (max_fee={max_fee} < required={HYPERLIQUID_BUILDER_CONFIG.builder_fee}), triggering authorization")

                        # Execute authorization
                        client = get_hyperliquid_client(db, account_id, override_environment="mainnet")
                        fee_percentage = f"{HYPERLIQUID_BUILDER_CONFIG.builder_fee / 10 / 100}%"
                        result = client.sdk_exchange.approve_builder_fee(
                            HYPERLIQUID_BUILDER_CONFIG.builder_address,
                            fee_percentage
                        )

                        # Check if authorization failed
                        is_success = not (isinstance(result, dict) and result.get('status') == 'err')
                        if is_success:
                            print(f"[BUILDER_AUTH] Authorization completed for account {account_id}: {result}")
                        else:
                            print(f"[BUILDER_AUTH] Authorization FAILED for account {account_id}: {result}")
                            requires_auth = True
                    else:
                        print(f"[BUILDER_AUTH] Already authorized for account {account_id} (max_fee={max_fee})")
                except Exception as e:
                    print(f"[BUILDER_AUTH] Authorization failed for account {account_id}: {type(e).__name__}: {e}")
                    requires_auth = True

            return WalletConfigResponse(
                success=True,
                wallet_id=new_wallet.id,
                wallet_address=wallet_address,
                message=f"{request.environment.capitalize()} wallet configured for {account.name}",
                requires_authorization=requires_auth
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to configure wallet for account {account_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to configure wallet: {str(e)}")


@router.delete("/accounts/{account_id}/wallet")
def delete_account_wallet(
    account_id: int,
    environment: str = Query(..., pattern="^(testnet|mainnet)$", description="Environment to delete (testnet or mainnet)"),
    db: Session = Depends(get_db)
):
    """
    Delete wallet configuration for a specific environment

    Deletes the testnet or mainnet wallet for an AI Trader account.
    The other wallet (if exists) will remain configured.

    Query Parameters:
    - environment: Which wallet to delete ('testnet' or 'mainnet')
    """
    from database.models import HyperliquidWallet, Account

    try:
        # Check if account exists
        account = db.query(Account).filter(Account.id == account_id, Account.is_deleted != True).first()
        if not account:
            raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

        # Find wallet for specified environment
        wallet = db.query(HyperliquidWallet).filter(
            HyperliquidWallet.account_id == account_id,
            HyperliquidWallet.environment == environment
        ).first()

        if not wallet:
            raise HTTPException(
                status_code=404,
                detail=f"No {environment} wallet configured for account {account_id}"
            )

        # Delete wallet
        wallet_address = wallet.wallet_address
        db.delete(wallet)
        db.commit()

        logger.warning(
            f"Deleted {environment} wallet ({wallet_address}) for account {account.name} (ID: {account_id})"
        )

        return {
            'success': True,
            'accountId': account_id,
            'accountName': account.name,
            'environment': environment,
            'message': f'{environment.capitalize()} wallet deleted'
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete {environment} wallet for account {account_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete wallet: {str(e)}")


class TestWalletRequest(BaseModel):
    environment: Optional[str] = None


@router.post("/accounts/{account_id}/wallet/test")
def test_wallet_connection(
    account_id: int,
    body: TestWalletRequest = TestWalletRequest(),
    db: Session = Depends(get_db)
):
    """
    Test wallet connection to Hyperliquid

    Validates that the wallet can connect to the exchange and fetch account state.
    Uses the provided environment, or falls back to global trading_mode.
    """
    from database.models import Account

    try:
        account = db.query(Account).filter(Account.id == account_id, Account.is_deleted != True).first()
        if not account:
            raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

        env = body.environment
        if env and env not in ("testnet", "mainnet"):
            raise HTTPException(status_code=400, detail="environment must be 'testnet' or 'mainnet'")
        if not env:
            from services.hyperliquid_environment import get_global_trading_mode
            env = get_global_trading_mode(db)

        try:
            client = get_hyperliquid_client(db, account_id, override_environment=env)
            account_state = client.get_account_state(db)

            return {
                'success': True,
                'accountId': account_id,
                'accountName': account.name,
                'environment': env,
                'walletAddress': client.wallet_address,
                'connection': 'successful',
                'accountState': {
                    'totalEquity': float(account_state.get('total_equity', 0)),
                    'availableBalance': float(account_state.get('available_balance', 0)),
                    'marginUsage': float(account_state.get('margin_usage_percent', 0))
                }
            }

        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            return {
                'success': False,
                'accountId': account_id,
                'accountName': account.name,
                'environment': env,
                'connection': 'failed',
                'error': str(e)
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to test wallet connection for account {account_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to test connection: {str(e)}")
