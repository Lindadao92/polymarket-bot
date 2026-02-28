"""
telegram_alerts.py — Send formatted opportunity alerts to Telegram.

Daily cap logic:
  - The bot tracks how many alerts have been sent today (UTC calendar day).
  - Once MAX_ALERTS_PER_DAY alerts have been sent, no more are sent until
    UTC midnight resets the counter.
  - Within each scan cycle, qualifying alerts are ranked by edge strength
    so the strongest opportunities always get the limited slots.
  - A "daily quota reached" message is sent once when the cap is hit.

Quality filter (MIN_CONFIDENCE + ALLOWED_ACTIONS) is applied first, then
the daily cap is applied to whatever remains.

Message format:

  🟢 BUY YES  |  🔥 Confidence: HIGH  |  Bet: MEDIUM ($20–50)
  ⚖️ Potential Mispricing  |  Alert 3 of 5 today
  ────────────────────────────────
  📋 Market: Will X happen by March?
  💰 Odds: YES 35¢ / NO 65¢
     Estimated edge: ~15%

  💡 Why this is an opportunity:
  Odds haven't adjusted yet. Buy YES before it moves up.

  ⚠️ Risk: Low liquidity — keep bets small.

  🔗 View on Polymarket
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import telegram
from telegram.constants import ParseMode

import config
from detectors import Alert, ACTION_EMOJI, CONFIDENCE_EMOJI

logger = logging.getLogger(__name__)

# ── Confidence ordering ───────────────────────────────────────────────────────
_CONFIDENCE_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

# ── Per-run state (persists across scan cycles within the same process) ───────
_cooldowns:       dict[str, float] = {}   # unique_key → last sent timestamp
_daily_sent:      int  = 0                # alerts sent today
_daily_date:      str  = ""               # "YYYY-MM-DD" of current day (UTC)
_quota_notified:  bool = False            # have we sent the "quota reached" msg?


# ── Daily cap helpers ─────────────────────────────────────────────────────────

def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _reset_daily_counter_if_needed() -> None:
    """Reset the daily counter at UTC midnight."""
    global _daily_sent, _daily_date, _quota_notified
    today = _today_utc()
    if _daily_date != today:
        if _daily_date:
            logger.info("New UTC day (%s) — daily alert counter reset.", today)
        _daily_date     = today
        _daily_sent     = 0
        _quota_notified = False


def daily_slots_remaining() -> int:
    """How many more alerts can be sent today (0 = cap reached)."""
    _reset_daily_counter_if_needed()
    if config.MAX_ALERTS_PER_DAY <= 0:
        return 999_999   # cap disabled
    return max(0, config.MAX_ALERTS_PER_DAY - _daily_sent)


def daily_cap_reached() -> bool:
    return daily_slots_remaining() == 0


# ── Quality filter ────────────────────────────────────────────────────────────

def _passes_quality_filter(alert: Alert) -> bool:
    """Return True only if the alert meets MIN_CONFIDENCE and ALLOWED_ACTIONS."""
    min_rank   = _CONFIDENCE_RANK.get(config.MIN_CONFIDENCE.upper(), 2)
    alert_rank = _CONFIDENCE_RANK.get(alert.confidence.upper(), 0)
    if alert_rank < min_rank:
        return False
    allowed = {a.strip().upper() for a in config.ALLOWED_ACTIONS.split(",")}
    return alert.action.upper() in allowed


# ── Ranking ───────────────────────────────────────────────────────────────────

def _rank_score(alert: Alert) -> float:
    """
    Composite score used to rank alerts when the daily cap is limited.

    Factors (all normalised to roughly 0-100):
      1. Edge percentage (primary driver)
      2. Confidence tier bonus  (HIGH=20, MEDIUM=10, LOW=0)
      3. Urgency bonus for closing-soon markets (up to +15)
    """
    edge = alert.edge_pct                                         # 0-100+
    conf_bonus = {"HIGH": 20, "MEDIUM": 10, "LOW": 0}.get(alert.confidence, 0)

    urgency_bonus = 0.0
    if alert.signal_type == "closing_soon":
        hours = alert.details.get("hours_until_close", 48)
        urgency_bonus = max(0, 15 - hours / 3)   # peaks at 15 for <1h remaining

    return edge + conf_bonus + urgency_bonus


# ── Cooldown helpers ──────────────────────────────────────────────────────────

def _is_on_cooldown(alert: Alert) -> bool:
    return (time.time() - _cooldowns.get(alert.unique_key, 0)) < config.ALERT_COOLDOWN_SECONDS


def _record_sent(alert: Alert) -> None:
    _cooldowns[alert.unique_key] = time.time()


def _cleanup_cooldowns() -> None:
    now = time.time()
    expired = [k for k, v in _cooldowns.items()
               if (now - v) > config.ALERT_COOLDOWN_SECONDS * 2]
    for k in expired:
        del _cooldowns[k]


# ── Signal type display names ─────────────────────────────────────────────────
SIGNAL_LABELS = {
    "odds_shift":   "📊 Sudden Odds Shift",
    "volume_spike": "📈 Volume Spike",
    "closing_soon": "⏰ Closing Soon",
    "new_market":   "🆕 New Market",
    "mispricing":   "⚖️ Potential Mispricing",
}


# ── HTML helpers ──────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _trunc(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[:max_len - 1] + "…"


# ── Message formatter ─────────────────────────────────────────────────────────

def format_alert_html(alert: Alert, alert_number: int = 0) -> str:
    """
    Build a rich HTML message for a single Alert.

    alert_number: if > 0, shown as "Alert N of MAX today" in the subheader.
    """
    action_emoji     = ACTION_EMOJI.get(alert.action, "⚪")
    confidence_emoji = CONFIDENCE_EMOJI.get(alert.confidence, "📌")
    signal_label     = SIGNAL_LABELS.get(alert.signal_type, alert.signal_type)

    # ── Header ────────────────────────────────────────────────────────────────
    header = (
        f"{action_emoji} <b>{_esc(alert.action)}</b>  |  "
        f"{confidence_emoji} Confidence: <b>{_esc(alert.confidence)}</b>  |  "
        f"Bet: <b>{_esc(alert.bet_size)}</b>"
    )

    # ── Signal type + daily counter ───────────────────────────────────────────
    if alert_number > 0 and config.MAX_ALERTS_PER_DAY > 0:
        tag = (f"<i>{signal_label}</i>  |  "
               f"<i>Alert {alert_number} of {config.MAX_ALERTS_PER_DAY} today</i>")
    else:
        tag = f"<i>{signal_label}</i>"

    # ── Market + odds ─────────────────────────────────────────────────────────
    market_line = f"📋 <b>Market:</b> {_esc(_trunc(alert.market_question, 120))}"

    odds = _esc(alert.current_odds)
    if len(odds) > 300:
        odds = odds[:297] + "…"
    odds_line = f"💰 <b>Odds:</b> {odds}"

    edge      = alert.edge_pct
    edge_line = f"   <i>Estimated edge: ~{edge:.0f}%</i>" if edge >= 3 else ""

    # ── Explanation ───────────────────────────────────────────────────────────
    reason    = _esc(_trunc(alert.explanation, 500))
    why_block = f"💡 <b>Why this is an opportunity:</b>\n{reason}"

    # ── Risk note ─────────────────────────────────────────────────────────────
    risk_block = ""
    if alert.risk_note:
        risk_text  = _esc(_trunc(alert.risk_note, 300))
        risk_block = f"\n⚠️ <b>Risk:</b> {risk_text}"

    # ── Link ──────────────────────────────────────────────────────────────────
    link = f'🔗 <a href="{alert.market_url}">View on Polymarket</a>'

    parts = [header, tag, "─" * 32, market_line, odds_line]
    if edge_line:
        parts.append(edge_line)
    parts += ["", why_block]
    if risk_block:
        parts.append(risk_block)
    parts += ["", link]

    return "\n".join(parts)


# ── Async send helper ─────────────────────────────────────────────────────────

async def _send_async(bot: telegram.Bot, text: str) -> bool:
    try:
        await bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return True
    except telegram.error.TelegramError as exc:
        logger.error("Telegram send failed: %s", exc)
        return False


def _run(coro):
    """Run a coroutine in a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Main send function ────────────────────────────────────────────────────────

def send_alerts(alerts: list[Alert]) -> int:
    """
    Filter, rank, cap, and send alerts.

    Pipeline:
      1. Apply quality filter (MIN_CONFIDENCE + ALLOWED_ACTIONS).
      2. Apply per-market cooldown.
      3. Rank survivors by composite score (edge + confidence + urgency).
      4. Take only as many as the daily cap allows.
      5. Send them, recording each one sent.

    Returns the count of alerts actually sent.
    """
    global _daily_sent, _quota_notified

    _reset_daily_counter_if_needed()

    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured — printing to console.")
        qualified = [a for a in alerts if _passes_quality_filter(a)]
        for a in qualified:
            _print_console(a)
        return 0

    # ── Step 1: quality filter ────────────────────────────────────────────────
    qualified = [a for a in alerts if _passes_quality_filter(a)]
    skipped_q = len(alerts) - len(qualified)

    # ── Step 2: cooldown filter ───────────────────────────────────────────────
    fresh = [a for a in qualified if not _is_on_cooldown(a)]
    skipped_c = len(qualified) - len(fresh)

    # ── Step 3: rank by composite score ──────────────────────────────────────
    ranked = sorted(fresh, key=_rank_score, reverse=True)

    # ── Step 4: daily cap ─────────────────────────────────────────────────────
    slots = daily_slots_remaining()

    logger.info(
        "Alert pipeline: %d raw → %d quality → %d fresh → %d ranked | "
        "%d daily slot(s) remaining.",
        len(alerts), len(qualified), len(fresh), len(ranked), slots,
    )

    if slots == 0:
        if not _quota_notified:
            _quota_notified = True
            logger.info("Daily cap of %d reached — no more alerts today.", config.MAX_ALERTS_PER_DAY)
            _run(_send_async(
                telegram.Bot(token=config.TELEGRAM_BOT_TOKEN),
                (
                    f"🛑 <b>Daily alert quota reached</b>\n\n"
                    f"The bot has sent its maximum of <b>{config.MAX_ALERTS_PER_DAY} alerts</b> "
                    f"for today. It will keep scanning but won't send any more messages "
                    f"until <b>UTC midnight</b> resets the counter.\n\n"
                    f"<i>To increase the daily limit, change <code>MAX_ALERTS_PER_DAY</code> "
                    f"in your Railway environment variables.</i>"
                ),
            ))
        return 0

    to_send = ranked[:slots]

    # ── Step 5: send ──────────────────────────────────────────────────────────
    bot  = telegram.Bot(token=config.TELEGRAM_BOT_TOKEN)
    sent = 0
    for alert in to_send:
        alert_number = _daily_sent + 1
        html = format_alert_html(alert, alert_number=alert_number)
        ok   = _run(_send_async(bot, html))
        if ok:
            _record_sent(alert)
            _daily_sent += 1
            sent += 1
            logger.info(
                "  ✓ Sent alert %d/%d today: [%s] %s | score=%.1f",
                _daily_sent, config.MAX_ALERTS_PER_DAY,
                alert.signal_type, alert.market_question[:55],
                _rank_score(alert),
            )
            time.sleep(0.5)

        # Re-check cap after each send (in case another thread incremented it)
        if daily_cap_reached():
            break

    _cleanup_cooldowns()
    return sent


# ── Startup / error messages ──────────────────────────────────────────────────

def send_startup_message() -> None:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.info("Telegram not configured — skipping startup message.")
        return

    cap_text = (
        f"<b>{config.MAX_ALERTS_PER_DAY} alerts/day max</b> "
        f"(resets at UTC midnight)"
        if config.MAX_ALERTS_PER_DAY > 0
        else "No daily cap (unlimited)"
    )

    text = (
        "<b>🤖 Polymarket Alert Bot — Online</b>\n\n"
        f"Polling every <b>{config.POLL_INTERVAL_SECONDS}s</b>\n\n"
        "<b>🔍 Active filters:</b>\n"
        f"  • Minimum confidence: <b>{config.MIN_CONFIDENCE}</b>\n"
        f"  • Allowed actions: <b>{config.ALLOWED_ACTIONS}</b>\n"
        f"  • Daily alert cap: {cap_text}\n\n"
        "<b>Detection thresholds:</b>\n"
        f"  • Odds shift: {config.ODDS_SHIFT_THRESHOLD*100:.0f}pp in 24h\n"
        f"  • Volume spike: {config.VOLUME_SPIKE_MULTIPLIER:.1f}× daily avg\n"
        f"  • Closing soon: within {config.CLOSING_SOON_HOURS}h\n"
        f"  • New markets: created within {config.NEW_MARKET_HOURS}h\n"
        f"  • Mispricing: ≥{config.MISPRICE_SUM_DEVIATION*100:.0f}pp deviation\n\n"
        f"Topic filter: <i>{'all markets' if not config.TOPIC_KEYWORDS else config.TOPIC_KEYWORDS}</i>\n"
        f"Alert cooldown: {config.ALERT_COOLDOWN_SECONDS // 60} min per market\n\n"
        "<i>Alerts are ranked by edge strength — you'll only receive the best opportunities of the day.</i>"
    )
    _run(_send_async(telegram.Bot(token=config.TELEGRAM_BOT_TOKEN), text))


def send_error_message(error_text: str) -> None:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return
    text = f"<b>⚠️ Polymarket Bot Error</b>\n\n<code>{_esc(error_text[-600:])}</code>"
    _run(_send_async(telegram.Bot(token=config.TELEGRAM_BOT_TOKEN), text))


# ── Console fallback ──────────────────────────────────────────────────────────

def _print_console(alert: Alert) -> None:
    action_emoji = ACTION_EMOJI.get(alert.action, "⚪")
    print("\n" + "═" * 65)
    print(f"  {action_emoji} {alert.action}  |  Confidence: {alert.confidence}  |  Bet: {alert.bet_size}")
    print(f"  Signal: {SIGNAL_LABELS.get(alert.signal_type, alert.signal_type)}")
    print(f"  Score:  {_rank_score(alert):.1f}")
    print("  " + "─" * 61)
    print(f"  Market:  {alert.market_question}")
    print(f"  Odds:    {alert.current_odds}  (edge ~{alert.edge_pct:.0f}%)")
    print(f"  Why:     {alert.explanation}")
    if alert.risk_note:
        print(f"  Risk:    {alert.risk_note}")
    print(f"  Link:    {alert.market_url}")
    print("═" * 65)
