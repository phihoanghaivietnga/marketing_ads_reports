"""Pydantic schemas for GET /api/v1/metrics endpoint.

Request: validated query parameters with date range, filters, comparison options.
Response: MetricResponse with current/previous periods and summary.
"""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class Granularity(str, Enum):
    """Time granularity for aggregation."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class CompareMode(str, Enum):
    """Comparison mode for previous period."""

    PREVIOUS_PERIOD = "previous_period"
    PREVIOUS_YEAR = "previous_year"


class MetricsQueryParams(BaseModel):
    """Validated query parameters for GET /api/v1/metrics."""

    date_from: date = Field(..., description="Start date (inclusive), ISO format YYYY-MM-DD")
    date_to: date = Field(..., description="End date (inclusive), ISO format YYYY-MM-DD")
    platform_codes: Optional[list[str]] = Field(
        default=None,
        description="Filter by platform: ['FACEBOOK', 'TIKTOK', 'GOOGLE']",
    )
    campaign_ids: Optional[list[int]] = Field(
        default=None,
        description="Filter by campaign IDs from dim_campaign",
    )
    granularity: Granularity = Field(
        default=Granularity.DAY,
        description="Aggregation granularity",
    )
    compare_previous_period: bool = Field(
        default=False,
        description="Include previous period data for comparison",
    )
    compare_mode: CompareMode = Field(
        default=CompareMode.PREVIOUS_PERIOD,
        description="Comparison mode: previous_period or previous_year",
    )

    @model_validator(mode="after")
    def validate_date_range(self) -> "MetricsQueryParams":
        """Ensure date_from <= date_to."""
        if self.date_from > self.date_to:
            raise ValueError("date_from must be <= date_to")
        return self

    @model_validator(mode="after")
    def normalize_platform_codes(self) -> "MetricsQueryParams":
        """Uppercase platform codes for consistency."""
        if self.platform_codes:
            self.platform_codes = [p.upper() for p in self.platform_codes]
        return self


class MetricRow(BaseModel):
    """A single row in the metrics response — one date's aggregated values."""

    date: date
    spend: Decimal = Decimal("0")
    impressions: int = 0
    clicks: int = 0
    conversions: int = 0
    conversion_value: Decimal = Decimal("0")


class MetricSummaryItem(BaseModel):
    """Summary for a single metric — current total, previous total, % change."""

    current: Decimal
    previous: Decimal | None = None
    change_pct: float | None = None


class MetricSummary(BaseModel):
    """Aggregated summary of all core metrics + % change vs previous period."""

    spend: MetricSummaryItem
    impressions: MetricSummaryItem
    clicks: MetricSummaryItem
    conversions: MetricSummaryItem
    conversion_value: MetricSummaryItem


class MetricsResponse(BaseModel):
    """Response for GET /api/v1/metrics."""

    current: list[MetricRow]
    previous: list[MetricRow] | None = None
    summary: MetricSummary