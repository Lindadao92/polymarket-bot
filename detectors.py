"""
detectors.py — Opportunity-detection strategies for Polymarket markets.

Each public function accepts market/event data and returns a list of ``Alert``
objects.  Every alert now includes a structured recommendation:

  - action:      BUY YES | BUY NO | WATCH | SKIP
  - confidence:  HIGH | MEDIUM | LOW
  - bet_size:    LARGE ($50-100) | MEDIUM ($20-50) | SMALL ($5-10) | NONE
  - explanation: 1-2 plain-English sentences describing the opportunity
  - risk_note:   optional caution (e.g. low liquidity, near expiry, etc.)

Recommendation logic is signal-specific and driven by quantitative thresholds
so that only genuinely interesting situations get strong buy signals.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import config

logger = logging.getLogger(__name__)


# ── Recommendation constants ─────────────────────────────────────────────────

class Action:
    BUY_YES = "BUY YES"
    BUY_NO  = "BUY NO"
    WATCH   = "WATCH"
    SKIP    = "SKIP"

class Confidence:
    HIGH   = "HIGH"
    MEDIUM = "MEDIUM"
    LOW    = "LOW"

class BetSize:
    LARGE  = "LARGE ($50–100)"
    MEDIUM = "MEDIUM ($20–50)"
    SMALL  = "SMALL ($5–10)"
    NONE   = "NONE"

# Emoji badges for the Telegram header line
ACTION_EMOJI = {
    Action.BUY_YES: "🟢",
    Action.BUY_NO:  "🔴",
    Action.WATCH:   "🟡",
    Action.SKIP:    "⚪",
}
CONFIDENCE_EMOJI = {
    Confidence.HIGH:   "🔥",
    Confidence.MEDIUM: "📌",
    Confidence.LOW:    "💭",
}


# ── Alert dataclass ──────────────────────────────────────────────────────────

@dataclass
class Alert:
    """One opportunity alert, fully enriched with a structured recommendation."""

    # Identity
    market_id:       str
    market_question: str
    market_slug:     str
    event_slug:      str
    signal_type:     str   # odds_shift | volume_spike | closing_soon | new_market | mispricing

    # Odds snapshot
    yes_price:       float        # 0–1 implied probability of YES
    no_price:        float        # 0–1 implied probability of NO
    current_odds:    str          # human-readable, e.g. "YES 35¢ / NO 65¢"

    # Recommendation
    action:          str          # BUY YES | BUY NO | WATCH | SKIP
    confidence:      str          # HIGH | MEDIUM | LOW
    bet_size:        str          # LARGE | MEDIUM | SMALL | NONE
    explanation:     str          # 1-2 plain-English sentences
    risk_note:       str = ""     # optional caution

    # Raw signal data for scoring / sorting
    details:         dict = field(default_factory=dict)

    @property
    def market_url(self) -> str:
        slug = self.event_slug or self.market_slug
        return f"https://polymarket.com/event/{slug}"

    @property
    def unique_key(self) -> str:
        return f"{self.market_id}:{self.signal_type}"

    @property
    def edge_pct(self) -> float:
        """Estimated edge as a percentage (signal-type specific)."""
        d = self.details
        if self.signal_type == "odds_shift":
            return abs(d.get("price_change_24h", 0)) * 100
        if self.signal_type == "volume_spike":
            return min(d.get("spike_ratio", 1) * 5, 50)   # cap at 50%
        if self.signal_type == "closing_soon":
            # Edge = distance from 50¢ (the more extreme, the clearer the bet)
            return abs(self.yes_price - 0.5) * 100
        if self.signal_type == "new_market":
            return 10.0   # early-mover premium is qualitative
        if self.signal_type == "mispricing":
            return d.get("deviation", 0) * 100
        return 0.0


# ── Shared helpers ───────────────────────────────────────────────────────────

def _parse_prices(market: dict) -> list[float]:
    raw = market.get("outcomePrices", "[]")
    try:
        return [float(p) for p in json.loads(raw)]
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


def _parse_outcomes(market: dict) -> list[str]:
    raw = market.get("outcomes", "[]")
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def _odds_str(yes: float, no: float) -> str:
    """Return 'YES 35¢ / NO 65¢' style string."""
    return f"YES {yes*100:.0f}¢ / NO {no*100:.0f}¢"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def _matches_topic_filter(market: dict) -> bool:
    keywords = [k.strip().lower() for k in config.TOPIC_KEYWORDS.split(",") if k.strip()]
    if not keywords:
        return True
    text = (market.get("question", "") + " " + market.get("description", "")).lower()
    return any(kw in text for kw in keywords)


def _liquidity(market: dict) -> float:
    return _safe_float(market.get("liquidityClob") or market.get("liquidityNum"))


# ── Recommendation helpers ───────────────────────────────────────────────────

def _bet_from_confidence_and_edge(confidence: str, edge_pct: float) -> str:
    """Map confidence + edge magnitude to a bet size."""
    if confidence == Confidence.HIGH and edge_pct >= 15:
        return BetSize.LARGE
    if confidence in (Confidence.HIGH, Confidence.MEDIUM) and edge_pct >= 8:
        return BetSize.MEDIUM
    if confidence != Confidence.LOW and edge_pct >= 3:
        return BetSize.SMALL
    return BetSize.NONE


def _liquidity_risk_note(liq: float) -> str:
    if liq < 2_000:
        return "⚠️ Very low liquidity — large orders may move the price significantly. Use limit orders and keep bets tiny."
    if liq < 10_000:
        return "⚠️ Moderate liquidity — stick to small bets to avoid slippage."
    return ""


# ── 1. Sudden Odds Shift ─────────────────────────────────────────────────────

def detect_odds_shift(market: dict, event_slug: str = "") -> list[Alert]:
    """
    Flag markets where the YES price moved ≥ ODDS_SHIFT_THRESHOLD in 24 h.

    Recommendation logic:
      - Large move UP   → price may overshoot → BUY NO (fade the move)
        unless the price is still below 50¢ → BUY YES (momentum)
      - Large move DOWN → price may overshoot → BUY YES (contrarian)
        unless price is already near 0 → SKIP (market resolving)
      - Confidence scales with move size; edge = abs(change)
    """
    if not _matches_topic_filter(market):
        return []

    change = _safe_float(market.get("oneDayPriceChange"))
    abs_change = abs(change)
    if abs_change < config.ODDS_SHIFT_THRESHOLD:
        return []

    prices = _parse_prices(market)
    if not prices:
        return []

    yes = prices[0]
    no  = 1.0 - yes
    liq = _liquidity(market)

    week_change  = _safe_float(market.get("oneWeekPriceChange"))
    month_change = _safe_float(market.get("oneMonthPriceChange"))

    # Skip markets that have already resolved (price at extreme)
    if yes >= 0.99 or yes <= 0.01:
        return []

    # ── Confidence ────────────────────────────────────────────────────────────
    if abs_change >= 0.25:
        confidence = Confidence.HIGH
    elif abs_change >= 0.15:
        confidence = Confidence.MEDIUM
    else:
        confidence = Confidence.LOW

    # ── Action logic ──────────────────────────────────────────────────────────
    # Price moved UP sharply
    if change > 0:
        if yes > 0.70:
            # Already priced in heavily — fade the move
            action = Action.BUY_NO
            explanation = (
                f"YES jumped {abs_change*100:.0f}¢ in 24h and is now at {yes*100:.0f}¢ — "
                f"a likely overshoot. The market may be overreacting. "
                f"Buying NO at {no*100:.0f}¢ bets on a correction back toward fair value."
            )
        else:
            # Strong upward momentum, still room to run
            action = Action.BUY_YES
            explanation = (
                f"YES surged {abs_change*100:.0f}¢ in 24h to {yes*100:.0f}¢, suggesting "
                f"new information is driving the market. Momentum often continues "
                f"short-term — buying YES rides that wave before it fully prices in."
            )
    # Price moved DOWN sharply
    else:
        if yes < 0.15:
            # Near zero — likely resolving NO, risky contrarian
            action = Action.WATCH
            confidence = Confidence.LOW
            explanation = (
                f"YES crashed {abs_change*100:.0f}¢ in 24h and is now at just {yes*100:.0f}¢. "
                f"The market is pricing near-certain NO. Watch for any reversal news "
                f"before considering a contrarian YES bet."
            )
        else:
            # Potential overreaction — contrarian YES
            action = Action.BUY_YES
            explanation = (
                f"YES dropped {abs_change*100:.0f}¢ in 24h to {yes*100:.0f}¢ — a sharp "
                f"sell-off that may be an overreaction. If the underlying situation "
                f"hasn't changed fundamentally, buying YES here could capture the bounce."
            )

    edge = abs_change * 100
    bet  = _bet_from_confidence_and_edge(confidence, edge)
    risk = _liquidity_risk_note(liq)

    # Add extra risk note if weekly trend contradicts daily move
    if week_change != 0 and (change / abs_change) != (week_change / abs(week_change) if week_change != 0 else 1):
        risk = (risk + " " if risk else "") + (
            f"Note: the 7-day trend ({week_change*100:+.0f}¢) runs opposite to today's move — "
            f"this could be a short-term spike rather than a trend change."
        )

    return [Alert(
        market_id=market.get("id", ""),
        market_question=market.get("question", "Unknown"),
        market_slug=market.get("slug", ""),
        event_slug=event_slug,
        signal_type="odds_shift",
        yes_price=yes,
        no_price=no,
        current_odds=_odds_str(yes, no),
        action=action,
        confidence=confidence,
        bet_size=bet,
        explanation=explanation,
        risk_note=risk,
        details={
            "price_change_24h": change,
            "price_change_1w":  week_change,
            "price_change_1m":  month_change,
            "liquidity":        liq,
        },
    )]


# ── 2. Volume Spike ──────────────────────────────────────────────────────────

def detect_volume_spike(market: dict, event_slug: str = "") -> list[Alert]:
    """
    Flag markets with 24h volume ≥ VOLUME_SPIKE_MULTIPLIER × 30-day daily avg.

    Recommendation logic:
      - High volume is a signal that informed traders are active.
      - We follow the direction of the recent price change (momentum).
      - Very high spikes (>10×) get HIGH confidence; moderate (3-6×) get LOW.
    """
    if not _matches_topic_filter(market):
        return []

    vol_24h = _safe_float(market.get("volume24hr"))
    vol_1mo = _safe_float(market.get("volume1mo"))
    if vol_24h < config.MIN_VOLUME_24H or vol_1mo <= 0:
        return []

    avg_daily = vol_1mo / 30.0
    ratio = vol_24h / avg_daily
    if ratio < config.VOLUME_SPIKE_MULTIPLIER:
        return []

    prices = _parse_prices(market)
    if not prices:
        return []

    yes = prices[0]
    no  = 1.0 - yes
    liq = _liquidity(market)
    change = _safe_float(market.get("oneDayPriceChange"))

    # Skip near-resolved markets
    if yes >= 0.98 or yes <= 0.02:
        return []

    # ── Confidence ────────────────────────────────────────────────────────────
    if ratio >= 10:
        confidence = Confidence.HIGH
    elif ratio >= 5:
        confidence = Confidence.MEDIUM
    else:
        confidence = Confidence.LOW

    # ── Action: follow the price direction of the spike ───────────────────────
    if change > 0.03:
        action = Action.BUY_YES
        explanation = (
            f"Trading volume is {ratio:.1f}× the normal daily average (${vol_24h:,.0f} "
            f"in 24h) and the price is rising (+{change*100:.0f}¢). Heavy buying "
            f"activity usually signals informed traders acting on new information — "
            f"buying YES follows the smart money."
        )
    elif change < -0.03:
        action = Action.BUY_NO
        explanation = (
            f"Trading volume is {ratio:.1f}× the normal daily average (${vol_24h:,.0f} "
            f"in 24h) and the price is falling ({change*100:.0f}¢). Heavy selling "
            f"pressure suggests informed traders are exiting YES — buying NO "
            f"follows the direction of the volume-driven move."
        )
    else:
        # High volume but flat price — contested market, watch only
        action = Action.WATCH
        confidence = Confidence.LOW
        explanation = (
            f"Unusually high volume ({ratio:.1f}× normal, ${vol_24h:,.0f} in 24h) "
            f"but the price hasn't moved much yet. This suggests a tug-of-war "
            f"between buyers and sellers. Watch for a price breakout in either "
            f"direction before committing."
        )

    edge = min(ratio * 3, 40)   # proxy edge: higher ratio = more edge
    bet  = _bet_from_confidence_and_edge(confidence, edge)
    risk = _liquidity_risk_note(liq)
    if ratio >= 10 and not risk:
        risk = "Note: extreme volume spikes can sometimes be wash trading or a single large order — verify with external news."

    return [Alert(
        market_id=market.get("id", ""),
        market_question=market.get("question", "Unknown"),
        market_slug=market.get("slug", ""),
        event_slug=event_slug,
        signal_type="volume_spike",
        yes_price=yes,
        no_price=no,
        current_odds=_odds_str(yes, no),
        action=action,
        confidence=confidence,
        bet_size=bet,
        explanation=explanation,
        risk_note=risk,
        details={
            "volume_24h":      vol_24h,
            "avg_daily":       avg_daily,
            "spike_ratio":     ratio,
            "price_change_24h": change,
            "liquidity":       liq,
        },
    )]


# ── 3. Markets About to Resolve ──────────────────────────────────────────────

def detect_closing_soon(market: dict, event_slug: str = "") -> list[Alert]:
    """
    Flag markets resolving within CLOSING_SOON_HOURS whose odds are not extreme.

    Recommendation logic:
      - Very close to expiry (< 6h) with clear odds → HIGH confidence bet
      - YES > 75¢ near expiry → BUY YES (lock in the win)
      - YES < 25¢ near expiry → BUY NO (lock in the win)
      - 25–75¢ range → WATCH (still genuinely uncertain)
    """
    if not _matches_topic_filter(market):
        return []

    end_str = market.get("endDate")
    if not end_str:
        return []
    try:
        end_date = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return []

    now = datetime.now(timezone.utc)
    hours_left = (end_date - now).total_seconds() / 3600.0
    if hours_left <= 0 or hours_left > config.CLOSING_SOON_HOURS:
        return []

    prices = _parse_prices(market)
    if not prices:
        return []

    yes = prices[0]
    no  = 1.0 - yes
    liq = _liquidity(market)

    if not (config.CLOSING_EDGE_MIN <= yes <= config.CLOSING_EDGE_MAX):
        return []

    # ── Confidence scales with urgency and clarity of odds ────────────────────
    if hours_left <= 6:
        confidence = Confidence.HIGH
    elif hours_left <= 24:
        confidence = Confidence.MEDIUM
    else:
        confidence = Confidence.LOW

    # ── Action ────────────────────────────────────────────────────────────────
    if yes >= 0.75:
        action = Action.BUY_YES
        edge   = (yes - 0.5) * 100
        explanation = (
            f"This market resolves in {hours_left:.1f} hours and YES is already "
            f"at {yes*100:.0f}¢. If you believe the outcome is YES, buying now "
            f"locks in a {(1/yes - 1)*100:.0f}% return with very little time left "
            f"for the odds to move against you."
        )
    elif yes <= 0.25:
        action = Action.BUY_NO
        edge   = (0.5 - yes) * 100
        explanation = (
            f"This market resolves in {hours_left:.1f} hours and YES is only "
            f"{yes*100:.0f}¢ — the market strongly expects NO. Buying NO at "
            f"{no*100:.0f}¢ offers a {(1/no - 1)*100:.0f}% return if the "
            f"outcome is indeed NO, with little time left for a reversal."
        )
    else:
        # Genuinely uncertain — watch, don't bet blindly
        action     = Action.WATCH
        confidence = Confidence.LOW
        edge       = abs(yes - 0.5) * 100
        explanation = (
            f"Market closes in {hours_left:.1f} hours with YES at {yes*100:.0f}¢ — "
            f"genuinely uncertain. Only bet if you have specific knowledge about "
            f"the outcome that the market may not have priced in yet."
        )

    bet  = _bet_from_confidence_and_edge(confidence, edge)
    risk = _liquidity_risk_note(liq)
    if hours_left <= 3:
        risk = (risk + " " if risk else "") + (
            "⏰ Resolves in under 3 hours — act quickly or the opportunity will be gone."
        )

    return [Alert(
        market_id=market.get("id", ""),
        market_question=market.get("question", "Unknown"),
        market_slug=market.get("slug", ""),
        event_slug=event_slug,
        signal_type="closing_soon",
        yes_price=yes,
        no_price=no,
        current_odds=_odds_str(yes, no),
        action=action,
        confidence=confidence,
        bet_size=bet,
        explanation=explanation,
        risk_note=risk,
        details={
            "hours_until_close": hours_left,
            "end_date":          end_str,
            "liquidity":         liq,
        },
    )]


# ── 4. New Markets ───────────────────────────────────────────────────────────

def detect_new_market(market: dict, event_slug: str = "") -> list[Alert]:
    """
    Flag recently created markets where early participants may get better odds.

    Recommendation logic:
      - New markets often open near 50¢ regardless of true probability.
      - If the opening price is far from 50¢, the creator has an informed view.
      - We recommend WATCH unless there's a clear directional signal.
      - Confidence is always LOW-MEDIUM since there's no price history yet.
    """
    if not _matches_topic_filter(market):
        return []

    created_str = market.get("createdAt")
    if not created_str:
        return []
    try:
        created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return []

    now = datetime.now(timezone.utc)
    age_hours = (now - created).total_seconds() / 3600.0
    if age_hours > config.NEW_MARKET_HOURS:
        return []

    liq = _liquidity(market)
    if liq < config.NEW_MARKET_MIN_LIQUIDITY:
        return []

    prices = _parse_prices(market)
    if not prices:
        return []

    yes = prices[0]
    no  = 1.0 - yes

    # Skip near-resolved markets (price at extreme)
    if yes >= 0.97 or yes <= 0.03:
        return []

    # ── Action: only directional if odds are clearly skewed ──────────────────
    if yes <= 0.20:
        action     = Action.BUY_NO
        confidence = Confidence.MEDIUM
        explanation = (
            f"New market ({age_hours:.0f}h old) opened at just {yes*100:.0f}¢ for YES — "
            f"the creator already has a strong NO bias. Early liquidity is thin, "
            f"so odds may not yet reflect all public information. "
            f"Buying NO at {no*100:.0f}¢ aligns with the opening signal."
        )
    elif yes >= 0.80:
        action     = Action.BUY_YES
        confidence = Confidence.MEDIUM
        explanation = (
            f"New market ({age_hours:.0f}h old) opened at {yes*100:.0f}¢ for YES — "
            f"a strong opening bias toward YES. Early movers often set aggressive "
            f"prices. Buying YES at {yes*100:.0f}¢ follows the initial informed view "
            f"before the broader market weighs in."
        )
    else:
        action     = Action.WATCH
        confidence = Confidence.LOW
        explanation = (
            f"Brand-new market ({age_hours:.0f}h old) with ${liq:,.0f} in liquidity. "
            f"Odds are near 50/50 ({yes*100:.0f}¢ YES) — the market hasn't formed "
            f"a strong view yet. Research the question and return once you have "
            f"an edge over the current price."
        )

    bet  = _bet_from_confidence_and_edge(confidence, 10)
    risk = _liquidity_risk_note(liq)
    risk = (risk + " " if risk else "") + (
        "New markets have no price history — treat early odds as a rough estimate only."
    )

    return [Alert(
        market_id=market.get("id", ""),
        market_question=market.get("question", "Unknown"),
        market_slug=market.get("slug", ""),
        event_slug=event_slug,
        signal_type="new_market",
        yes_price=yes,
        no_price=no,
        current_odds=_odds_str(yes, no),
        action=action,
        confidence=confidence,
        bet_size=bet,
        explanation=explanation,
        risk_note=risk,
        details={
            "age_hours": age_hours,
            "liquidity": liq,
        },
    )]


# ── 5. Mispricing ────────────────────────────────────────────────────────────

def detect_mispricing(event: dict) -> list[Alert]:
    """
    In multi-outcome events, flag when implied probabilities deviate from 100%.

    Recommendation logic:
      - Sum > 100%: at least one outcome is overpriced → find the most
        overpriced and recommend BUY NO on it.
      - Sum < 100%: at least one outcome is underpriced → find the most
        underpriced and recommend BUY YES on it.
      - Confidence scales with deviation size.
    """
    markets = event.get("markets", [])
    if len(markets) < 2:
        return []

    active = [
        m for m in markets
        if m.get("active") and not m.get("closed") and m.get("enableOrderBook")
    ]
    if len(active) < 2:
        return []

    total_liq = sum(_liquidity(m) for m in active)
    if total_liq < config.MISPRICE_MIN_LIQUIDITY:
        return []

    yes_data: list[tuple[dict, float]] = []
    for m in active:
        p = _parse_prices(m)
        if p:
            yes_data.append((m, p[0]))

    if len(yes_data) < 2:
        return []

    prob_sum = sum(p for _, p in yes_data)
    deviation = abs(prob_sum - 1.0)
    if deviation < config.MISPRICE_SUM_DEVIATION:
        return []

    # Filter out sports prop-bet events where many independent markets are
    # grouped together (e.g. 50+ player prop outcomes). These always sum
    # far above 100% by design and are not true mispricings.
    if len(yes_data) > 20 or prob_sum > 3.0:
        return []

    # ── Confidence ────────────────────────────────────────────────────────────
    if deviation >= 0.15:
        confidence = Confidence.HIGH
    elif deviation >= 0.08:
        confidence = Confidence.MEDIUM
    else:
        confidence = Confidence.LOW

    event_slug = event.get("slug", "")

    # ── Find the single most mis-priced outcome ───────────────────────────────
    if prob_sum > 1.0:
        # Over-sum: find the outcome with the highest price (most overpriced)
        worst_market, worst_price = max(yes_data, key=lambda x: x[1])
        action = Action.BUY_NO
        yes = worst_price
        no  = 1.0 - yes
        outcome_label = (
            worst_market.get("groupItemTitle") or
            worst_market.get("question", "?")[:40]
        )
        explanation = (
            f"The {len(yes_data)} outcomes in this event sum to {prob_sum*100:.0f}¢ "
            f"(should be 100¢) — a {deviation*100:.0f}¢ overpricing. "
            f"The most overpriced outcome is \"{outcome_label}\" at {yes*100:.0f}¢. "
            f"Buying NO on it is a near-arbitrage: if any other outcome wins, you profit."
        )
        mkt = worst_market
    else:
        # Under-sum: find the outcome with the lowest price (most underpriced)
        best_market, best_price = min(yes_data, key=lambda x: x[1])
        action = Action.BUY_YES
        yes = best_price
        no  = 1.0 - yes
        outcome_label = (
            best_market.get("groupItemTitle") or
            best_market.get("question", "?")[:40]
        )
        explanation = (
            f"The {len(yes_data)} outcomes in this event sum to only {prob_sum*100:.0f}¢ "
            f"(should be 100¢) — a {deviation*100:.0f}¢ underpricing. "
            f"The most underpriced outcome is \"{outcome_label}\" at {yes*100:.0f}¢. "
            f"Buying YES gives you exposure at a discount to fair value."
        )
        mkt = best_market

    bet  = _bet_from_confidence_and_edge(confidence, deviation * 100)
    risk = _liquidity_risk_note(total_liq)
    risk = (risk + " " if risk else "") + (
        "Mispricing in prediction markets can persist if liquidity is fragmented — "
        "check that the specific outcome you're trading has enough depth."
    )

    return [Alert(
        market_id=event.get("id", ""),
        market_question=event.get("title", "Unknown Event"),
        market_slug=mkt.get("slug", event_slug),
        event_slug=event_slug,
        signal_type="mispricing",
        yes_price=yes,
        no_price=no,
        current_odds=_odds_str(yes, no),
        action=action,
        confidence=confidence,
        bet_size=bet,
        explanation=explanation,
        risk_note=risk,
        details={
            "probability_sum": prob_sum,
            "deviation":       deviation,
            "num_outcomes":    len(yes_data),
            "total_liquidity": total_liq,
        },
    )]


# ── Aggregate runner ─────────────────────────────────────────────────────────

def run_all_detectors(events: list[dict]) -> list[Alert]:
    """Run every detector across all events and markets. Returns deduplicated alerts."""
    alerts: list[Alert] = []
    seen:   set[str]    = set()

    for event in events:
        event_slug = event.get("slug", "")

        for alert in detect_mispricing(event):
            if alert.unique_key not in seen:
                seen.add(alert.unique_key)
                alerts.append(alert)

        for market in event.get("markets", []):
            if not market.get("active") or market.get("closed"):
                continue
            if not market.get("enableOrderBook"):
                continue

            for detector in (
                detect_odds_shift,
                detect_volume_spike,
                detect_closing_soon,
                detect_new_market,
            ):
                for alert in detector(market, event_slug):
                    if alert.unique_key not in seen:
                        seen.add(alert.unique_key)
                        alerts.append(alert)

    logger.info("Detectors produced %d alerts this cycle.", len(alerts))
    return alerts
