"""Hyperliquid agent-wallet API routes."""

from datetime import datetime, timezone
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.connection import get_db
from services.hyperliquid_trading_client import clear_trading_client_cache

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================================
# Agent Wallet Endpoints
# ============================================================================

class AgentWalletUpgradeRequest(BaseModel):
    """Request to upgrade existing wallet from private_key to agent_key"""
    environment: str = Field(..., pattern="^(testnet|mainnet)$")
    agent_name: str = Field("HyperArena", max_length=50, alias="agentName")

    class Config:
        populate_by_name = True


class AgentWalletConfigRequest(BaseModel):
    """Request to bind a new agent wallet (from Hyperliquid API page)"""
    agent_private_key: str = Field(..., min_length=64, max_length=66, alias="agentPrivateKey")
    master_wallet_address: str = Field(..., min_length=42, max_length=42, alias="masterWalletAddress")
    environment: str = Field(..., pattern="^(testnet|mainnet)$")
    max_leverage: int = Field(3, ge=1, le=50, alias="maxLeverage")
    default_leverage: int = Field(1, ge=1, le=50, alias="defaultLeverage")

    class Config:
        populate_by_name = True


def _get_extra_agents(api_url: str, wallet_address: str) -> list:
    """Query Hyperliquid extraAgents API for a wallet address"""
    import requests
    try:
        resp = requests.post(
            f"{api_url}/info",
            json={"type": "extraAgents", "user": wallet_address},
            timeout=10
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"Failed to query extraAgents for {wallet_address}: {e}")
        return []


def _find_agent_in_extra_agents(extra_agents: list, agent_address: str) -> Optional[dict]:
    """Find a specific agent in the extraAgents response"""
    agent_address_lower = agent_address.lower()
    for agent in extra_agents:
        if isinstance(agent, dict):
            addr = agent.get("address", "").lower()
            if addr == agent_address_lower:
                return agent
    return None


@router.post("/accounts/{account_id}/wallet/upgrade-to-agent")
def upgrade_wallet_to_agent(
    account_id: int,
    request: AgentWalletUpgradeRequest,
    db: Session = Depends(get_db)
):
    """
    Upgrade an existing private_key wallet to agent_key mode.

    Uses the stored master private key to call approve_agent on-chain,
    then replaces the stored key with the agent key.
    """
    from database.models import HyperliquidWallet, Account
    from utils.encryption import encrypt_private_key, decrypt_private_key
    from eth_account import Account as EthAccount

    try:
        account = db.query(Account).filter(Account.id == account_id, Account.is_deleted != True).first()
        if not account:
            raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

        wallet = db.query(HyperliquidWallet).filter(
            HyperliquidWallet.account_id == account_id,
            HyperliquidWallet.environment == request.environment,
        ).first()
        if not wallet:
            raise HTTPException(status_code=404, detail=f"No {request.environment} wallet found")

        key_type = getattr(wallet, 'key_type', 'private_key') or 'private_key'
        if key_type == "agent_key":
            raise HTTPException(status_code=400, detail="Wallet is already using agent key mode")

        # Decrypt master private key
        master_private_key = decrypt_private_key(wallet.private_key_encrypted)
        master_address = wallet.wallet_address

        # Create SDK Exchange with master key
        api_url = "https://api.hyperliquid-testnet.xyz" if request.environment == "testnet" else "https://api.hyperliquid.xyz"

        from hyperliquid.exchange import Exchange
        eth_wallet = EthAccount.from_key(master_private_key)
        # Pass empty metadata to avoid SDK spot token parsing error on testnet
        # approve_agent doesn't need coin mappings
        sdk_exchange = Exchange(
            wallet=eth_wallet,
            base_url=api_url,
            meta={"universe": []},
            spot_meta={"tokens": [], "universe": []},
        )

        # Approve agent on-chain
        agent_name = request.agent_name or f"HyperArena-{account_id}"
        result = sdk_exchange.approve_agent(name=agent_name)

        if not result or len(result) < 2:
            raise HTTPException(status_code=500, detail=f"approve_agent failed: {result}")

        approve_result, agent_private_key = result
        if isinstance(approve_result, dict) and approve_result.get("status") == "err":
            raise HTTPException(status_code=500, detail=f"approve_agent error: {approve_result}")

        # Derive agent address
        agent_eth_account = EthAccount.from_key(agent_private_key)
        agent_address = agent_eth_account.address.lower()

        # Query validUntil
        extra_agents = _get_extra_agents(api_url, master_address)
        agent_info = _find_agent_in_extra_agents(extra_agents, agent_address)
        valid_until = None
        if agent_info and "validUntil" in agent_info:
            valid_until_ms = agent_info["validUntil"]
            valid_until = datetime.fromtimestamp(valid_until_ms / 1000, tz=timezone.utc)

        # Update wallet record
        wallet.private_key_encrypted = encrypt_private_key(agent_private_key)
        wallet.wallet_address = agent_address
        wallet.key_type = "agent_key"
        wallet.master_wallet_address = master_address
        wallet.agent_valid_until = valid_until

        db.commit()

        # Clear trading client cache
        clear_trading_client_cache(account_id=account_id, environment=request.environment)

        return {
            "success": True,
            "message": f"Wallet upgraded to agent key mode",
            "agentAddress": agent_address,
            "masterWalletAddress": master_address,
            "agentName": agent_name,
            "validUntil": valid_until.isoformat() if valid_until else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upgrade wallet to agent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Agent upgrade failed: {str(e)}")


@router.post("/accounts/{account_id}/wallet/agent")
def configure_agent_wallet(
    account_id: int,
    request: AgentWalletConfigRequest,
    db: Session = Depends(get_db)
):
    """
    Bind an agent wallet created via Hyperliquid API page.

    The user creates the agent wallet on Hyperliquid's website and provides
    the agent private key + master wallet address here.
    """
    from database.models import HyperliquidWallet, Account
    from utils.encryption import encrypt_private_key
    from eth_account import Account as EthAccount

    try:
        account = db.query(Account).filter(Account.id == account_id, Account.is_deleted != True).first()
        if not account:
            raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

        # Validate and normalize agent private key
        agent_key = request.agent_private_key.strip()
        if not agent_key.startswith('0x'):
            agent_key = '0x' + agent_key

        # Derive agent address
        try:
            agent_eth_account = EthAccount.from_key(agent_key)
            agent_address = agent_eth_account.address.lower()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid agent private key: {e}")

        # Validate master wallet address format
        master_address = request.master_wallet_address.strip().lower()
        if not master_address.startswith('0x') or len(master_address) != 42:
            raise HTTPException(status_code=400, detail="Invalid master wallet address format")

        # Verify agent is authorized by querying extraAgents
        api_url = "https://api.hyperliquid-testnet.xyz" if request.environment == "testnet" else "https://api.hyperliquid.xyz"
        extra_agents = _get_extra_agents(api_url, master_address)
        agent_info = _find_agent_in_extra_agents(extra_agents, agent_address)

        valid_until = None
        if agent_info and "validUntil" in agent_info:
            valid_until_ms = agent_info["validUntil"]
            valid_until = datetime.fromtimestamp(valid_until_ms / 1000, tz=timezone.utc)

        if not agent_info:
            logger.warning(f"Agent {agent_address} not found in extraAgents for {master_address}. Proceeding anyway.")

        # Encrypt agent private key
        encrypted_key = encrypt_private_key(agent_key)

        # Create or update wallet record
        existing_wallet = db.query(HyperliquidWallet).filter(
            HyperliquidWallet.account_id == account_id,
            HyperliquidWallet.environment == request.environment,
        ).first()

        if existing_wallet:
            existing_wallet.private_key_encrypted = encrypted_key
            existing_wallet.wallet_address = agent_address
            existing_wallet.key_type = "agent_key"
            existing_wallet.master_wallet_address = master_address
            existing_wallet.agent_valid_until = valid_until
            existing_wallet.max_leverage = request.max_leverage
            existing_wallet.default_leverage = request.default_leverage
            existing_wallet.is_active = "true"
            wallet_id = existing_wallet.id
        else:
            new_wallet = HyperliquidWallet(
                account_id=account_id,
                environment=request.environment,
                private_key_encrypted=encrypted_key,
                wallet_address=agent_address,
                key_type="agent_key",
                master_wallet_address=master_address,
                agent_valid_until=valid_until,
                max_leverage=request.max_leverage,
                default_leverage=request.default_leverage,
                is_active="true"
            )
            db.add(new_wallet)
            db.flush()
            wallet_id = new_wallet.id

        db.commit()

        # Clear trading client cache
        clear_trading_client_cache(account_id=account_id, environment=request.environment)

        # Check builder fee authorization for mainnet (using master wallet address)
        builder_fee_authorized = True
        if request.environment == 'mainnet':
            try:
                from config.settings import HYPERLIQUID_BUILDER_CONFIG
                import requests as http_requests
                resp = http_requests.post(
                    "https://api.hyperliquid.xyz/info",
                    json={
                        "type": "maxBuilderFee",
                        "user": master_address,
                        "builder": HYPERLIQUID_BUILDER_CONFIG.builder_address
                    },
                    timeout=10
                )
                max_fee = resp.json()
                builder_fee_authorized = max_fee >= HYPERLIQUID_BUILDER_CONFIG.builder_fee
                print(f"[BUILDER_AUTH] Agent wallet bind: master={master_address[:12]}... maxBuilderFee={max_fee}, authorized={builder_fee_authorized}")
            except Exception as e:
                print(f"[BUILDER_AUTH] Failed to check builder fee for agent wallet: {e}")

        return {
            "success": True,
            "walletId": wallet_id,
            "agentAddress": agent_address,
            "masterWalletAddress": master_address,
            "validUntil": valid_until.isoformat() if valid_until else None,
            "message": f"Agent wallet configured for {request.environment}",
            "builderFeeAuthorized": builder_fee_authorized,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to configure agent wallet: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Agent wallet configuration failed: {str(e)}")


@router.get("/accounts/{account_id}/wallet/agent-status")
def get_agent_wallet_status(
    account_id: int,
    environment: str = Query(..., pattern="^(testnet|mainnet)$"),
    db: Session = Depends(get_db)
):
    """Get live agent wallet status including expiration info"""
    from database.models import HyperliquidWallet, Account

    try:
        account = db.query(Account).filter(Account.id == account_id, Account.is_deleted != True).first()
        if not account:
            raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

        wallet = db.query(HyperliquidWallet).filter(
            HyperliquidWallet.account_id == account_id,
            HyperliquidWallet.environment == environment,
        ).first()

        if not wallet:
            raise HTTPException(status_code=404, detail=f"No {environment} wallet found")

        key_type = getattr(wallet, 'key_type', 'private_key') or 'private_key'
        if key_type != "agent_key":
            return {
                "success": True,
                "keyType": "private_key",
                "message": "Wallet is using legacy private key mode"
            }

        master_address = wallet.master_wallet_address
        agent_address = wallet.wallet_address

        # Query live status from Hyperliquid
        api_url = "https://api.hyperliquid-testnet.xyz" if environment == "testnet" else "https://api.hyperliquid.xyz"
        extra_agents = _get_extra_agents(api_url, master_address)
        agent_info = _find_agent_in_extra_agents(extra_agents, agent_address)

        valid_until = None
        agent_name = None
        is_expired = True

        if agent_info:
            agent_name = agent_info.get("name")
            if "validUntil" in agent_info:
                valid_until_ms = agent_info["validUntil"]
                valid_until = datetime.fromtimestamp(valid_until_ms / 1000, tz=timezone.utc)
                is_expired = datetime.now(timezone.utc) > valid_until

        now = datetime.now(timezone.utc)
        days_remaining = (valid_until - now).days if valid_until and not is_expired else 0

        return {
            "success": True,
            "keyType": "agent_key",
            "agentAddress": agent_address,
            "masterWalletAddress": master_address,
            "agentName": agent_name,
            "validUntil": valid_until.isoformat() if valid_until else None,
            "isExpired": is_expired,
            "daysRemaining": max(0, days_remaining),
            "found": agent_info is not None,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get agent wallet status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get agent status: {str(e)}")


@router.get("/wallet-upgrade-check")
def check_wallet_upgrade_needed(db: Session = Depends(get_db)):
    """
    Check which wallets still use legacy private_key mode and should be upgraded.
    Returns list of wallets that need upgrade (for showing upgrade modal).
    """
    from database.models import HyperliquidWallet, Account

    try:
        wallets = db.query(HyperliquidWallet, Account).join(
            Account, HyperliquidWallet.account_id == Account.id
        ).filter(
            HyperliquidWallet.is_active == "true",
            Account.is_deleted != True,
        ).all()

        needs_upgrade = []
        for wallet, account in wallets:
            key_type = getattr(wallet, 'key_type', 'private_key') or 'private_key'
            if key_type == "private_key":
                needs_upgrade.append({
                    "accountId": account.id,
                    "accountName": account.name,
                    "environment": wallet.environment,
                    "walletAddress": wallet.wallet_address,
                })

        return {
            "success": True,
            "needsUpgrade": needs_upgrade,
            "count": len(needs_upgrade),
        }

    except Exception as e:
        logger.error(f"Failed to check wallet upgrade: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to check wallet upgrade: {str(e)}")
