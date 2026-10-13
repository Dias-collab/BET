from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Coupon:
    home_team: str
    away_team: str
    market: str
    selection: str
    event_date: str | None = None
    event_time: str | None = None
    shown_odds: Decimal | None = None

    @property
    def event(self) -> str:
        return f"{self.home_team} — {self.away_team}"

    def summary(self) -> str:
        timing = " ".join(x for x in (self.event_date, self.event_time) if x)
        odds = f"; коэф. на скрине {self.shown_odds}" if self.shown_odds else ""
        return f"{self.event} | {self.market}: {self.selection} | {timing}{odds}".strip()


@dataclass(frozen=True, slots=True)
class CouponVerification:
    ok: bool
    expected: Coupon
    coupon_text: str
    problems: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CouponBuildResult:
    event_url: str
    current_odds: Decimal | None

