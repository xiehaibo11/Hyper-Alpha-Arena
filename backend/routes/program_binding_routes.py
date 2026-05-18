"""Binding routes for AI Traders and trading programs."""

import json
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import Account, AccountProgramBinding, TradingProgram
from routes.program_helpers import _binding_to_response
from routes.program_schemas import BindingCreate, BindingUpdate, BindingResponse

router = APIRouter()

@router.get("/bindings/", response_model=List[BindingResponse])
def list_bindings(
    program_id: Optional[int] = Query(None),
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    """List program bindings, optionally filtered by program_id or account_id."""
    query = db.query(AccountProgramBinding).filter(
        AccountProgramBinding.is_deleted != True
    )

    if program_id:
        query = query.filter(AccountProgramBinding.program_id == program_id)
    if account_id:
        query = query.filter(AccountProgramBinding.account_id == account_id)

    bindings = query.order_by(AccountProgramBinding.created_at.desc()).all()
    return [_binding_to_response(b, db) for b in bindings]


@router.post("/bindings/", response_model=BindingResponse)
def create_binding(data: BindingCreate, account_id: int = Query(...), db: Session = Depends(get_db)):
    """Create a new binding between an AI Trader and a Program."""
    # Verify account exists
    account = db.query(Account).filter(Account.id == account_id, Account.is_deleted != True).first()
    if not account:
        raise HTTPException(status_code=404, detail="AI Trader not found")

    # Verify program exists
    program = db.query(TradingProgram).filter(TradingProgram.id == data.program_id, TradingProgram.is_deleted != True).first()
    if not program:
        raise HTTPException(status_code=404, detail="Program not found")

    # Check for duplicate binding
    existing = db.query(AccountProgramBinding).filter(
        AccountProgramBinding.account_id == account_id,
        AccountProgramBinding.program_id == data.program_id,
        AccountProgramBinding.is_deleted != True
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Binding already exists")

    binding = AccountProgramBinding(
        account_id=account_id,
        program_id=data.program_id,
        signal_pool_ids=json.dumps(data.signal_pool_ids) if data.signal_pool_ids else None,
        trigger_interval=data.trigger_interval,
        scheduled_trigger_enabled=data.scheduled_trigger_enabled,
        is_active=data.is_active,
        params_override=json.dumps(data.params_override) if data.params_override else None,
        exchange=data.exchange,
    )
    db.add(binding)
    db.commit()
    db.refresh(binding)

    return _binding_to_response(binding, db)


@router.put("/bindings/{binding_id}", response_model=BindingResponse)
def update_binding(binding_id: int, data: BindingUpdate, db: Session = Depends(get_db)):
    """Update a program binding's trigger configuration."""
    binding = db.query(AccountProgramBinding).filter(
        AccountProgramBinding.id == binding_id,
        AccountProgramBinding.is_deleted != True
    ).first()

    if not binding:
        raise HTTPException(status_code=404, detail="Binding not found")

    if data.signal_pool_ids is not None:
        binding.signal_pool_ids = json.dumps(data.signal_pool_ids)
    if data.trigger_interval is not None:
        binding.trigger_interval = data.trigger_interval
    if data.scheduled_trigger_enabled is not None:
        binding.scheduled_trigger_enabled = data.scheduled_trigger_enabled
    if data.is_active is not None:
        binding.is_active = data.is_active
    if data.params_override is not None:
        binding.params_override = json.dumps(data.params_override)
    if data.exchange is not None:
        binding.exchange = data.exchange

    db.commit()
    db.refresh(binding)

    return _binding_to_response(binding, db)


@router.delete("/bindings/{binding_id}")
def delete_binding(binding_id: int, db: Session = Depends(get_db)):
    """Delete a program binding with active-status checking."""
    from services.entity_deletion_service import delete_program_binding
    result = delete_program_binding(db, binding_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Binding not found"))
    return result


# ============================================================================
