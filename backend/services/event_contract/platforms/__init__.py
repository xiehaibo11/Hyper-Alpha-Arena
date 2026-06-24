"""Event-contract platform adapters (execution) and data-source registry."""
from .registry import (
    get_execution_platform,
    list_data_sources,
    list_execution_platforms,
    overview,
)

__all__ = [
    "get_execution_platform",
    "list_data_sources",
    "list_execution_platforms",
    "overview",
]
