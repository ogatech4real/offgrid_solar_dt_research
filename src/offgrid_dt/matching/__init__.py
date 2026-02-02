"""Day-ahead matching: expected demand vs expected solar availability.

All outputs are framed as day-ahead planning (00:00–24:00) based on forecasted
solar availability. Explanations communicate uncertainty and advisory intent.
"""

from .day_ahead import (
    ApplianceAdvisory,
    DayAheadMatchingResult,
    TimeWindow,
    compute_day_ahead_matching,
    format_day_ahead_statements,
)

__all__ = [
    "ApplianceAdvisory",
    "DayAheadMatchingResult",
    "TimeWindow",
    "compute_day_ahead_matching",
    "format_day_ahead_statements",
]
