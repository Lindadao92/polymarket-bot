"""
telegram_alerts.py — Send formatted opportunity alerts to Telegram.

Only alerts that pass the quality filter (MIN_CONFIDENCE + ALLOWED_ACTIONS
from config.py) are ever sent.  By default this means only HIGH-confidence
BUY YES or BUY NO signals reach Linda's Telegram.

Message format:

  🟢 BUY YES  |  🔥 Confidence: HIGH  |  Bet: MEDIUM ($20–50)
  ⚖️ Potential Mispricing
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

import telegram
from telegram.constants import ParseMode

import config
from detectors import Alert, ACTION_EMOJI, CONFIDENCE_EMOJI

logger = logging.getLogger(__name__)

# ── Confidence ordering (higher index = higher confidence) ────────────────────
_CONFIDENCE_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

# ── Cooldown state ────────────────────────────────────────────────────────────
_cooldowns: dict[str, float] = {}


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


# ── Quality filter ────────────────────────────────────────────────────────────

def _passes_quality_filter(alert: Alert) -> bool:
    """
    Return True only if the alert meets both the minimum confidence level
    and is one of the allowed action types.

    Controlled by config.MIN_CONFIDENCE and config.ALLOWED_ACTIONS.
    Default: HIGH confidence + BUY YES or BUY NO only.
    """
    # Check confidence level
    min_rank = _CONFIDENCE_RANK.get(config.MIN_CONFIDENCE.upper(), 2)
    alert_rank = _CONFIDENCE_RANK.get(alert.confidence.upper(), 0)
    if alert_rank < min_rank:
        return False

    # Check action type
    allowed = {a.strip().upper() for a in config.ALLOWED_ACTIONS.split(",")}
    if alert.action.upper() not in allowed:
        return False

    return True


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

def format_alert_html(alert: Alert) -> str:
    """Build a rich HTML message for a single Alert."""
    action_emoji     = ACTION_EMOJI.get(alert.action, "⚪")
    confidence_emoji = CONFIDENCE_EMOJI.get(alert.confidence, "📌")
    signal_label     = SIGNAL_LABELS.get(alert.signal_type, alert.signal_type)

    header = (
        f"{action_emoji} <b>{_esc(alert.action)}</b>  |  "
        f"{confidence_emoji} Confidence: <b>{_esc(alert.confidence)}</b>  |  "
        f"Bet: <b>{_esc(alert.bet_size)}</b>"
    )

    tag         = f"<i>{signal_label}</i>"
    market_line = f"📋 <b>Market:</b> {_esc(_trunc(alert.market_question, 120))}"

    odds = _esc(alert.current_odds)
    if len(odds) > 300:
        odds = odds[:297] + "…"
    odds_line = f"💰 <b>Odds:</b> {odds}"

    edge = alert.edge_pct
    edge_line = f"   <i>Estimated edge: ~{edge:.0f}%</i>" if edge >= 3 else ""

    reason = _esc(_trunc(alert.explanation, 500))
    why_block = f"💡 <b>Why this is an opportunity:</b>\n{reason}"

    risk_block = ""
    if alert.risk_note:
        risk_text  = _esc(_trunc(alert.risk_note, 300))
        risk_block = f"\n⚠️ <b>Risk:</b> {risk_text}"

    link = f'🔗 <a href="{alert.market_url}">View on Polymarket</a>'

    parts = [header, tag, "─" * 32, market_line, odds_line]
    if edge_line:
        parts.append(edge_line)
    parts += ["", why_block]
    if risk_block:
        parts.append(risk_block)
    parts += ["", link]

    return "\n".join(parts)


# ── Sending logic ─────────────────────────────────────────────────────────────

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


def send_alerts(alerts: list[Alert]) -> int:
    """
    Filter alerts by quality, then send those that pass and aren't on cooldown.
    Returns the count of alerts actually sent.
    """
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured — printing to console.")
        for a in alerts:
            if _passes_quality_filter(a):
                _print_console(a)
        return 0

    # Apply quality filter first
    qualified = [a for a in alerts if _passes_quality_filter(a)]
    skipped_quality = len(alerts) - len(qualified)

    # Then apply cooldown filter
    actionable = [a for a in qualified if not _is_on_cooldown(a)]
    skipped_cooldown = len(qualified) - len(actionable)

    logger.info(
        "Alert filter: %d total → %d pass quality (HIGH+BUY) → %d not on cooldown → sending.",
        len(alerts), len(qualified), len(actionable),
    )
    if skipped_quality:
        logger.debug("  Skipped %d alerts (LOW/MEDIUM confidence or WATCH/SKIP action).",
                     skipped_quality)
    if skipped_cooldown:
        logger.debug("  Skipped %d alerts (cooldown active).", skipped_cooldown)

    if not actionable:
        return 0

    bot  = telegram.Bot(token=config.TELEGRAM_BOT_TOKEN)
    sent = 0
    loop = asyncio.new_event_loop()
    try:
        for alert in actionable:
            html = format_alert_html(alert)
            ok   = loop.run_until_complete(_send_async(bot, html))
            if ok:
                _record_sent(alert)
                sent += 1
                time.sleep(0.5)
    finally:
        loop.close()

    _cleanup_cooldowns()
    return sent


def send_startup_message() -> None:
    """Notify Linda that the bot is online and show active filter settings."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.info("Telegram not configured — skipping startup message.")
        return

    allowed_actions = config.ALLOWED_ACTIONS or "BUY YES,BUY NO"
    min_conf        = config.MIN_CONFIDENCE or "HIGH"

    bot  = telegram.Bot(token=config.TELEGRAM_BOT_TOKEN)
    text = (
        "<b>🤖 Polymarket Alert Bot — Online</b>\n\n"
        f"Polling every <b>{config.POLL_INTERVAL_SECONDS}s</b>\n\n"
        "<b>🔍 Active quality filter:</b>\n"
        f"  • Minimum confidence: <b>{min_conf}</b>\n"
        f"  • Allowed actions: <b>{allowed_actions}</b>\n"
        f"  • You will only receive <b>HIGH confidence BUY YES / BUY NO</b> alerts.\n\n"
        "<b>Detection thresholds:</b>\n"
        f"  • Odds shift: {config.ODDS_SHIFT_THRESHOLD*100:.0f}pp in 24h\n"
        f"  • Volume spike: {config.VOLUME_SPIKE_MULTIPLIER:.1f}× daily avg\n"
        f"  • Closing soon: within {config.CLOSING_SOON_HOURS}h\n"
        f"  • New markets: created within {config.NEW_MARKET_HOURS}h\n"
        f"  • Mispricing: ≥{config.MISPRICE_SUM_DEVIATION*100:.0f}pp deviation\n\n"
        f"Topic filter: <i>{'all markets' if not config.TOPIC_KEYWORDS else config.TOPIC_KEYWORDS}</i>\n"
        f"Alert cooldown: {config.ALERT_COOLDOWN_SECONDS // 60} minutes per market\n\n"
        "<i>To adjust filters, update MIN_CONFIDENCE and ALLOWED_ACTIONS in your Railway environment variables.</i>"
    )
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_send_async(bot, text))
    finally:
        loop.close()


def send_error_message(error_text: str) -> None:
    """Send an error notification."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return
    bot  = telegram.Bot(token=config.TELEGRAM_BOT_TOKEN)
    text = f"<b>⚠️ Polymarket Bot Error</b>\n\n<code>{_esc(error_text[-600:])}</code>"
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_send_async(bot, text))
    finally:
        loop.close()


# ── Console fallback ──────────────────────────────────────────────────────────

def _print_console(alert: Alert) -> None:
    action_emoji = ACTION_EMOJI.get(alert.action, "⚪")
    print("\n" + "═" * 65)
    print(f"  {action_emoji} {alert.action}  |  Confidence: {alert.confidence}  |  Bet: {alert.bet_size}")
    print(f"  Signal: {SIGNAL_LABELS.get(alert.signal_type, alert.signal_type)}")
    print("  " + "─" * 61)
    print(f"  Market:  {alert.market_question}")
    print(f"  Odds:    {alert.current_odds}  (edge ~{alert.edge_pct:.0f}%)")
    print(f"  Why:     {alert.explanation}")
    if alert.risk_note:
        print(f"  Risk:    {alert.risk_note}")
    print(f"  Link:    {alert.market_url}")
    print("═" * 65)
