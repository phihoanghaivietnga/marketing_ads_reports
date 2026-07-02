"""Pydantic schemas for GET /api/v1/campaigns endpoint."""

from typing import Optional

from pydantic import BaseModel, Field


class CampaignQueryParams(BaseModel):
    """Validated query parameters for GET /api/v1/campaigns."""

    platform_codes: Optional[list[str]] = Field(
        default=None,
        description="Optional filter by platform codes",
    )


class CampaignItem(BaseModel):
    """A single campaign in the response."""

    id: int = Field(alias="campaign_id")  # type: ignore[assignment]
    name: str = Field(alias="campaign_name")  # type: ignore[assignment]
    platform_code: str


class CampaignsResponse(BaseModel):
    """Response for GET /api/v1/campaigns — list of campaigns."""

    campaigns: list[CampaignItem]
    total: int