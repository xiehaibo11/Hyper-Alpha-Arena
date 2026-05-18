"""API router assembly for Program Trader."""

from fastapi import APIRouter

from routes.program_schemas import ProgramCreate, ProgramUpdate
from routes.program_crud_routes import create_program, update_program
from routes.program_test_run_routes import router as test_run_router
from routes.program_reference_routes import router as reference_router
from routes.program_crud_routes import router as crud_router
from routes.program_ai_routes import router as ai_router
from routes.program_binding_routes import router as binding_router
from routes.program_preview_routes import router as preview_router
from routes.program_legacy_backtest_routes import router as legacy_backtest_router
from routes.program_execution_routes import router as execution_router
from routes.program_market_routes import router as market_router
from routes.program_backtest_routes import router as backtest_router
from routes.program_backtest_detail_routes import router as backtest_detail_router


router = APIRouter(prefix="/api/programs", tags=["Program Trader"])

# Keep specific routes before generic path-parameter routes.
router.include_router(test_run_router)
router.include_router(reference_router)
router.include_router(ai_router)
router.include_router(binding_router)
router.include_router(preview_router)
router.include_router(execution_router)
router.include_router(market_router)
router.include_router(backtest_router)
router.include_router(backtest_detail_router)
router.include_router(crud_router)
router.include_router(legacy_backtest_router)

__all__ = [
    "router",
    "ProgramCreate",
    "ProgramUpdate",
    "create_program",
    "update_program",
]
