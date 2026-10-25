import asyncio
import re
from collections import OrderedDict
from html import escape
from typing import Any

import requests
from telegram import (
    BotCommand,
    CallbackQuery,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src import bot_ui
from src.config.config import app_settings
from src.config.logging_config import get_logger, setup_logging
from src.places_api import (
    NEAR_RADIUS,
    USER_AGENT,
    PlacesUnavailable,
    describe_error,
    get_nearby_food,
    get_nearby_places,
)
from src.utils import generate_answer

logger = get_logger(__name__)

# Per-user state for button callbacks, in memory only. The least recently used users are
# dropped so the process does not grow without bound.
MAX_USERS = 200
user_contexts: OrderedDict[int, dict[str, Any]] = OrderedDict()


def _remember(user_id: int, user_context: dict[str, Any]) -> None:
    user_contexts[user_id] = user_context
    user_contexts.move_to_end(user_id)
    while len(user_contexts) > MAX_USERS:
        user_contexts.popitem(last=False)


async def send_welcome(update: Update, context: CallbackContext):
    logger.info("Starting a conversation...")
    lang = _detect_user_language(update)
    label = "📍 Отправить геолокацию" if lang == "ru" else "📍 Send Location"
    button = KeyboardButton(label, request_location=True)
    reply_markup = ReplyKeyboardMarkup([[button]], one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(
        bot_ui.welcome(lang), reply_markup=reply_markup, parse_mode=ParseMode.HTML
    )


async def health_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id in app_settings.ADMIN_USER_IDS:
        await context.bot.send_message(chat_id=user_id, text="Bot is live and running!")
        logger.info(f"User {user_id} checked bot's status via /health command.")
    else:
        logger.warning(f"Unauthorized /health command from user {user_id}")


async def location(update: Update, context: CallbackContext) -> None:
    """Handle a shared location: search sights and show the category overview."""
    user_location = update.message.location
    lat = user_location.latitude
    lon = user_location.longitude
    user_id = update.message.from_user.id

    logger.info(f"Received location from user {user_id}")
    if app_settings.DEBUG:
        # Dev only: rounded to ~100 m, enough to reproduce a search; never logged in prod
        logger.info(f"DEBUG location: {lat:.3f}, {lon:.3f}")

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    user_lang = _detect_user_language(update)
    try:
        location_name, nearby = await asyncio.gather(
            asyncio.to_thread(_get_location_name, lat, lon),
            get_nearby_places(lat, lon, lang=user_lang),
        )
    except PlacesUnavailable:
        logger.warning("Place search unavailable")
        await update.message.reply_text(bot_ui.text("places_unavailable", user_lang))
        return
    logger.info(f"Found places: {[(cat, len(p)) for cat, p in nearby.by_category.items()]}")

    # The context is kept even when no sights were found: the food button still needs it.
    _remember(
        user_id,
        {
            "lat": lat,
            "lon": lon,
            "location": location_name,
            "nearby": nearby,
            "language": user_lang,
        },
    )
    text, keyboard = _overview(user_contexts[user_id])
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


def _overview(user_context: dict[str, Any]) -> bot_ui.Screen:
    nearby = user_context["nearby"]
    return bot_ui.overview(
        nearby.by_category,
        user_context["location"],
        user_context["language"],
        nearby.radius,
        nearby.expanded,
        NEAR_RADIUS,
    )


def _detect_user_language(update: Update) -> str:
    """Return 'ru' or 'en' based on the user's Telegram language or a Cyrillic first name."""
    user = update.effective_user
    if user and user.language_code:
        lang_code = user.language_code.lower()
        if lang_code.startswith("ru"):
            return "ru"
        if lang_code.startswith("en"):
            return "en"
    if user and user.first_name and re.search(r"[а-яё]", user.first_name.lower()):
        return "ru"
    return "en"


async def _show(query: CallbackQuery, screen: bot_ui.Screen) -> None:
    text, keyboard = screen
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


def _to_int(value: str) -> int | None:
    return int(value) if value.isdecimal() else None


async def handle_callback_query(update: Update, context: CallbackContext):
    """Route inline button presses; the screens themselves are built in bot_ui."""
    query = update.callback_query
    await query.answer()
    if query.data == "noop":
        return

    user_context = user_contexts.get(query.from_user.id)
    if user_context is None:
        await query.edit_message_text(bot_ui.text("expired", _detect_user_language(update)))
        return
    user_contexts.move_to_end(query.from_user.id)
    lang = user_context["language"]
    by_category = user_context["nearby"].by_category

    action, _, rest = query.data.partition(":")
    scope, _, number = rest.rpartition(":")
    number = _to_int(number)
    valid_scope = scope == bot_ui.ALL or scope in bot_ui.SIGHT_CATEGORIES

    if action == "cat" and valid_scope and number is not None:
        places = bot_ui.sights_in_scope(by_category, scope)
        await _show(query, bot_ui.place_list(scope, places, number, lang))
    elif action == "pl" and valid_scope and number is not None:
        places = bot_ui.sights_in_scope(by_category, scope)
        if number < len(places):
            card = bot_ui.place_card(places[number], scope, number, lang, user_context["location"])
            await _show(query, card)
    elif query.data == "food":
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        await _show(query, await _food_screen(user_context))
    elif query.data == "back":
        await _show(query, _overview(user_context))
    else:
        logger.warning(f"Ignored unexpected callback action: {action[:20]}")


async def _food_screen(user_context: dict[str, Any]) -> bot_ui.Screen:
    lang = user_context["language"]
    if "food" not in user_context:
        try:
            user_context["food"] = await get_nearby_food(
                user_context["lat"], user_context["lon"], lang=lang
            )
        except PlacesUnavailable:
            return bot_ui.message_with_back(bot_ui.text("food_unavailable", lang), lang)
    return bot_ui.food_screen(user_context["food"], lang, user_context["location"])


async def handle_text_message(update: Update, context: CallbackContext):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    llm_response = generate_answer(update.message.text)
    await update.message.reply_text(escape(llm_response), parse_mode=ParseMode.HTML)


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled error while processing an update", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("⚠️ Something went wrong. Please try again.")


def _get_location_name(lat: float, lon: float) -> str:
    """Return "City, Country" via Nominatim reverse geocoding, or coordinates as a fallback."""
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json", "addressdetails": 1},
            timeout=8,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        address = response.json().get("address", {})
        city = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("municipality")
        )
        country = address.get("country")
        if city and country:
            return f"{city}, {country}"
    except Exception as e:
        logger.warning(f"Nominatim reverse geocoding failed: {describe_error(e)}")

    return f"Coordinates: {lat:.4f}, {lon:.4f}"


async def register_handlers(app: Application):
    """Register all command and message handlers."""
    app.add_handler(CommandHandler("start", send_welcome))
    app.add_handler(CommandHandler("health", health_check))
    # Live location updates arrive as edited messages; they are not handled yet.
    app.add_handler(MessageHandler(filters.LOCATION & ~filters.UpdateType.EDITED_MESSAGE, location))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    app.add_error_handler(handle_error)

    await app.bot.set_my_commands([BotCommand("start", "Start interacting with the bot")])
    logger.info("Handlers registered")


async def main():
    """Main entry point for the bot."""
    bot_app = ApplicationBuilder().token(app_settings.TELEGRAM_BOT_TOKEN).build()
    await bot_app.initialize()
    await register_handlers(bot_app)

    try:
        logger.info("Starting the bot...")
        await bot_app.start()
        await bot_app.updater.start_polling()
        await asyncio.Future()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
    finally:
        logger.info("Shutting down the bot...")


if __name__ == "__main__":
    setup_logging(app_settings.LOG_LEVEL)
    asyncio.run(main())
