"""Pydantic schemas for Program Trader routes."""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class ProgramCreate(BaseModel):
    name: str
    description: Optional[str] = None
    code: str
    params: Optional[Dict[str, Any]] = None
    icon: Optional[str] = None


class ProgramUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    code: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    icon: Optional[str] = None


class ProgramResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    code: str
    params: Optional[Dict[str, Any]]
    icon: Optional[str]
    binding_count: int = 0
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class WalletInfo(BaseModel):
    environment: str
    address: str


class BindingCreate(BaseModel):
    program_id: int
    signal_pool_ids: List[int] = []
    trigger_interval: int = 180
    scheduled_trigger_enabled: bool = False
    is_active: bool = True
    params_override: Optional[Dict[str, Any]] = None
    exchange: str = "hyperliquid"


class BindingUpdate(BaseModel):
    signal_pool_ids: Optional[List[int]] = None
    trigger_interval: Optional[int] = None
    scheduled_trigger_enabled: Optional[bool] = None
    is_active: Optional[bool] = None
    params_override: Optional[Dict[str, Any]] = None
    exchange: Optional[str] = None


class BindingResponse(BaseModel):
    id: int
    account_id: int
    account_name: str
    program_id: int
    program_name: str
    signal_pool_ids: List[int]
    signal_pool_names: List[str] = []
    trigger_interval: int
    scheduled_trigger_enabled: bool
    is_active: bool
    last_trigger_at: Optional[str]
    params_override: Optional[Dict[str, Any]]
    exchange: str = "hyperliquid"
    wallets: List[WalletInfo] = []
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class ValidationResponse(BaseModel):
    is_valid: bool
    errors: List[str]
    warnings: List[str]


class LegacyBacktestRequest(BaseModel):
    symbol: str = "BTC"
    period: str = "5m"
    days: int = 7
    initial_balance: float = 10000.0


class LegacyBacktestResponse(BaseModel):
    success: bool
    error: Optional[str] = None
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    equity_curve: List[Dict[str, Any]] = []


class SignalPoolInfo(BaseModel):
    id: int
    pool_name: str
    symbols: List[str]
    enabled: bool
    exchange: str = "hyperliquid"
    source_type: Optional[str] = "market_signals"


class AccountInfo(BaseModel):
    id: int
    name: str
    model: Optional[str]


class TestRunRequest(BaseModel):
    code: str
    symbol: str = "BTC"
    period: str = "1h"


class ErrorLocation(BaseModel):
    file: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None
    function: Optional[str] = None
    code_context: Optional[str] = None


class DecisionResult(BaseModel):
    action: str
    symbol: Optional[str] = None
    size_usd: Optional[float] = None
    leverage: Optional[int] = None
    reason: Optional[str] = None


class MarketDataSummary(BaseModel):
    symbol: str
    current_price: Optional[float] = None
    price_change_1h: Optional[float] = None
    klines_count: int = 0
    indicators_loaded: List[str] = []


class TestRunResponse(BaseModel):
    success: bool
    decision: Optional[DecisionResult] = None
    execution_time_ms: float = 0.0
    market_data: Optional[MarketDataSummary] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    error_traceback: Optional[str] = None
    error_location: Optional[ErrorLocation] = None
    suggestions: List[str] = []
    available_apis: Optional[Dict[str, Any]] = None


class AiProgramChatRequest(BaseModel):
    message: str
    account_id: int
    conversation_id: Optional[int] = None
    program_id: Optional[int] = None
    use_background_task: bool = True


class ConversationResponse(BaseModel):
    id: int
    program_id: Optional[int]
    title: str
    created_at: str
    updated_at: str


class SaveSuggestionResponse(BaseModel):
    code: str
    name: str
    description: str


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    saveSuggestion: Optional[SaveSuggestionResponse] = None
    reasoning_snapshot: Optional[str] = None
    tool_calls_log: Optional[List[Dict[str, Any]]] = None
    created_at: str
    is_complete: bool = True


class PreviewRunResponse(BaseModel):
    success: bool
    error: Optional[str] = None
    input_data: Optional[Dict[str, Any]] = None
    data_queries: List[Dict[str, Any]] = []
    execution_logs: List[str] = []
    decision: Optional[Dict[str, Any]] = None
    execution_time_ms: float = 0.0


class ExecutionLogResponse(BaseModel):
    id: int
    binding_id: Optional[int]
    account_id: int
    account_name: str
    program_id: Optional[int]
    program_name: str
    trigger_type: str
    trigger_symbol: Optional[str]
    signal_pool_id: Optional[int]
    signal_pool_name: Optional[str]
    wallet_address: Optional[str]
    success: bool
    decision_action: Optional[str]
    decision_symbol: Optional[str]
    decision_size_usd: Optional[float]
    decision_leverage: Optional[int]
    decision_reason: Optional[str]
    error_message: Optional[str]
    execution_time_ms: Optional[float]
    market_context: Optional[Dict[str, Any]] = None
    params_snapshot: Optional[Dict[str, Any]] = None
    decision_json: Optional[Dict[str, Any]] = None
    created_at: str
    exchange: str = "hyperliquid"

    class Config:
        from_attributes = True


class MarketDataQueryRequest(BaseModel):
    symbol: str = "BTC"
    period: str = "1h"
    indicators: Optional[List[str]] = None
    flow_metrics: Optional[List[str]] = None


class MarketDataQueryResponse(BaseModel):
    symbol: str
    period: str
    price: Optional[float]
    indicators: Dict[str, Any]
    flow_metrics: Dict[str, Any]
    regime: Optional[Dict[str, Any]]
    klines_sample: Optional[List[Dict[str, Any]]]
    timestamp: str


class ProgramBacktestRequest(BaseModel):
    binding_id: int
    start_time_ms: int
    end_time_ms: int
    initial_balance: float = 10000.0
    slippage_percent: float = 0.05
    fee_rate: float = 0.035
