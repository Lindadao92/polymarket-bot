"""
telegram_alerts.py — Send formatted opportunity alerts to Telegram.

Message format (per alert):

  🟢 BUY YES  |  🔥 Confidence: HIGH  |  Bet: MEDIUM ($20–50)
  ─────────────────────────────────────────────────────────────
  📋 Market: Will X happen by March?
  💰 Odds: YES 35¢ / NO 65¢  |  Estimated edge: ~15%

  💡 Why this is an opportunity:
  News just broke that [reason]. Odds haven't adjusted yet. Buy YES before it moves up.

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
from detectors import Alert, ACTION_EMOJI, CONFIDENCE_EMOJI, Action, Confidence

logger = logging.getLogger(__name__)

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
    """Escape Telegram HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _trunc(text: str, max_len: int) -> str:
    """Truncate text to max_len characters, appending ellipsis if needed."""
    return text if len(text) <= max_len else text[:max_len - 1] + "…"


# ── Message formatter ─────────────────────────────────────────────────────────

def format_alert_html(alert: Alert) -> str:
    """
    Build a rich HTML message for a single Alert.

    Layout:
      Header line  — action badge, confidence badge, bet size
      Divider
      Market name
      Odds + estimated edge
      Blank line
      Plain-English explanation
      Risk note (if any)
      Polymarket link
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

    # ── Signal type tag ───────────────────────────────────────────────────────
    tag = f"<i>{signal_label}</i>"

    # ── Market + odds ─────────────────────────────────────────────────────────
    market_line = f"📋 <b>Market:</b> {_esc(_trunc(alert.market_question, 120))}"
    odds_line   = f"💰 <b>Odds:</b> {_esc(alert.current_odds)}"

    # Edge estimate (only show if meaningful)
    edge = alert.edge_pct
    edge_line = f"   <i>Estimated edge: ~{edge:.0f}%</i>" if edge >= 3 else ""

    # ── Explanation ───────────────────────────────────────────────────────────
    explanation = _esc(_trunc(alert.explanation, 500))
    why_block   = f"💡 <b>Why this is an opportunity:</b>\n{explanation}"

    # ── Risk note ─────────────────────────────────────────────────────────────
    risk_block = ""
    if alert.risk_note:
        risk_text = _esc(_trunc(alert.risk_note, 300))
        risk_block = f"\n⚠️ <b>Risk:</b> {risk_text}"

    # ── Link ──────────────────────────────────────────────────────────────────
    link = f'🔗 <a href="{alert.market_url}">View on Polymarket</a>'

    # ── Assemble ──────────────────────────────────────────────────────────────
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
    """Send a batch of alerts, respecting cooldowns. Returns count sent."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured — printing to console.")
        for a in alerts:
            _print_console(a)
        return 0

    actionable = [a for a in alerts if not _is_on_cooldown(a)]
    if not actionable:
        logger.debug("All %d alerts on cooldown.", len(alerts))
        return 0

    logger.info("Sending %d alerts (%d on cooldown).",
                len(actionable), len(alerts) - len(actionable))

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
    """Notify Linda that the bot is online."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.info("Telegram not configured — skipping startup message.")
        return

    bot  = telegram.Bot(token=config.TELEGRAM_BOT_TOKEN)
    text = (
        "<b>🤖 Polymarket Alert Bot — Online</b>\n\n"
        f"Polling every <b>{config.POLL_INTERVAL_SECONDS}s</b>\n\n"
        "<b>Detection thresholds:</b>\n"
        f"  • Odds shift: {config.ODDS_SHIFT_THRESHOLD*100:.0f}pp in 24h\n"
        f"  • Volume spike: {config.VOLUME_SPIKE_MULTIPLIER:.1f}× daily avg\n"
        f"  • Closing soon: within {config.CLOSING_SOON_HOURS}h\n"
        f"  • New markets: created within {config.NEW_MARKET_HOURS}h\n"
        f"  • Mispricing: ≥{config.MISPRICE_SUM_DEVIATION*100:.0f}pp deviation\n\n"
        "<b>Alert format:</b>\n"
        "  🟢 BUY YES / 🔴 BUY NO / 🟡 WATCH / ⚪ SKIP\n"
        "  🔥 HIGH / 📌 MEDIUM / 💭 LOW confidence\n"
        "  Bet size: SMALL / MEDIUM / LARGE\n\n"
        f"Topic filter: <i>{'all markets' if not config.TOPIC_KEYWORDS else config.TOPIC_KEYWORDS}</i>\n"
        f"Alert cooldown: {config.ALERT_COOLDOWN_SECONDS // 60} minutes per market"
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
