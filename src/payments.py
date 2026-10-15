"""Premium subscriptions paid for with Telegram Stars (XTR).

Telegram Stars is Telegram's own in-app currency (Bot API 7.4+,
https://core.telegram.org/bots/payments-stars). It needs no external payment
provider or ``provider_token`` -- ``currency="XTR"`` is enough -- which is
why it is used here: the bot can sell premium without the owner having to
set up a merchant account anywhere.

This module wires together four Bot API pieces:
  - ``send_invoice`` (currency="XTR") to show the payment sheet.
  - ``PreCheckoutQueryHandler`` -> ``answer_pre_checkout_query`` to confirm
    the order right before Telegram charges the user.
  - ``MessageHandler(filters.SUCCESSFUL_PAYMENT)`` to grant premium once the
    charge completes.
  - ``refund_star_payment`` for the admin-only ``/refund`` command.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import closing
from datetime import datetime

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from database.databases import usrdatabase
from src.config import get_config
from src.messages import NO_PREVIEW

logger = logging.getLogger(__name__)

STARS_CURRENCY = "XTR"


# =============================================================================
# Helpers
# =============================================================================

def format_date(iso_value: str | None) -> str:
    if not iso_value:
        return "forever"

    try:
        return datetime.fromisoformat(iso_value).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso_value


def _status_text(info: dict) -> str:
    kind = info["type_user"].capitalize()

    if info["premium_until"]:
        expiry = f"Active until <b>{format_date(info['premium_until'])}</b>."
    else:
        expiry = "No expiry."

    return (
        f"⭐ <b>You already have {kind} access.</b>\n\n"
        f"{expiry}\n\n"
        "Want to extend it? Pick another plan below."
    )


def _plan_keyboard(plans) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                f"{plan.label} — ⭐ {plan.stars}",
                callback_data=f"buy:{plan.code}",
            )
        ]
        for plan in plans
    ]

    return InlineKeyboardMarkup(rows)


# =============================================================================
# /premium
# =============================================================================

async def premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = get_config()
    user = update.effective_user

    with closing(usrdatabase()) as db:
        db.add_user(user.id, user.username or user.first_name or str(user.id))
        info = db.get_user(user.id)

    if info and info["unlimited"]:
        text = _status_text(info)
    else:
        perks = "unlimited daily downloads"

        if config.uses_local_server:
            perks += f", plus files up to {config.effective_premium_max_mb():.0f} MB"

        text = (
            f"⭐ <b>Premium</b>\n\n{perks.capitalize()}.\n\n"
            "Pay with Telegram Stars -- no card, no external account:"
        )

    await update.effective_message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=_plan_keyboard(config.plans),
        link_preview_options=NO_PREVIEW,
    )


async def buy_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle a plan button press: send the Stars invoice."""
    query = update.callback_query
    await query.answer()

    code = (query.data or "").split(":", 1)[-1]
    config = get_config()
    plan = config.plan(code)

    if plan is None:
        await query.message.reply_text("That plan is no longer available, use /premium again.")
        return

    description = "Unlimited daily downloads"

    if config.uses_local_server:
        description += f" and files up to {config.effective_premium_max_mb():.0f} MB"

    description += f", for {plan.label}."

    try:
        await context.bot.send_invoice(
            chat_id=query.message.chat_id,
            title=f"Premium -- {plan.label}",
            description=description,
            payload=plan.code,
            provider_token="",  # empty string -> Telegram Stars, no external provider
            currency=STARS_CURRENCY,
            # Stars have no decimal subunits, so the "amount" is the star count.
            prices=[LabeledPrice(plan.label, plan.stars)],
        )
    except TelegramError:
        logger.exception("Could not send Stars invoice for plan %s", plan.code)
        await query.message.reply_text(
            "⚠️ Could not start the payment. Please try /premium again in a moment."
        )


# =============================================================================
# Checkout
# =============================================================================

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Answer within the ~10s Telegram allows, right before the charge happens."""
    query = update.pre_checkout_query
    config = get_config()
    plan = config.plan(query.invoice_payload)

    if plan is None or plan.stars != query.total_amount or query.currency != STARS_CURRENCY:
        logger.warning(
            "Rejecting pre-checkout: payload=%r amount=%r currency=%r",
            query.invoice_payload, query.total_amount, query.currency,
        )
        await query.answer(
            ok=False,
            error_message="This plan is no longer available. Please use /premium again.",
        )
        return

    await query.answer(ok=True)


async def successful_payment_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Grant premium once Telegram confirms the Stars charge went through."""
    message = update.effective_message
    payment = message.successful_payment
    user = update.effective_user
    config = get_config()

    plan = config.plan(payment.invoice_payload)

    if plan is None:
        # Should be unreachable (precheckout already validated the payload),
        # but if it ever happens the user has already paid -- never lose
        # that silently.
        logger.error(
            "successful_payment with an unrecognized plan code %r (charge %s, user %s)",
            payment.invoice_payload, payment.telegram_payment_charge_id, user.id,
        )
        await message.reply_text(
            "⚠️ Payment received, but the plan could not be matched. "
            "Please contact the bot owner with this payment id:\n"
            f"<code>{payment.telegram_payment_charge_id}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    def _grant() -> dict:
        with closing(usrdatabase()) as db:
            # Defense in depth: set_premium() is a no-op if the user has no
            # row yet, and in the current handler wiring that can't actually
            # happen (reaching a successful payment requires having opened
            # /premium first, which already calls add_user). Calling it here
            # too removes that implicit ordering dependency for free --
            # add_user() is a safe no-op for an existing user.
            db.add_user(user.id, user.username or user.first_name or str(user.id))

            is_new = db.record_payment(
                user.id,
                payment.telegram_payment_charge_id,
                plan.code,
                plan.stars,
                plan.days,
            )

            if is_new:
                db.set_premium(user.id, "premium", days=plan.days)

            return {"is_new": is_new, "info": db.get_user(user.id)}

    result = await asyncio.to_thread(_grant)

    if not result["is_new"]:
        # Telegram's delivery is at-least-once; this update was already
        # processed (premium already granted). Nothing else to do.
        logger.info(
            "Duplicate successful_payment ignored (charge %s)",
            payment.telegram_payment_charge_id,
        )
        return

    info = result["info"]

    await message.reply_text(
        "✅ <b>Payment received, thank you!</b>\n\n"
        f"Premium is active until <b>{format_date(info['premium_until'])}</b>.",
        parse_mode=ParseMode.HTML,
    )

    logger.info(
        "Granted premium to user %s: plan=%s stars=%s charge=%s",
        user.id, plan.code, plan.stars, payment.telegram_payment_charge_id,
    )


# =============================================================================
# Admin: /refund
# =============================================================================

async def refund_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``/refund <telegram_id>`` -- refund a user's most recent Stars payment.

    Admin-only; the caller (src/bot.py) is expected to have already checked
    the sender is in ``Config.admin_ids`` before routing here.
    """
    message = update.effective_message
    args = context.args or []

    if not args or not args[0].lstrip("-").isdigit():
        await message.reply_text("Usage: /refund <telegram_id>")
        return

    target_id = int(args[0])

    with closing(usrdatabase()) as db:
        payment = db.last_payment(target_id)

    if payment is None:
        await message.reply_text(f"No refundable payment found for user {target_id}.")
        return

    try:
        await context.bot.refund_star_payment(
            user_id=target_id,
            telegram_payment_charge_id=payment["charge_id"],
        )
    except TelegramError as error:
        logger.error("Refund failed for %s: %s", target_id, error)
        await message.reply_text(f"⚠️ Refund failed: {error}")
        return

    with closing(usrdatabase()) as db:
        db.mark_refunded(payment["charge_id"])
        db.revoke_premium(target_id)

    await message.reply_text(
        f"✅ Refunded {payment['stars']} ⭐ to user {target_id} "
        f"(plan {payment['plan_code']}) and revoked premium."
    )
