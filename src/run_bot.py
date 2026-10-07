import asyncio
import re
from html import escape
from typing import Any

import requests
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
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

from src.config.config import app_settings
from src.config.logging_config import get_logger, setup_logging
from src.places_api import get_nearby_places
from src.utils import generate_answer

logger = get_logger(__name__)

# Store user context for callback handling
user_contexts: dict[int, dict[str, Any]] = {}

AI_DISCLAIMER = (
    "\n\n⚠️ <i>Disclaimer:</i> This information is AI-generated. "
    "Please verify important details from official sources."
)

CATEGORY_INFO = {
    "history_culture": {"emoji": "🏛️", "name": "History & Culture", "name_ru": "История и культура"},
    "food_drinks": {"emoji": "🍽️", "name": "Food & Drinks", "name_ru": "Еда и напитки"},
    "shopping": {"emoji": "🛍️", "name": "Shopping", "name_ru": "Покупки"},
    "parks_nature": {"emoji": "🌳", "name": "Parks & Nature", "name_ru": "Парки и природа"},
    "entertainment": {"emoji": "🎭", "name": "Entertainment", "name_ru": "Развлечения"},
    "other": {"emoji": "📍", "name": "Other Places", "name_ru": "Другие места"},
}


async def send_welcome(update: Update, context: CallbackContext):
    logger.info("Starting a conversation...")
    greeting_text = (
        "🏛️ <b>Welcome to the History Around Me Bot!</b> 🌍\n\n"
        "I'm your AI-powered travel guide! Send your location to discover "
        "fascinating historical and cultural landmarks nearby.\n\n"
        "📍 Click the button below to share your current location."
    )

    button = KeyboardButton("📍 Send Location", request_location=True)
    reply_markup = ReplyKeyboardMarkup([[button]], one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(
        greeting_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
    )


async def health_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id in app_settings.ADMIN_USER_IDS:
        await context.bot.send_message(chat_id=user_id, text="Bot is live and running!")
        logger.info(f"User {user_id} checked bot's status via /health command.")
    else:
        logger.warning(f"Unauthorized /health command from user {user_id}")


async def location(update: Update, context: CallbackContext) -> None:
    """Handle location messages from users."""
    user_location = update.message.location
    lat = user_location.latitude
    lon = user_location.longitude
    user_id = update.message.from_user.id

    logger.info(f"Received location from user {user_id}")

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    location_name = _get_location_name_with_fallbacks(lat, lon)
    user_lang = _detect_user_language(update)
    logger.info(f"Detected user language: {user_lang}")

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    categorized_places = get_nearby_places(lat, lon, radius=10000, lang=user_lang)
    logger.info(
        f"Found categorized places: {[(cat, len(p)) for cat, p in categorized_places.items()]}"
    )

    if not categorized_places:
        await update.message.reply_text(
            "🔍 Unfortunately, I couldn't find any notable landmarks or cultural sites nearby. "
            "Try moving to a different location or check back later!"
        )
        return

    user_contexts[user_id] = {
        "location": location_name,
        "categorized_places": categorized_places,
        "language": user_lang,
    }

    overview_response = generate_category_overview(categorized_places, location_name, user_lang)
    await update.message.reply_text(
        overview_response["text"],
        reply_markup=overview_response["keyboard"],
        parse_mode=ParseMode.HTML,
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


def _category_name(category: str, lang: str) -> str:
    info = CATEGORY_INFO[category]
    return info["name_ru"] if lang == "ru" else info["name"]


def generate_category_overview(
    categorized_places: dict[str, list[dict[str, Any]]], location_name: str, lang: str = "en"
) -> dict[str, Any]:
    """Generate category-based overview with interactive buttons."""
    if lang == "ru":
        overview_text = f"📍 <b>{escape(location_name)}</b>\n\n🎯 <b>Что вас интересует?</b>\n\n"
        distance_text = "<i>Или выберите расстояние:</i>"
    else:
        overview_text = (
            f"📍 <b>{escape(location_name)}</b>\n\n🎯 <b>What are you looking for?</b>\n\n"
        )
        distance_text = "<i>Or choose distance:</i>"

    available = [c for c, places in categorized_places.items() if c in CATEGORY_INFO and places]

    lines = [
        f"{CATEGORY_INFO[c]['emoji']} {_category_name(c, lang)} ({len(categorized_places[c])})"
        for c in available
    ]
    overview_text += "\n".join(lines) + f"\n\n{distance_text}"

    category_buttons = [
        InlineKeyboardButton(
            f"{CATEGORY_INFO[c]['emoji']} {_category_name(c, lang)}", callback_data=f"category_{c}"
        )
        for c in available
    ]
    keyboard = [category_buttons[i : i + 2] for i in range(0, len(category_buttons), 2)]

    unit = "м" if lang == "ru" else "m"
    keyboard.append(
        [
            InlineKeyboardButton(f"👀 100{unit}", callback_data="distance_100"),
            InlineKeyboardButton(f"🚶 500{unit}", callback_data="distance_500"),
            InlineKeyboardButton(
                "🚗 1км+" if lang == "ru" else "🚗 1km+", callback_data="distance_1000"
            ),
        ]
    )
    all_label = "📍 Всё поблизости" if lang == "ru" else "📍 Everything Nearby"
    keyboard.append([InlineKeyboardButton(all_label, callback_data="category_all")])

    return {"text": overview_text, "keyboard": InlineKeyboardMarkup(keyboard)}


def _places_keyboard(places: list[dict[str, Any]], lang: str) -> InlineKeyboardMarkup:
    keyboard = []
    for i, place in enumerate(places[:5]):
        name = place["name"]
        button_text = f"📖 {name[:25]}..." if len(name) > 25 else f"📖 {name}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"place_details_{i}")])
    back_label = "⬅️ Назад к категориям" if lang == "ru" else "⬅️ Back to Categories"
    keyboard.append([InlineKeyboardButton(back_label, callback_data="back_categories")])
    return InlineKeyboardMarkup(keyboard)


def _place_line(place: dict[str, Any], emoji: str, max_desc: int) -> str:
    line = f"{emoji} <b>{escape(place['name'])}</b> ({int(place.get('distance', 0))}m)\n"
    desc = place.get("description", "")
    if desc:
        if len(desc) > max_desc:
            desc = desc[: max_desc - 3] + "..."
        line += f"<i>{escape(desc)}</i>\n"
    return line + "\n"


def generate_category_places_response(
    places: list[dict[str, Any]], category: str, lang: str = "en"
) -> dict[str, Any]:
    """Generate response for specific category places."""
    if category in CATEGORY_INFO:
        emoji, name = CATEGORY_INFO[category]["emoji"], _category_name(category, lang)
    else:
        emoji, name = "📍", ("Все места" if lang == "ru" else "All Places")

    response_text = f"{emoji} <b>{escape(name)}</b>\n\n"
    response_text += "".join(_place_line(place, "⭐", 60) for place in places[:5])

    return {"text": response_text, "keyboard": _places_keyboard(places, lang)}


def generate_distance_places_response(
    places: list[dict[str, Any]], distance: int, lang: str = "en"
) -> dict[str, Any]:
    """Generate response for distance-filtered places."""
    headers = {
        "ru": {
            100: f"👀 <b>В радиусе {distance}м</b> (что видно прямо сейчас)",
            500: f"🚶 <b>В радиусе {distance}м</b> (5 минут пешком)",
        },
        "en": {
            100: f"👀 <b>Within {distance}m</b> (what you can see right now)",
            500: f"🚶 <b>Within {distance}m</b> (5-minute walk)",
        },
    }
    default = (
        f"🚗 <b>В радиусе {distance}м+</b> (стоит дойти)"
        if lang == "ru"
        else f"🚗 <b>Within {distance}m+</b> (worth the trip)"
    )
    response_text = headers.get(lang, headers["en"]).get(distance, default) + "\n\n"

    for place in places[:7]:
        category = place.get("category", "").lower()
        if "historic" in category or "museum" in category or "culture" in category:
            emoji = "🏛️"
        elif "food" in category or "restaurant" in category or "cafe" in category:
            emoji = "🍽️"
        elif "park" in category or "garden" in category:
            emoji = "🌳"
        else:
            emoji = "📍"
        response_text += _place_line(place, emoji, 50)

    return {"text": response_text, "keyboard": _places_keyboard(places, lang)}


async def handle_callback_query(update: Update, context: CallbackContext):
    """Handle inline button callbacks."""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    await query.answer()

    if user_id not in user_contexts:
        await query.edit_message_text("❌ Session expired. Please send your location again.")
        return

    user_context = user_contexts[user_id]
    categorized_places = user_context.get("categorized_places", {})
    lang = user_context["language"]

    if data.startswith("category_"):
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        category = data.removeprefix("category_")

        if category == "all":
            all_places = [p for cat_places in categorized_places.values() for p in cat_places]
            places_to_show = sorted(all_places, key=lambda x: x["distance"])[:7]
        else:
            places_to_show = categorized_places.get(category, [])[:5]

        if places_to_show:
            user_context["current_places"] = places_to_show
            response = generate_category_places_response(places_to_show, category, lang)
            await query.edit_message_text(
                response["text"], reply_markup=response["keyboard"], parse_mode=ParseMode.HTML
            )
        elif lang == "ru":
            await query.edit_message_text("❌ В этой категории ничего не найдено.")
        else:
            await query.edit_message_text("❌ No places found in this category.")

    elif data.startswith("distance_"):
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        distance = int(data.removeprefix("distance_"))

        all_places = [
            p
            for cat_places in categorized_places.values()
            for p in cat_places
            if p.get("distance", 0) <= distance
        ]
        places_to_show = sorted(all_places, key=lambda x: x["distance"])[:7]

        if places_to_show:
            user_context["current_places"] = places_to_show
            response = generate_distance_places_response(places_to_show, distance, lang)
            await query.edit_message_text(
                response["text"], reply_markup=response["keyboard"], parse_mode=ParseMode.HTML
            )
        elif lang == "ru":
            await query.edit_message_text(f"❌ В радиусе {distance}м ничего не найдено.")
        else:
            await query.edit_message_text(f"❌ No places found within {distance}m.")

    elif data == "back_categories":
        overview_response = generate_category_overview(
            categorized_places, user_context["location"], lang
        )
        await query.edit_message_text(
            overview_response["text"],
            reply_markup=overview_response["keyboard"],
            parse_mode=ParseMode.HTML,
        )

    elif data.startswith("place_details_"):
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        place_index = int(data.removeprefix("place_details_"))
        current_places = user_context.get("current_places", [])

        if place_index < len(current_places):
            place = current_places[place_index]
            detailed_info = generate_detailed_place_info(place, lang)
            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_categories")]]
            await query.edit_message_text(
                detailed_info + AI_DISCLAIMER,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML,
            )


def generate_detailed_place_info(place, lang="en"):
    """Generate detailed AI-powered information about a specific place based on its category."""
    name = place.get("name", "").lower()
    description = place.get("description", "").lower()
    category = place.get("category", "")
    place_type = place.get("tourism") or place.get("historic") or place.get("amenity", "")

    food_keywords = ["restaurant", "cafe", "bar", "pub", "bistro", "pizzeria", "bakery", "food"]
    nature_keywords = ["park", "garden", "forest", "lake", "river", "beach", "nature"]
    shopping_keywords = ["shop", "store", "market", "mall", "boutique", "souvenir"]
    entertainment_keywords = ["cinema", "theater", "club", "disco", "entertainment", "sports"]

    all_text = f"{name} {description} {category} {place_type}".lower()

    if any(keyword in all_text for keyword in food_keywords):
        place_type = "restaurant"
    elif any(keyword in all_text for keyword in nature_keywords):
        place_type = "nature"
    elif any(keyword in all_text for keyword in shopping_keywords):
        place_type = "shopping"
    elif any(keyword in all_text for keyword in entertainment_keywords):
        place_type = "entertainment"
    else:
        place_type = "landmark"

    logger.info(f"Determined place type for {place['name']}: {place_type}")

    place_data = {
        "name": place["name"],
        "type": place.get("tourism") or place.get("historic") or place.get("amenity", place_type),
        "distance": int(place["distance"]),
        "wikipedia": place.get("wikipedia_extract", ""),
        "description": place.get("description", ""),
        "website": place.get("website", ""),
    }
    language = "Russian" if lang == "ru" else "English"
    description_line = (
        f"Description: {place_data['description']}" if place_data["description"] else ""
    )

    if place_type == "restaurant":
        prompt = f"""You are a passionate local foodie with 20+ years of experience. Provide engaging information about this restaurant/cafe:

Name: {place_data["name"]}
Type: {place_data["type"]}
Distance: {place_data["distance"]}m away
{description_line}

Requirements:
- Write in {language}
- 3-4 sentences about the cuisine, atmosphere, and what makes it special
- Include practical visitor information (best dishes, price range if known)
- Be enthusiastic but honest
- If you don't know specific details, suggest what might be good based on the restaurant type/name
- Don't make up exact prices or menu items you're not certain about"""  # noqa: E501

    elif place_type == "nature":
        wikipedia_line = (
            f"Wikipedia info: {place_data['wikipedia']}" if place_data["wikipedia"] else ""
        )
        prompt = f"""You are a nature-loving local guide. Provide engaging information about this natural attraction:

Name: {place_data["name"]}
Type: {place_data["type"]}
Distance: {place_data["distance"]}m away
{wikipedia_line}
{description_line}

Requirements:
- Write in {language}
- 3-4 sentences about what makes this place beautiful or special
- Include practical visitor information (best time to visit, what to see)
- Be engaging and informative
- Focus on natural features and activities visitors can enjoy"""  # noqa: E501

    elif place_type == "shopping":
        prompt = f"""You are a knowledgeable local shopping expert. Provide engaging information about this shopping venue:

Name: {place_data["name"]}
Type: {place_data["type"]}
Distance: {place_data["distance"]}m away
{description_line}

Requirements:
- Write in {language}
- 3-4 sentences about what makes this place worth visiting
- Include practical visitor information (what they sell, price range if known)
- Be enthusiastic but honest
- If you don't know specific details, suggest what might be found based on the shop type/name"""  # noqa: E501

    elif place_type == "entertainment":
        prompt = f"""You are a local entertainment expert. Provide engaging information about this entertainment venue:

Name: {place_data["name"]}
Type: {place_data["type"]}
Distance: {place_data["distance"]}m away
{description_line}

Requirements:
- Write in {language}
- 3-4 sentences about what makes this place fun or interesting
- Include practical visitor information (what to expect, best times to visit)
- Be engaging and informative
- Focus on the experience visitors can expect"""  # noqa: E501

    elif place_data["wikipedia"]:
        prompt = f"""You are an expert local guide with 20+ years of experience. Provide detailed, fascinating information about this landmark using the Wikipedia extract provided:

Name: {place_data["name"]}
Type: {place_data["type"]}
Distance: {place_data["distance"]}m away
Wikipedia extract: {place_data["wikipedia"]}

Requirements:
- Write in {language}
- 3-4 sentences with interesting historical/cultural facts from the Wikipedia extract
- Include practical visitor information if relevant
- Be engaging and informative like a passionate local guide
- Focus on what makes this place special or unique
- Use the Wikipedia information but make it sound like you're a local expert
- Don't start with phrases like 'According to Wikipedia'"""  # noqa: E501
    else:
        prompt = f"""You are an expert local guide with 20+ years of experience. Provide detailed, fascinating information about this landmark:

Name: {place_data["name"]}
Type: {place_data["type"]}
Distance: {place_data["distance"]}m away
{description_line}

Requirements:
- Write in {language}
- 3-4 sentences with interesting historical/cultural facts
- Include practical visitor information if relevant
- Be engaging and informative
- Focus on what makes this place special or unique
- If you don't have specific information about this place, be honest and suggest what visitors might find interesting about similar places in the area
- Don't make up historical facts if you're uncertain"""  # noqa: E501

    emoji = {
        "restaurant": "🍽️",
        "nature": "🌳",
        "shopping": "🛍️",
        "entertainment": "🎭",
    }.get(place_type, "🏛️")

    try:
        detailed_info = generate_answer(prompt)
    except Exception:
        logger.exception(f"Failed to generate detailed info for {place['name']}")
        return (
            f"🏛️ <b>{escape(place['name'])}</b>\n\n"
            "Sorry, I couldn't generate detailed information right now. Please try again later."
        )

    result = f"{emoji} <b>{escape(place['name'])}</b>\n\n{escape(detailed_info)}"

    links = []
    if place.get("website"):
        website_url = place["website"]
        if not website_url.startswith("http"):
            website_url = "https://" + website_url
        links.append(f'🌐 <a href="{escape(website_url)}">Official Website</a>')
    if place.get("wikipedia_url"):
        links.append(f'📖 <a href="{escape(place["wikipedia_url"])}">Wikipedia</a>')
    if links:
        result += "\n\n" + " | ".join(links)

    return result


async def handle_text_message(update: Update, context: CallbackContext):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    llm_response = generate_answer(update.message.text)
    disclaimer = (
        "\n\n⚠️ <i>Disclaimer:</i> This response is AI-generated. "
        "Please verify important information from reliable sources."
    )
    await update.message.reply_text(escape(llm_response) + disclaimer, parse_mode=ParseMode.HTML)


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled error while processing an update", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("⚠️ Something went wrong. Please try again.")


def _get_location_name_with_fallbacks(lat: float, lon: float) -> str:
    """Get location name using multiple reverse geocoding APIs with fallbacks."""
    try:
        response = requests.get(
            "https://api.bigdatacloud.net/data/reverse-geocode-client",
            params={"latitude": lat, "longitude": lon, "localityLanguage": "en"},
            timeout=8,
        )
        response.raise_for_status()
        location_data = response.json()
        if location_data.get("locality") and location_data.get("countryName"):
            return f"{location_data['locality']}, {location_data['countryName']}"
    except Exception as e:
        logger.warning(f"BigDataCloud API failed: {e}")

    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json", "addressdetails": 1},
            timeout=8,
            headers={"User-Agent": "HistoryAroundMeBot/1.0"},
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
        logger.warning(f"Nominatim API failed: {e}")

    if app_settings.LOCATIONIQ_API_KEY:
        try:
            response = requests.get(
                "https://us1.locationiq.com/v1/reverse.php",
                params={
                    "key": app_settings.LOCATIONIQ_API_KEY,
                    "lat": lat,
                    "lon": lon,
                    "format": "json",
                },
                timeout=8,
            )
            response.raise_for_status()
            address = response.json().get("address", {})
            city = address.get("city") or address.get("town") or address.get("village")
            country = address.get("country")
            if city and country:
                return f"{city}, {country}"
        except Exception as e:
            logger.warning(f"LocationIQ API failed: {e}")

    return f"Coordinates: {lat:.4f}, {lon:.4f}"


async def register_handlers(app: Application):
    """Register all command and message handlers."""
    app.add_handler(CommandHandler("start", send_welcome))
    app.add_handler(CommandHandler("health", health_check))
    app.add_handler(MessageHandler(filters.LOCATION, location))
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
