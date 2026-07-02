"""Abstract base class for all ad platform adapters.

Every platform (Facebook, TikTok, Google, ...) MUST implement this interface.
Adding a new platform = write 1 class + 1 row in dim_platform — no core code change.
"""

from abc import ABC, abstractmethod
from datetime import date

from app.domain.models import CanonicalAdMetric


class AdPlatformAdapter(ABC):
    """Contract that every ad platform adapter must fulfill.

    Subclass and implement `fetch_raw()` + `normalize()`.
    `platform_code` is used as a key to select the right adapter at runtime.
    """

    platform_code: str  # e.g. 'FACEBOOK', 'TIKTOK', 'GOOGLE'

    @abstractmethod
    async def fetch_raw(self, account_external_id: str, target_date: date) -> list[dict]:
        """Call the platform's reporting API and return raw JSON records.

        Must handle authentication, pagination, rate limiting.
        Returns the raw API response records (no transformation).
        """
        ...

    @abstractmethod
    def normalize(self, raw: dict) -> CanonicalAdMetric:
        """Map a single raw JSON record → CanonicalAdMetric domain model."""
        ...