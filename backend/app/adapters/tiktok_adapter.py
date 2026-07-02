"""TikTok Ads API adapter — stub for Phase 2.

Currently raises NotImplementedError.
To implement: follow the same interface contract as FacebookAdapter.
"""

from datetime import date

from app.adapters.base import AdPlatformAdapter
from app.domain.models import CanonicalAdMetric


class TikTokAdapter(AdPlatformAdapter):
    """Placeholder — implement in Phase 2 (TikTok Ads integration)."""

    platform_code = "TIKTOK"

    async def fetch_raw(self, account_external_id: str, target_date: date) -> list[dict]:
        """Not yet implemented."""
        raise NotImplementedError("TikTok Ads integration is planned for Phase 2")

    def normalize(self, raw: dict) -> CanonicalAdMetric:
        """Not yet implemented."""
        raise NotImplementedError("TikTok Ads integration is planned for Phase 2")