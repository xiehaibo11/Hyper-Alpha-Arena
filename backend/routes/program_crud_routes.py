"""CRUD routes for trading programs."""

import json
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import TradingProgram
from program_trader import validate_strategy_code
from routes.program_helpers import get_default_user, _program_to_response
from routes.program_schemas import ProgramCreate, ProgramUpdate, ProgramResponse, ValidationResponse

router = APIRouter()

@router.get("/", response_model=List[ProgramResponse])
def list_programs(db: Session = Depends(get_db)):
    """List all trading programs (code templates)."""
    user = get_default_user(db)
    programs = db.query(TradingProgram).filter(
        TradingProgram.user_id == user.id,
        TradingProgram.is_deleted != True
    ).order_by(TradingProgram.updated_at.desc()).all()

    return [_program_to_response(p, db) for p in programs]


@router.post("/", response_model=ProgramResponse)
def create_program(data: ProgramCreate, db: Session = Depends(get_db)):
    """Create a new trading program."""
    user = get_default_user(db)

    validation = validate_strategy_code(data.code)
    if not validation.is_valid:
        raise HTTPException(status_code=400, detail=f"Invalid code: {'; '.join(validation.errors)}")

    program = TradingProgram(
        user_id=user.id,
        name=data.name,
        description=data.description,
        code=data.code,
        params=json.dumps(data.params) if data.params else None,
        icon=data.icon,
    )
    db.add(program)
    db.commit()
    db.refresh(program)

    return _program_to_response(program, db)

@router.get("/{program_id}", response_model=ProgramResponse)
def get_program(program_id: int, db: Session = Depends(get_db)):
    """Get a trading program by ID."""
    user = get_default_user(db)
    program = db.query(TradingProgram).filter(
        TradingProgram.id == program_id,
        TradingProgram.user_id == user.id,
        TradingProgram.is_deleted != True
    ).first()

    if not program:
        raise HTTPException(status_code=404, detail="Program not found")

    return _program_to_response(program, db)


@router.put("/{program_id}", response_model=ProgramResponse)
def update_program(program_id: int, data: ProgramUpdate, db: Session = Depends(get_db)):
    """Update a trading program."""
    user = get_default_user(db)
    program = db.query(TradingProgram).filter(
        TradingProgram.id == program_id,
        TradingProgram.user_id == user.id,
        TradingProgram.is_deleted != True
    ).first()

    if not program:
        raise HTTPException(status_code=404, detail="Program not found")

    if data.code:
        validation = validate_strategy_code(data.code)
        if not validation.is_valid:
            raise HTTPException(status_code=400, detail=f"Invalid code: {'; '.join(validation.errors)}")
        program.code = data.code

    if data.name is not None:
        program.name = data.name
    if data.description is not None:
        program.description = data.description
    if data.params is not None:
        program.params = json.dumps(data.params)
    if data.icon is not None:
        program.icon = data.icon

    db.commit()
    db.refresh(program)

    return _program_to_response(program, db)


@router.delete("/{program_id}")
def delete_program(program_id: int, db: Session = Depends(get_db)):
    """Delete a trading program with dependency checking."""
    from services.entity_deletion_service import delete_trading_program
    result = delete_trading_program(db, program_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Program not found"))
    return result


@router.post("/validate", response_model=ValidationResponse)
def validate_code(data: dict, db: Session = Depends(get_db)):
    """Validate strategy code without saving."""
    code = data.get("code", "")
    if not code:
        raise HTTPException(status_code=400, detail="Code is required")

    validation = validate_strategy_code(code)
    return ValidationResponse(
        is_valid=validation.is_valid,
        errors=validation.errors,
        warnings=validation.warnings,
    )
