"""Domain models — pure business logic, no framework/infrastructure dependency.

CanonicalAdMetric is the single source of truth for ad metrics across all platforms.
Every adapter MUST normalize its raw JSON into this format.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class CanonicalAdMetric(BaseModel):
    """Normalized ad metric — grain = 1 ad × 1 date.

    All platform-specific adapters produce this exact model.
    Extra platform-specific metrics go into `extra_metrics` JSONB,
    never into new columns (to avoid schema migration per platform).
    """

    platform_code: str
    account_external_id: str
    campaign_external_id: str
    campaign_name: str = ""
    ad_set_external_id: str
    ad_set_name: str = ""
    ad_external_id: str
    ad_name: str = ""
    date: date
    spend: Decimal = Decimal("0")
    impressions: int = 0
    clicks: int = 0
    conversions: int = 0
    conversion_value: Decimal = Decimal("0")
    extra_metrics: dict = Field(default_factory=dict)