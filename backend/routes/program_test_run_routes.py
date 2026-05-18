"""Program strategy test-run routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database.connection import get_db
from program_trader import validate_strategy_code
from routes.program_helpers import _get_available_apis, _generate_suggestions, _parse_error_location
from routes.program_schemas import TestRunRequest, TestRunResponse, DecisionResult

router = APIRouter()

@router.post("/test-run", response_model=TestRunResponse)
def test_run_program(request: TestRunRequest, db: Session = Depends(get_db)):
    """
    Test-run a program in sandbox environment without saving.

    This API is designed for:
    1. Syntax validation before saving/binding
    2. AI-assisted debugging with detailed error info
    3. Quick iteration during development

    The endpoint only provides execution environment (MarketData with data_provider).
    Strategy code internally calls data_provider methods to get market data as needed.

    Returns comprehensive error information when execution fails.
    """
    import time
    import traceback
    from program_trader.executor import SandboxExecutor
    from program_trader.data_provider import DataProvider
    from program_trader.models import MarketData

    start_time = time.time()

    # Step 1: Validate code syntax first
    validation = validate_strategy_code(request.code)
    if not validation.is_valid:
        return TestRunResponse(
            success=False,
            error_type="ValidationError",
            error_message=f"Code validation failed: {'; '.join(validation.errors)}",
            suggestions=[
                "Ensure your code defines a class with should_trade(self, data: MarketData) method",
                "The method must return a Decision object",
            ],
            available_apis=_get_available_apis(),
            execution_time_ms=(time.time() - start_time) * 1000,
        )

    # Step 2: Prepare execution environment
    # Note: test-run is for syntax validation only, no AI Trader is bound yet,
    # so there's no real wallet address. We use simulated account data here.
    # Strategy code can still call data_provider methods to get market data
    # (e.g., get_klines, get_indicator) which don't require a wallet.
    try:
        data_provider = DataProvider(db, account_id=0, environment="mainnet")
        market_data = MarketData(
            available_balance=10000.0,  # Simulated balance for testing
            total_equity=10000.0,
            used_margin=0.0,
            margin_usage_percent=0.0,
            maintenance_margin=0.0,
            positions={},  # No positions in test mode
            trigger_symbol=request.symbol,
            trigger_type="manual_test",
            _data_provider=data_provider,
        )

    except Exception as e:
        return TestRunResponse(
            success=False,
            error_type="DataError",
            error_message=f"Failed to initialize execution environment: {str(e)}",
            error_traceback=traceback.format_exc(),
            suggestions=["Check database connection"],
            available_apis=_get_available_apis(),
            execution_time_ms=(time.time() - start_time) * 1000,
        )

    # Step 3: Execute in sandbox
    try:
        executor = SandboxExecutor(timeout_seconds=5)
        result = executor.execute(request.code, market_data, params={})

        execution_time = (time.time() - start_time) * 1000

        if result.success and result.decision:
            return TestRunResponse(
                success=True,
                decision=DecisionResult(
                    action=result.decision.operation,
                    symbol=result.decision.symbol,
                    size_usd=getattr(result.decision, 'size_usd', None),
                    leverage=result.decision.leverage,
                    reason=result.decision.reason,
                ),
                execution_time_ms=result.execution_time_ms,
            )
        else:
            # Execution failed - parse error details
            error_str = result.error or "Unknown error"
            tb_str = error_str

            # Determine error type
            error_type = "RuntimeError"
            if "ImportError" in error_str:
                error_type = "ImportError"
            elif "SyntaxError" in error_str:
                error_type = "SyntaxError"
            elif "NameError" in error_str:
                error_type = "NameError"
            elif "AttributeError" in error_str:
                error_type = "AttributeError"
            elif "TypeError" in error_str:
                error_type = "TypeError"
            elif "KeyError" in error_str:
                error_type = "KeyError"
            elif "timed out" in error_str.lower():
                error_type = "TimeoutError"
            elif "Validation failed" in error_str:
                error_type = "ValidationError"

            # Extract just the error message (first line after "Error:")
            error_msg = error_str.split('\n')[0] if '\n' in error_str else error_str
            if ": " in error_msg:
                error_msg = error_msg.split(": ", 1)[1]

            return TestRunResponse(
                success=False,
                error_type=error_type,
                error_message=error_msg,
                error_traceback=tb_str,
                error_location=_parse_error_location(tb_str, request.code),
                suggestions=_generate_suggestions(error_type, error_msg, tb_str),
                available_apis=_get_available_apis(),
                execution_time_ms=execution_time,
            )

    except Exception as e:
        tb_str = traceback.format_exc()
        error_type = type(e).__name__

        return TestRunResponse(
            success=False,
            error_type=error_type,
            error_message=str(e),
            error_traceback=tb_str,
            error_location=_parse_error_location(tb_str, request.code),
            suggestions=_generate_suggestions(error_type, str(e), tb_str),
            available_apis=_get_available_apis(),
            execution_time_ms=(time.time() - start_time) * 1000,
        )
