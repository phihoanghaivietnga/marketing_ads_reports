"""Facebook Marketing API adapter — implements AdPlatformAdapter.

Calls Facebook Graph API /insights endpoint, returns raw JSON records.
Normalization is handled by domain/normalizer.py (not here).
"""

import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.adapters.base import AdPlatformAdapter
from app.domain.models import CanonicalAdMetric
from app.infra.settings import settings

logger = logging.getLogger(__name__)

# Facebook Insights fields to request — includes IDs, names, and core metrics.
# extra_metrics like reach, frequency, video_p25_watched_actions
# are also pulled but go into extra_metrics after normalization.
FACEBOOK_INSIGHTS_FIELDS = [
    "campaign_id",
    "campaign_name",
    "adset_id",
    "adset_name",
    "ad_id",
    "ad_name",
    "spend",
    "impressions",
    "clicks",
    "actions",
    "action_values",
    "reach",
    "frequency",
    "cpm",
    "cpp",
    "ctr",
    "cost_per_action_type",
]


class FacebookAdapter(AdPlatformAdapter):
    """Calls Facebook Marketing API v19.0 — Insights endpoint.

    Fetches ad-level metrics for a given account and date, broken down by day.
    Handles pagination via cursor-based `paging.next`.
    """

    platform_code = "FACEBOOK"

    def __init__(self) -> None:
        self._base_url = f"https://graph.facebook.com/{settings.facebook_api_version}"
        self._access_token = settings.facebook_access_token

    # ------------------------------------------------------------------
    # fetch_raw — called by Celery task fetch_and_land
    # ------------------------------------------------------------------

    async def fetch_raw(self, account_external_id: str, target_date: date) -> list[dict]:
        """Fetch raw ad insights records from Facebook for a single date.

        Returns list of dicts — each is a single ad × single day row
        from Facebook's /insights API with time_increment=1.
        """
        if not self._access_token:
            raise ValueError(
                "FACEBOOK_ACCESS_TOKEN is not set in .env — cannot call Facebook API."
            )

        url = f"{self._base_url}/act_{account_external_id}/insights"
        params: dict[str, str] = {
            "fields": ",".join(FACEBOOK_INSIGHTS_FIELDS),
            "time_range": _build_time_range(target_date),
            "level": "ad",
            "time_increment": "1",
            "limit": "500",
            "access_token": self._access_token,
        }

        all_records: list[dict] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            while url is not None:
                logger.debug("Facebook API request: %s", url)
                response = await client.get(url, params=params if url == f"{self._base_url}/act_{account_external_id}/insights" else None)
                response.raise_for_status()
                data: dict[str, Any] = response.json()

                if "error" in data:
                    logger.error("Facebook API error: %s", data["error"])
                    raise RuntimeError(f"Facebook API error: {data['error']}")

                records = data.get("data", [])
                all_records.extend(records)

                # Pagination — Facebook returns paging.next as full URL
                paging = data.get("paging", {})
                url = paging.get("next")

        logger.info(
            "Fetched %d insight rows for account %s on %s",
            len(all_records),
            account_external_id,
            target_date.isoformat(),
        )
        return all_records

    # ------------------------------------------------------------------
    # normalize — called by Celery task normalize_and_stage
    # ------------------------------------------------------------------

    def normalize(self, raw: dict) -> CanonicalAdMetric:
        """Map a single Facebook Insights row → CanonicalAdMetric.

        Handles:
        - Field name mapping (Facebook → canonical)
        - Decimal conversion for monetary values (spend, conversion_value)
        - Extraction of 'purchase' / 'offsite_conversion' actions into conversions
        - Everything else → extra_metrics
        """
        date_start = _parse_date(raw.get("date_start"))
        spend = _to_decimal(raw.get("spend", "0"))

        # Conversions — extract from actions list
        conversions = 0
        conversion_value = _to_decimal("0")
        for action in raw.get("actions", []) or []:
            action_type = action.get("action_type", "")
            if action_type in ("purchase", "offsite_conversion.fb_pixel_purchase", "omni_purchase"):
                conversions += int(action.get("value", 0))
        for action_value in raw.get("action_values", []) or []:
            action_type = action_value.get("action_type", "")
            if action_type in ("purchase", "offsite_conversion.fb_pixel_purchase", "omni_purchase"):
                conversion_value += _to_decimal(action_value.get("value", "0"))

        # Extra metrics — everything not in CanonicalAdMetric core fields
        core_fields = {
            "campaign_id", "campaign_name", "adset_id", "adset_name",
            "ad_id", "ad_name", "spend", "impressions", "clicks",
            "actions", "action_values", "date_start", "date_stop",
        }
        extra = {
            k: v for k, v in raw.items()
            if k not in core_fields and v is not None
        }

        return CanonicalAdMetric(
            platform_code=self.platform_code,
            account_external_id="",  # filled by the ETL task from task param
            campaign_external_id=str(raw.get("campaign_id", "")),
            campaign_name=str(raw.get("campaign_name", "")),
            ad_set_external_id=str(raw.get("adset_id", "")),
            ad_set_name=str(raw.get("adset_name", "")),
            ad_external_id=str(raw.get("ad_id", "")),
            ad_name=str(raw.get("ad_name", "")),
            date=date_start,
            spend=spend,
            impressions=int(raw.get("impressions", 0) or 0),
            clicks=int(raw.get("clicks", 0) or 0),
            conversions=conversions,
            conversion_value=conversion_value,
            extra_metrics=extra,
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _build_time_range(target_date: date) -> str:
    """Build Facebook time_range JSON string for a single date."""
    iso = target_date.isoformat()
    return f'{{"since":"{iso}","until":"{iso}"}}'


def _parse_date(value: str | None) -> date:
    """Parse YYYY-MM-DD string → date. Raises ValueError on invalid input."""
    if not value:
        raise ValueError("Missing date_start in Facebook insight row")
    return date.fromisoformat(value)


def _to_decimal(value: str | float | int | None) -> Decimal:
    """Safely convert a value to Decimal, defaulting to 0 on error/None."""
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")
