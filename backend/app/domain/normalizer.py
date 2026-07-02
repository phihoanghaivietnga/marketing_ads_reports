"""Normalizer — maps raw platform JSON records → CanonicalAdMetric.

Serves as the single entry point for the normalize_and_stage Celery task:
  1. Selects the right adapter based on platform_code
  2. Calls adapter.normalize(raw) → CanonicalAdMetric
  3. Validates required fields, returns error info for invalid records

Each adapter implements its own normalize() method.
This module provides shared helpers and the top-level dispatch function.
"""

import logging
from typing import Any

from app.adapters.base import AdPlatformAdapter
from app.domain.models import CanonicalAdMetric

logger = logging.getLogger(__name__)

# Lazily imported to avoid circular imports when adapters import from domain
_adapter_registry: dict[str, type[AdPlatformAdapter]] | None = None


def _get_registry() -> dict[str, type[AdPlatformAdapter]]:
    """Lazy-load the adapter registry (avoids circular imports at module level)."""
    global _adapter_registry
    if _adapter_registry is None:
        from app.adapters.facebook_adapter import FacebookAdapter
        from app.adapters.tiktok_adapter import TikTokAdapter
        from app.adapters.google_adapter import GoogleAdapter

        _adapter_registry = {
            "FACEBOOK": FacebookAdapter,
            "TIKTOK": TikTokAdapter,
            "GOOGLE": GoogleAdapter,
        }
    return _adapter_registry


def normalize_raw(
    platform_code: str,
    account_external_id: str,
    raw_records: list[dict],
) -> tuple[list[CanonicalAdMetric], list[dict[str, Any]]]:
    """Normalize a batch of raw platform records → CanonicalAdMetric.

    Args:
        platform_code: 'FACEBOOK' | 'TIKTOK' | 'GOOGLE'
        account_external_id: Account ID to fill into each record
        raw_records: List of raw JSON dicts from the platform API

    Returns:
        (valid_records, error_records):
        - valid_records: list of CanonicalAdMetric (ready for staging)
        - error_records: list of {raw_index, raw_record, error_message}
          for records that failed normalization
    """
    registry = _get_registry()
    adapter_class = registry.get(platform_code)

    if adapter_class is None:
        raise ValueError(f"No adapter registered for platform_code='{platform_code}'")

    adapter = adapter_class()

    valid: list[CanonicalAdMetric] = []
    errors: list[dict[str, Any]] = []

    for idx, raw in enumerate(raw_records):
        try:
            metric = adapter.normalize(raw)
            # Override account_external_id — the task knows the account,
            # the raw record may not contain it directly.
            metric.account_external_id = account_external_id
            valid.append(metric)
        except Exception as exc:
            logger.warning(
                "Normalization failed for record %d platform=%s: %s",
                idx,
                platform_code,
                exc,
            )
            errors.append({
                "raw_index": idx,
                "raw_record": raw,
                "error_message": str(exc),
            })

    logger.info(
        "Normalized %d/%d records for platform=%s account=%s (%d errors)",
        len(valid),
        len(raw_records),
        platform_code,
        account_external_id,
        len(errors),
    )
    return valid, errors


def validate_canonical(metric: CanonicalAdMetric) -> list[str]:
    """Basic validation on a normalized CanonicalAdMetric.

    Returns a list of error messages. Empty list = valid.
    """
    issues: list[str] = []

    if not metric.platform_code:
        issues.append("platform_code is empty")
    if not metric.account_external_id:
        issues.append("account_external_id is empty")
    if not metric.campaign_external_id:
        issues.append("campaign_external_id is empty")
    if not metric.ad_external_id:
        issues.append("ad_external_id is empty")

    # Negative metrics don't make sense
    if metric.spend < 0:
        issues.append(f"spend is negative: {metric.spend}")
    if metric.impressions < 0:
        issues.append(f"impressions is negative: {metric.impressions}")
    if metric.clicks < 0:
        issues.append(f"clicks is negative: {metric.clicks}")
    if metric.conversions < 0:
        issues.append(f"conversions is negative: {metric.conversions}")

    return issues