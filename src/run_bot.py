import asyncio
from logging import getLogger
import json
from typing import Dict, List, Any

import requests
from telegram import Update, BotCommand, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    CallbackContext,
    ApplicationBuilder,
    ContextTypes,
    Application,
)

from src.config.config import app_settings
from src.config.logging_config import setup_logging
from src.places_api import get_nearby_places, get_places_by_category_and_distance
from src.utils import generate_answer, escape_markdown_v2

logger = getLogger(__name__)

# Store user context for callback handling
user_contexts = {}


async def send_welcome(update: Update, context: CallbackContext):
    logger.info("Starting a conversation...")
    greeting_text = (
        "🏛️ *Welcome to the History Around Me Bot!* 🌍\n\n"
        "I'm your AI-powered travel guide! Send your location to discover "
        "fascinating historical and cultural landmarks nearby.\n\n"
        "📍 Click the button below to share your current location."
    )

    button = KeyboardButton("📍 Send Location", request_location=True)
    reply_markup = ReplyKeyboardMarkup([[button]], one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(
        greeting_text, 
        reply_markup=reply_markup, 
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def health_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id in app_settings.ADMIN_USER_IDS:
        await context.bot.send_message(chat_id=user_id, text="Bot is live and running!")
        logger.info(f"User {user_id} checked bot's status via /health command. Bot is live and running!")
    else:
        logger.warning(f"Unauthorized /health command from user {user_id}")


async def location(update: Update, context: CallbackContext) -> None:
    """Handle location messages from users."""
    logger.info("=== LOCATION HANDLER TRIGGERED ===")
    
    if not update.message or not update.message.location:
        logger.error("No location data in message")
        await update.message.reply_text("❌ No location data received. Please try again.")
        return
        
    user_location = update.message.location
    lat = user_location.latitude
    lon = user_location.longitude
    user_id = update.message.from_user.id

    logger.info(f"Received location from user {user_id}: {lat}, {lon}")

    # Show typing indicator while processing
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # Get location name using reverse geocoding with fallbacks
    location_name = _get_location_name_with_fallbacks(lat, lon)

    # Determine user language preference from Telegram
    user_lang = _detect_user_language(update)
    logger.info(f"Detected user language: {user_lang}")

    # Show typing indicator while getting places
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # Get nearby places within 10km radius
    logger.info("Searching for nearby places...")
    categorized_places = get_nearby_places(lat, lon, radius=10000, lang=user_lang)
    logger.info(f"Found categorized places: {[(cat, len(places)) for cat, places in categorized_places.items()]}")
    
    # Debug: Log first few places in each category
    for category, places in categorized_places.items():
        if places:
            logger.info(f"Category {category}: {[p['name'] for p in places[:3]]}")
    
    if not categorized_places:
        logger.info("No places found, sending fallback message")
        await send_reply_text(
            update, 
            "🔍 Unfortunately, I couldn't find any notable landmarks or cultural sites nearby\\. "
            "Try moving to a different location or check back later\\!"
        )
        return

    # Store context for callback handling
    user_contexts[user_id] = {
        "location": location_name,
        "coordinates": (lat, lon),
        "categorized_places": categorized_places,
        "language": user_lang
    }
    logger.info(f"Stored context for user {user_id} with language {user_lang}")

    # Show typing indicator while generating AI overview
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # Generate category-based overview with buttons
    logger.info("Generating category overview...")
    overview_response = await generate_category_overview(categorized_places, location_name, user_lang)
    
    # Send the overview with category and distance buttons
    await update.message.reply_text(
        overview_response["text"],
        reply_markup=overview_response["keyboard"],
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    logger.info("=== LOCATION HANDLER COMPLETED ===")


def _detect_user_language(update: Update) -> str:
    """
    Detect user's preferred language from Telegram interface or user data.
    Returns 'en' for English or 'ru' for Russian.
    """
    try:
        # Try to get language from user's Telegram language code
        if update.message and update.message.from_user:
            user = update.message.from_user
            
            # Check user's language code
            if hasattr(user, 'language_code') and user.language_code:
                lang_code = user.language_code.lower()
                logger.info(f"User Telegram language code: {lang_code}")
                
                # Map language codes to supported languages
                if lang_code.startswith('ru'):
                    return 'ru'
                elif lang_code.startswith('en'):
                    return 'en'
                # Add more language mappings as needed
                
            # Check user's first name for Cyrillic characters (Russian indicator)
            if user.first_name:
                # Simple heuristic: if name contains Cyrillic characters, likely Russian speaker
                cyrillic_pattern = r'[а-яё]'
                import re
                if re.search(cyrillic_pattern, user.first_name.lower()):
                    logger.info("Detected Cyrillic in user name, using Russian")
                    return 'ru'
                    
    except Exception as e:
        logger.warning(f"Error detecting user language: {e}")
    
    # Default to English
    logger.info("Using default language: English")
    return 'en'


async def generate_category_overview(categorized_places: Dict[str, List[Dict[Any, Any]]], location_name: str, lang: str = "en") -> Dict[str, Any]:
    """
    Generate category-based overview with interactive buttons.
    """
    # Category emojis and names
    category_info = {
        "history_culture": {"emoji": "🏛️", "name": "History & Culture", "name_ru": "История и культура"},
        "food_drinks": {"emoji": "🍽️", "name": "Food & Drinks", "name_ru": "Еда и напитки"},
        "shopping": {"emoji": "🛍️", "name": "Shopping", "name_ru": "Покупки"},
        "parks_nature": {"emoji": "🌳", "name": "Parks & Nature", "name_ru": "Парки и природа"},
        "entertainment": {"emoji": "🎭", "name": "Entertainment", "name_ru": "Развлечения"},
        "other": {"emoji": "📍", "name": "Other Places", "name_ru": "Другие места"}
    }
    
    # Create overview text
    if lang == "ru":
        overview_text = f"📍 **{escape_markdown_v2(location_name)}**\n\n🎯 **Что вас интересует?**\n\n"
        distance_text = "*Или выберите расстояние:*"
    else:
        overview_text = f"📍 **{escape_markdown_v2(location_name)}**\n\n🎯 **What are you looking for?**\n\n"
        distance_text = "*Or choose distance:*"
    
    # Add category counts
    available_categories = []
    for category, places in categorized_places.items():
        if category in category_info and places:
            count = len(places)
            emoji = category_info[category]["emoji"]
            name = category_info[category]["name_ru"] if lang == "ru" else category_info[category]["name"]
            available_categories.append(f"{emoji} {name} \\({count}\\)")
    
    if available_categories:
        overview_text += "\n".join(available_categories)
        overview_text += f"\n\n{distance_text}"
    else:
        if lang == "ru":
            overview_text += "К сожалению, поблизости не найдено интересных мест\\."
        else:
            overview_text += "Unfortunately, no interesting places found nearby\\."
    
    # Create inline keyboard
    keyboard = []
    
    # Category buttons (2 per row)
    category_buttons = []
    for category, places in categorized_places.items():
        if category in category_info and places:
            emoji = category_info[category]["emoji"]
            name = category_info[category]["name_ru"] if lang == "ru" else category_info[category]["name"]
            button_text = f"{emoji} {name}"
            category_buttons.append(InlineKeyboardButton(button_text, callback_data=f"category_{category}"))
    
    # Arrange category buttons in rows of 2
    for i in range(0, len(category_buttons), 2):
        row = category_buttons[i:i+2]
        keyboard.append(row)
    
    # Distance buttons
    if lang == "ru":
        distance_buttons = [
            InlineKeyboardButton("👀 100м", callback_data="distance_100"),
            InlineKeyboardButton("🚶 500м", callback_data="distance_500"),
            InlineKeyboardButton("🚗 1км+", callback_data="distance_1000")
        ]
    else:
        distance_buttons = [
            InlineKeyboardButton("👀 100m", callback_data="distance_100"),
            InlineKeyboardButton("🚶 500m", callback_data="distance_500"),
            InlineKeyboardButton("🚗 1km+", callback_data="distance_1000")
        ]
    
    keyboard.append(distance_buttons)
    
    # "Everything nearby" button
    if lang == "ru":
        keyboard.append([InlineKeyboardButton("📍 Всё поблизости", callback_data="category_all")])
    else:
        keyboard.append([InlineKeyboardButton("📍 Everything Nearby", callback_data="category_all")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    return {
        "text": overview_text,
        "keyboard": reply_markup
    }


async def generate_category_places_response(places: List[Dict[Any, Any]], category: str, lang: str = "en") -> Dict[str, Any]:
    """
    Generate response for specific category places.
    """
    category_info = {
        "history_culture": {"emoji": "🏛️", "name": "History & Culture", "name_ru": "История и культура"},
        "food_drinks": {"emoji": "🍽️", "name": "Food & Drinks", "name_ru": "Еда и напитки"},
        "shopping": {"emoji": "🛍️", "name": "Shopping", "name_ru": "Покупки"},
        "parks_nature": {"emoji": "🌳", "name": "Parks & Nature", "name_ru": "Парки и природа"},
        "entertainment": {"emoji": "🎭", "name": "Entertainment", "name_ru": "Развлечения"},
        "other": {"emoji": "📍", "name": "Other Places", "name_ru": "Другие места"},
        "all": {"emoji": "📍", "name": "All Places", "name_ru": "Все места"}
    }
    
    if category in category_info:
        emoji = category_info[category]["emoji"]
        name = category_info[category]["name_ru"] if lang == "ru" else category_info[category]["name"]
    else:
        emoji = "📍"
        name = "Places" if lang == "en" else "Места"
    
    if lang == "ru":
        response_text = f"{emoji} **{name}**\n\n"
    else:
        response_text = f"{emoji} **{name}**\n\n"
    
    # Add places with details
    for i, place in enumerate(places[:5], 1):
        distance = int(place.get("distance", 0))
        name = escape_markdown_v2(place["name"])
        
        if category == "food_drinks":
            # Special formatting for restaurants
            response_text += f"⭐ **{name}** \({distance}m\)\n"
            if place.get("description"):
                # Make sure description is properly escaped and truncated safely
                desc = place.get("description", "")
                if len(desc) > 50:
                    desc = desc[:47] + "..."
                desc = escape_markdown_v2(desc)
                response_text += f"_{desc}_\n\n"
            else:
                response_text += f"_{escape_markdown_v2(lang == 'ru' and 'Ресторан' or 'Restaurant')}_\n\n"
        else:
            # Standard formatting for other categories
            response_text += f"⭐ **{name}** \\({distance}m\\)\n"
            if place.get("description"):
                # Make sure description is properly escaped and truncated safely
                desc = place.get("description", "")
                if len(desc) > 60:
                    desc = desc[:57] + "..."
                desc = escape_markdown_v2(desc)
                response_text += f"_{desc}_\n\n"
            else:
                response_text += "\n"
    
    # Create keyboard with place buttons
    keyboard = []
    for i, place in enumerate(places[:5]):
        button_text = f"📖 {place['name'][:25]}..." if len(place['name']) > 25 else f"📖 {place['name']}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"place_details_{i}")])
    
    # Add back button
    if lang == "ru":
        keyboard.append([InlineKeyboardButton("⬅️ Назад к категориям", callback_data="back_categories")])
    else:
        keyboard.append([InlineKeyboardButton("⬅️ Back to Categories", callback_data="back_categories")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    return {
        "text": response_text,
        "keyboard": reply_markup
    }


async def generate_distance_places_response(places: List[Dict[Any, Any]], distance: int, lang: str = "en") -> Dict[str, Any]:
    """
    Generate response for distance-filtered places.
    """
    if lang == "ru":
        if distance == 100:
            response_text = f"👀 **В радиусе {distance}м** \\(что видно прямо сейчас\\)\n\n"
        elif distance == 500:
            response_text = f"🚶 **В радиусе {distance}м** \\(5 минут пешком\\)\n\n"
        else:
            response_text = f"🚗 **В радиусе {distance}м\\+** \\(стоит дойти\\)\n\n"
    else:
        if distance == 100:
            response_text = f"👀 **Within {distance}m** \\(what you can see right now\\)\n\n"
        elif distance == 500:
            response_text = f"🚶 **Within {distance}m** \\(5\\-minute walk\\)\n\n"
        else:
            response_text = f"🚗 **Within {distance}m\\+** \\(worth the trip\\)\n\n"
    
    # Add places with details
    for i, place in enumerate(places[:7], 1):
        actual_distance = int(place.get("distance", 0))
        name = escape_markdown_v2(place["name"])
        
        # Add category emoji
        category = place.get("category", "").lower()
        if "historic" in category or "museum" in category or "culture" in category:
            emoji = "🏛️"
        elif "food" in category or "restaurant" in category or "cafe" in category:
            emoji = "🍽️"
        elif "park" in category or "garden" in category:
            emoji = "🌳"
        else:
            emoji = "📍"
        
        response_text += f"{emoji} **{name}** \\({actual_distance}m\\)\n"
        if place.get("description"):
            response_text += f"_{escape_markdown_v2(place['description'][:50])}..._\n\n"
        else:
            response_text += "\n"
    
    # Create keyboard with place buttons
    keyboard = []
    for i, place in enumerate(places[:5]):
        button_text = f"📖 {place['name'][:25]}..." if len(place['name']) > 25 else f"📖 {place['name']}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"place_details_{i}")])
    
    # Add back button
    if lang == "ru":
        keyboard.append([InlineKeyboardButton("⬅️ Назад к категориям", callback_data="back_categories")])
    else:
        keyboard.append([InlineKeyboardButton("⬅️ Back to Categories", callback_data="back_categories")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    return {
        "text": response_text,
        "keyboard": reply_markup
    }


async def generate_places_overview(places, location_name, lang="en"):
    """Generate AI-powered overview of nearby places."""
    if not places:
        return f"📍 *{location_name}*\n\nNo notable landmarks found nearby\\."
    
    # Create a structured list of places for the AI prompt
    places_list = []
    for i, place in enumerate(places[:5]):
        place_info = f"**{place['name']}**"
        
        # Add type information
        place_type = place.get('tourism') or place.get('historic') or place.get('amenity')
        if place_type:
            place_info += f" ({place_type})"
        
        # Add distance
        place_info += f" - {int(place['distance'])}m away"
        
        # Add any available description or Wikipedia extract
        if place.get('wikipedia_extract'):
            place_info += f"\n{place['wikipedia_extract'][:150]}..."
        elif place.get('description'):
            place_info += f"\n{place['description']}"
        
        places_list.append(place_info)

    places_text = "\n\n".join(places_list)
    
    prompt = f"""You are a knowledgeable local guide. The user is currently in {location_name} and can see these landmarks around them:

{places_text}

Create a response that includes:
1. A brief welcome mentioning the city/area they're in
2. A clear list of the nearby landmarks they can visually see, each with 2-3 engaging sentences describing what makes it interesting

Requirements:
- Write in {'Russian' if lang == 'ru' else 'English'}
- Be enthusiastic and welcoming
- Focus on what makes each place historically/culturally significant
- Keep descriptions concise but engaging (2-3 sentences per place)
- Use this format:

🏛️ **Place Name** (distance)
Brief engaging description about what makes this place special and interesting to visit.

Example format:
🏛️ **Pirosmani Monument** (150m)
This bronze bust commemorates Niko Pirosmani, Georgia's most beloved naive painter who captured rural life in the early 20th century. The monument stands as a tribute to the artist who painted with such passion that he often traded his works for food and wine.

Start with: "You're in [location]! Here are the fascinating landmarks you can see around you:" """

    try:
        logger.info("Generating AI overview for places...")
        overview = generate_answer(prompt)
        
        # Clean up the response and ensure proper formatting
        formatted_overview = escape_markdown_v2(overview)
        
        return f"📍 *{escape_markdown_v2(location_name)}*\n\n{formatted_overview}\n\n*Tap any landmark below for more details:*"
    except Exception as e:
        logger.error(f"Failed to generate overview: {e}")
        # Fallback: create a simple list
        fallback_text = f"📍 *{escape_markdown_v2(location_name)}*\n\n"
        fallback_text += "Here are the interesting places you can see around you:\n\n"
        
        for place in places[:3]:
            fallback_text += f"🏛️ **{escape_markdown_v2(place['name'])}** \\({int(place['distance'])}m away\\)\n"
            place_type = place.get('tourism') or place.get('historic') or place.get('amenity')
            if place_type:
                fallback_text += f"A {escape_markdown_v2(place_type)} worth exploring\\.\n\n"
        
        fallback_text += "*Tap any landmark below for detailed information:*"
        return fallback_text


async def handle_callback_query(update: Update, context: CallbackContext):
    """Handle inline button callbacks."""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    await query.answer()  # Acknowledge the callback

    if user_id not in user_contexts:
        await query.edit_message_text("❌ Session expired. Please send your location again.")
        return

    user_context = user_contexts[user_id]
    categorized_places = user_context.get("categorized_places", {})
    lang = user_context["language"]

    if data.startswith("category_"):
        # Handle category selection
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        category = data.split("_")[1]
        
        # Debug the category mapping
        logger.info(f"Callback category: '{category}'")
        
        # Map common category shortcuts to actual category keys
        category_mapping = {
            "food": "food_drinks",
            "history": "history_culture",
            "parks": "parks_nature",
            "all": "all"  # Keep this as is
        }
        
        # Map the category if needed
        if category in category_mapping:
            actual_category = category_mapping[category]
            logger.info(f"Mapped '{category}' to '{actual_category}'")
            category = actual_category
        
        if category == "all":
            # Show all places mixed
            all_places = []
            for cat_places in categorized_places.values():
                all_places.extend(cat_places)
            places_to_show = sorted(all_places, key=lambda x: x["distance"])[:7]
        else:
            places_to_show = categorized_places.get(category, [])[:5]
        
        # Debug logging
        logger.info(f"Category '{category}' selected. Available categories: {list(categorized_places.keys())}")
        logger.info(f"Places to show: {len(places_to_show)} places")
        if places_to_show:
            logger.info(f"First place: {places_to_show[0]['name']}")
        
        if places_to_show:
            # Store current places for proper indexing in callbacks
            user_context["current_places"] = places_to_show
            response = await generate_category_places_response(places_to_show, category, lang)
            await query.edit_message_text(
                response["text"],
                reply_markup=response["keyboard"],
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            if lang == "ru":
                await query.edit_message_text("❌ В этой категории ничего не найдено.")
            else:
                await query.edit_message_text("❌ No places found in this category.")
    
    elif data.startswith("distance_"):
        # Handle distance filtering
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        distance = int(data.split("_")[1])
        
        # Get all places within distance
        all_places = []
        for cat_places in categorized_places.values():
            for place in cat_places:
                if place.get("distance", 0) <= distance:
                    all_places.append(place)
        
        places_to_show = sorted(all_places, key=lambda x: x["distance"])[:7]
        
        if places_to_show:
            # Store current places for proper indexing in callbacks
            user_context["current_places"] = places_to_show
            response = await generate_distance_places_response(places_to_show, distance, lang)
            await query.edit_message_text(
                response["text"],
                reply_markup=response["keyboard"],
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            if lang == "ru":
                await query.edit_message_text(f"❌ В радиусе {distance}м ничего не найдено.")
            else:
                await query.edit_message_text(f"❌ No places found within {distance}m.")

    elif data.startswith("details_"):
        # Show typing indicator while generating detailed info
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        # Show detailed information about a specific place
        place_index = int(data.split("_")[1])
        
        # Get all places from categorized_places
        all_places = []
        for cat_places in categorized_places.values():
            all_places.extend(cat_places)
        
        if place_index < len(all_places):
            place = all_places[place_index]
            user_context["current_place"] = place["name"]  # Store current place for topic generation
            detailed_info = await generate_detailed_place_info(place, lang)
            
            # Create dynamic follow-up buttons
            keyboard = await generate_dynamic_buttons(place, lang)
            keyboard.append([InlineKeyboardButton("⬅️ Back to overview", callback_data="back_overview")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            disclaimer = (
                "\n\n⚠️ *Disclaimer:* This information is AI\\-generated\\. "
                "Please verify important details from official sources\\."
            )
            
            await query.edit_message_text(
                detailed_info + disclaimer,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )

    elif data.startswith("topic_"):
        # Show typing indicator while generating topic info
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        # Handle dynamic topic exploration
        topic = data.split("_", 1)[1]
        place_name = user_context.get("current_place", "this location")
        
        topic_info = await generate_topic_info(topic, place_name, lang)
        
        keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_details")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        disclaimer = (
            "\n\n⚠️ *Disclaimer:* This information is AI\\-generated\\. "
            "Please verify important details from official sources\\."
        )
        
        await query.edit_message_text(
            topic_info + disclaimer,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2
        )

    elif data == "back_categories":
        # Go back to category overview
        location_name = user_context["location"]
        overview_response = await generate_category_overview(categorized_places, location_name, lang)
        await query.edit_message_text(
            overview_response["text"],
            reply_markup=overview_response["keyboard"],
            parse_mode=ParseMode.MARKDOWN_V2
        )

    elif data.startswith("place_details_"):
        # Handle place details from category/distance views
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        place_index = int(data.split("_")[2])
        
        # Store current places in context for proper indexing
        current_places = user_context.get("current_places", [])
        
        if place_index < len(current_places):
            place = current_places[place_index]
            user_context["current_place"] = place["name"]
            detailed_info = await generate_detailed_place_info(place, lang)
            
            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_categories")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            disclaimer = (
                "\n\n⚠️ *Disclaimer:* This information is AI\\-generated\\. "
                "Please verify important details from official sources\\."
            )
            
            await query.edit_message_text(
                detailed_info + disclaimer,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )

    elif data == "back_overview":
        # Go back to places overview
        await location_from_context(update, context, user_context)

    elif data == "back_details":
        # Go back to detailed place info
        place_name = user_context.get("current_place")
        if place_name:
            # Find the place in the places list
            for i, place in enumerate(places):
                if place["name"] == place_name:
                    # Show typing indicator
                    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
                    
                    detailed_info = await generate_detailed_place_info(place, lang)
                    keyboard = await generate_dynamic_buttons(place, lang)
                    keyboard.append([InlineKeyboardButton("⬅️ Back to overview", callback_data="back_overview")])
                    
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    disclaimer = (
                        "\n\n⚠️ *Disclaimer:* This information is AI\\-generated\\. "
                        "Please verify important details from official sources\\."
                    )
                    
                    await query.edit_message_text(
                        detailed_info + disclaimer,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                    break

    elif data == "more_places":
        # Show additional places
        additional_places = places[5:10] if len(places) > 5 else []
        if additional_places:
            keyboard = []
            for i, place in enumerate(additional_places):
                button_text = f"🏛️ {place['name'][:30]}..." if len(place['name']) > 30 else f"🏛️ {place['name']}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"details_{i+5}")])
            
            keyboard.append([InlineKeyboardButton("⬅️ Back to main places", callback_data="back_overview")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "🔍 *More places nearby:*",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )


async def generate_detailed_place_info(place, lang="en"):
    """Generate detailed AI-powered information about a specific place based on its category."""
    # Determine the place category
    name = place.get("name", "").lower()
    description = place.get("description", "").lower()
    category = place.get("category", "")
    place_type = place.get("tourism") or place.get("historic") or place.get("amenity", "")
    
    # Determine the category based on place properties
    food_keywords = ["restaurant", "cafe", "bar", "pub", "bistro", "pizzeria", "bakery", "food"]
    nature_keywords = ["park", "garden", "forest", "lake", "river", "beach", "nature"]
    shopping_keywords = ["shop", "store", "market", "mall", "boutique", "souvenir"]
    entertainment_keywords = ["cinema", "theater", "club", "disco", "entertainment", "sports"]
    
    # Combine all text for checking
    all_text = f"{name} {description} {category} {place_type}".lower()
    
    # Determine place type for prompt selection
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
        "website": place.get("website", "")
    }
    
    # Select appropriate prompt based on place type
    if place_type == "restaurant":
        prompt = f"""You are a passionate local foodie with 20+ years of experience. Provide engaging information about this restaurant/cafe:

Name: {place_data['name']}
Type: {place_data['type']}
Distance: {place_data['distance']}m away
{f"Description: {place_data['description']}" if place_data['description'] else ""}

Requirements:
- Write in {'Russian' if lang == 'ru' else 'English'}
- 3-4 sentences about the cuisine, atmosphere, and what makes it special
- Include practical visitor information (best dishes, price range if known)
- Be enthusiastic but honest
- If you don't know specific details, suggest what might be good based on the restaurant type/name
- Don't make up exact prices or menu items you're not certain about"""
    
    elif place_type == "nature":
        prompt = f"""You are a nature-loving local guide. Provide engaging information about this natural attraction:

Name: {place_data['name']}
Type: {place_data['type']}
Distance: {place_data['distance']}m away
{f"Wikipedia info: {place_data['wikipedia']}" if place_data['wikipedia'] else ""}
{f"Description: {place_data['description']}" if place_data['description'] else ""}

Requirements:
- Write in {'Russian' if lang == 'ru' else 'English'}
- 3-4 sentences about what makes this place beautiful or special
- Include practical visitor information (best time to visit, what to see)
- Be engaging and informative
- Focus on natural features and activities visitors can enjoy"""
    
    elif place_type == "shopping":
        prompt = f"""You are a knowledgeable local shopping expert. Provide engaging information about this shopping venue:

Name: {place_data['name']}
Type: {place_data['type']}
Distance: {place_data['distance']}m away
{f"Description: {place_data['description']}" if place_data['description'] else ""}

Requirements:
- Write in {'Russian' if lang == 'ru' else 'English'}
- 3-4 sentences about what makes this place worth visiting
- Include practical visitor information (what they sell, price range if known)
- Be enthusiastic but honest
- If you don't know specific details, suggest what might be found based on the shop type/name"""
    
    elif place_type == "entertainment":
        prompt = f"""You are a local entertainment expert. Provide engaging information about this entertainment venue:

Name: {place_data['name']}
Type: {place_data['type']}
Distance: {place_data['distance']}m away
{f"Description: {place_data['description']}" if place_data['description'] else ""}

Requirements:
- Write in {'Russian' if lang == 'ru' else 'English'}
- 3-4 sentences about what makes this place fun or interesting
- Include practical visitor information (what to expect, best times to visit)
- Be engaging and informative
- Focus on the experience visitors can expect"""
    
    else:  # Default historical/cultural landmark
        # Check if we have Wikipedia extract
        has_wikipedia_data = place.get('wikipedia_extract', '') != ''
        
        if has_wikipedia_data:
            # We have Wikipedia data, use it as the primary source
            prompt = f"""You are an expert local guide with 20+ years of experience. Provide detailed, fascinating information about this landmark using the Wikipedia extract provided:

Name: {place_data['name']}
Type: {place_data['type']}
Distance: {place_data['distance']}m away
Wikipedia extract: {place.get('wikipedia_extract', '')}

Requirements:
- Write in {'Russian' if lang == 'ru' else 'English'}
- 3-4 sentences with interesting historical/cultural facts from the Wikipedia extract
- Include practical visitor information if relevant
- Be engaging and informative like a passionate local guide
- Focus on what makes this place special or unique
- Use the Wikipedia information but make it sound like you're a local expert
- Don't start with phrases like 'According to Wikipedia'"""
        else:
            # No Wikipedia data, use generic prompt but be more specific about local knowledge
            prompt = f"""You are an expert local guide with 20+ years of experience. Provide detailed, fascinating information about this landmark:

Name: {place_data['name']}
Type: {place_data['type']}
Distance: {place_data['distance']}m away
{f"Description: {place_data['description']}" if place_data['description'] else ""}

Requirements:
- Write in {'Russian' if lang == 'ru' else 'English'}
- 3-4 sentences with interesting historical/cultural facts
- Include practical visitor information if relevant
- Be engaging and informative
- Focus on what makes this place special or unique
- If you don't have specific information about this place, be honest and suggest what visitors might find interesting about similar places in the area
- Don't make up historical facts if you're uncertain"""

    try:
        logger.info(f"Generating detailed info for {place_data['name']}...")
        
        # Log place data for debugging
        logger.info(f"Place data: {place}")
        
        # Log if we have Wikipedia extract
        if place.get('wikipedia_extract'):
            logger.info(f"Wikipedia extract available: {place.get('wikipedia_extract')[:200]}...")
        else:
            logger.info("No Wikipedia extract available for this place")
            
        detailed_info = generate_answer(prompt)
        
        # Use appropriate emoji based on place type
        if place_type == "restaurant":
            emoji = "🍽️"
        elif place_type == "nature":
            emoji = "🌳"
        elif place_type == "shopping":
            emoji = "🛍️"
        elif place_type == "entertainment":
            emoji = "🎭"
        else:
            emoji = "🏛️"
        
        # Make sure to escape all text properly for MarkdownV2
        escaped_name = escape_markdown_v2(place['name'])
        escaped_info = escape_markdown_v2(detailed_info)
            
        result = f"{emoji} **{escaped_name}**\n\n{escaped_info}"
        
        # Add links section with proper formatting
        links = []
        
        if place.get("website"):
            # Make sure URLs are properly formatted for Telegram
            website_url = place['website']
            if not website_url.startswith("http"):
                website_url = "https://" + website_url
            links.append(f"🌐 [Official Website]({website_url})")
            
        if place.get("wikipedia_url"):
            wiki_url = place['wikipedia_url']
            links.append(f"📖 [Wikipedia]({wiki_url})")
            
        if links:
            # Join with properly escaped pipe character
            result += "\n\n" + " \| ".join(links)
            
        return result
    except Exception as e:
        logger.error(f"Failed to generate detailed info: {e}")
        return f"🏛️ **{escape_markdown_v2(place['name'])}**\n\nSorry, I couldn't generate detailed information right now\\. Please try again later\\."


async def generate_dynamic_buttons(place, lang="en"):
    """Generate AI-powered dynamic buttons for related topics."""
    place_info = f"Name: {place['name']}, Type: {place.get('tourism') or place.get('historic') or place.get('amenity')}"
    
    # Ensure language is properly specified in the prompt
    language_instruction = "English" if lang == "en" else "Russian" if lang == "ru" else "English"
    
    prompt = f"""Given this landmark: {place_info}

Suggest 2-3 interesting related topics that visitors might want to learn about. Topics should be:
- Specific and engaging (not generic)
- Related to history, culture, architecture, or local significance
- Suitable for curious travelers
- Written ONLY in {language_instruction} language
- NO Georgian, Arabic, or other scripts - use Latin alphabet only

Format as: topic1|topic2|topic3 (max 25 chars each, no extra text)

Examples for {language_instruction}: 
- English: "Architecture Style|Historical Events|Local Legends"
- Russian: "Архитектура|История|Легенды"

IMPORTANT: Respond ONLY in {language_instruction}. Do not use any other language or script."""

    try:
        logger.info(f"Generating dynamic buttons for {place['name']} in {language_instruction}...")
        topics_response = generate_answer(prompt)
        topics = [t.strip() for t in topics_response.split("|") if t.strip()][:3]
        
        # Validate that topics are in the correct language/script
        keyboard = []
        for topic in topics:
            if len(topic) <= 35 and _is_valid_language_script(topic, lang):
                keyboard.append([InlineKeyboardButton(f"💡 {topic}", callback_data=f"topic_{topic}")])
            else:
                logger.warning(f"Skipping invalid topic: {topic} (wrong language or too long)")
        
        # If no valid topics, add a fallback
        if not keyboard:
            fallback_topic = "Learn more" if lang == "en" else "Узнать больше"
            keyboard.append([InlineKeyboardButton(f"💡 {fallback_topic}", callback_data=f"topic_General Information")])
        
        return keyboard
    except Exception as e:
        logger.error(f"Failed to generate dynamic buttons: {e}")
        fallback_topic = "Learn more" if lang == "en" else "Узнать больше"
        return [[InlineKeyboardButton(f"💡 {fallback_topic}", callback_data="topic_General Information")]]


def _is_valid_language_script(text: str, lang: str) -> bool:
    """
    Check if text uses the expected script for the given language.
    """
    import re
    
    if lang == "ru":
        # For Russian, expect Cyrillic characters
        cyrillic_pattern = r'[а-яё]'
        return bool(re.search(cyrillic_pattern, text.lower()))
    elif lang == "en":
        # For English, expect Latin characters only (no Cyrillic, Georgian, etc.)
        latin_only_pattern = r'^[a-zA-Z0-9\s\-\.\,\!\?\'\"]*$'
        return bool(re.match(latin_only_pattern, text))
    
    # Default: allow any text
    return True


async def generate_topic_info(topic, place_name, lang="en"):
    """Generate information about a specific topic related to the place."""
    prompt = f"""You are a knowledgeable guide. Provide interesting information about "{topic}" related to {place_name}.

Requirements:
- Write in {'Russian' if lang == 'ru' else 'English'}
- 2-3 sentences with specific, engaging details
- Focus on the requested topic
- Be informative but concise
- Include interesting facts or stories if relevant"""

    try:
        logger.info(f"Generating topic info for '{topic}' related to {place_name}...")
        topic_info = generate_answer(prompt)
        return f"💡 **{escape_markdown_v2(topic)}**\n\n{escape_markdown_v2(topic_info)}"
    except Exception as e:
        logger.error(f"Failed to generate topic info: {e}")
        return f"💡 **{escape_markdown_v2(topic)}**\n\nSorry, I couldn't generate information about this topic right now\\."


async def location_from_context(update: Update, context: CallbackContext, user_context):
    """Recreate location overview from stored context."""
    places = user_context["places"]
    location_name = user_context["location"]
    lang = user_context["language"]
    
    places_overview = await generate_places_overview(places, location_name, lang)
    
    keyboard = []
    for i, place in enumerate(places[:5]):
        button_text = f"🏛️ {place['name'][:30]}..." if len(place['name']) > 30 else f"🏛️ {place['name']}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"details_{i}")])
    
    if len(places) > 5:
        keyboard.append([InlineKeyboardButton("🔍 More nearby places", callback_data="more_places")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    disclaimer = (
        "\n\n⚠️ *Disclaimer:* This information is AI\\-generated and may not be completely accurate\\. "
        "Please verify important details from official sources\\."
    )
    
    await update.callback_query.edit_message_text(
        places_overview + disclaimer,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def handle_text_message(update: Update, context: CallbackContext):
    logger.info("Processing user's text message")
    user_input = update.message.text

    # Show typing indicator while generating response
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # Generate AI response with disclaimer
    logger.info("Generating AI response for text message...")
    llm_response = generate_answer(user_input)
    
    disclaimer = (
        "\n\n⚠️ *Disclaimer:* This response is AI\\-generated\\. "
        "Please verify important information from reliable sources\\."
    )
    
    full_response = llm_response + disclaimer
    await send_reply_text(update, full_response)


async def send_reply_text(update: Update, text: str):
    # escaped_text = escape_markdown_v2(text)
    escaped_text = text
    await update.message.reply_text(escaped_text, parse_mode=ParseMode.MARKDOWN_V2)


def _get_location_name_with_fallbacks(lat: float, lon: float) -> str:
    """
    Get location name using multiple reverse geocoding APIs with fallbacks.
    """
    logger.info("Getting location name via reverse geocoding...")
    
    # API 1: BigDataCloud (free, no key required)
    try:
        response = requests.get(
            f"https://api.bigdatacloud.net/data/reverse-geocode-client?latitude={lat}&longitude={lon}&localityLanguage=en",
            timeout=8
        )
        response.raise_for_status()
        location_data = response.json()
        if location_data.get('locality') and location_data.get('countryName'):
            location_name = f"{location_data['locality']}, {location_data['countryName']}"
            logger.info(f"Location name from BigDataCloud: {location_name}")
            return location_name
    except Exception as e:
        logger.warning(f"BigDataCloud API failed: {e}")
    
    # API 2: Nominatim (free, no key required)
    try:
        response = requests.get(
            f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&addressdetails=1",
            timeout=8,
            headers={'User-Agent': 'HistoryAroundMeBot/1.0'}
        )
        response.raise_for_status()
        location_data = response.json()
        
        address = location_data.get('address', {})
        city = address.get('city') or address.get('town') or address.get('village') or address.get('municipality')
        country = address.get('country')
        
        if city and country:
            location_name = f"{city}, {country}"
            logger.info(f"Location name from Nominatim: {location_name}")
            return location_name
    except Exception as e:
        logger.warning(f"Nominatim API failed: {e}")
    
    # API 3: LocationIQ (free tier available)
    if hasattr(app_settings, 'LOCATIONIQ_API_KEY') and app_settings.LOCATIONIQ_API_KEY:
        try:
            response = requests.get(
                f"https://us1.locationiq.com/v1/reverse.php?key={app_settings.LOCATIONIQ_API_KEY}&lat={lat}&lon={lon}&format=json",
                timeout=8
            )
            response.raise_for_status()
            location_data = response.json()
            
            address = location_data.get('address', {})
            city = address.get('city') or address.get('town') or address.get('village')
            country = address.get('country')
            
            if city and country:
                location_name = f"{city}, {country}"
                logger.info(f"Location name from LocationIQ: {location_name}")
                return location_name
        except Exception as e:
            logger.warning(f"LocationIQ API failed: {e}")
    
    # Fallback: Use coordinates
    location_name = f"Coordinates: {lat:.4f}, {lon:.4f}"
    logger.info(f"Using fallback location name: {location_name}")
    return location_name


async def register_handlers(app: Application):
    """Register all command and message handlers."""
    logger.info("Registering handlers...")
    
    app.add_handler(CommandHandler("start", send_welcome))
    app.add_handler(CommandHandler("health", health_check))
    
    # Location handler - must be registered before text handler
    location_handler = MessageHandler(filters.LOCATION, location)
    app.add_handler(location_handler)
    logger.info("Location handler registered")
    
    # Re-enable callback handler for inline buttons
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    logger.info("Callback query handler registered")
    
    # Text handler - should be last to avoid conflicts
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
    )
    logger.info("Text message handler registered")
    
    commands = [
        BotCommand("start", "Start interacting with the bot"),
    ]
    await app.bot.set_my_commands(commands)
    logger.info("Bot commands set successfully")


async def main():
    """Main entry point for the bot."""
    bot_app = ApplicationBuilder().token(app_settings.TELEGRAM_BOT_TOKEN).build()

    # Initialize the application
    await bot_app.initialize()

    # Register all handlers
    await register_handlers(bot_app)

    try:
        logger.info("Starting the bot...")
        await bot_app.start()
        await bot_app.updater.start_polling()
        await asyncio.Future()
    except (KeyboardInterrupt, SystemExit):
        logger.error("Bot stopped.")
    finally:
        logger.info("Shutting down the bot...")


if __name__ == "__main__":
    setup_logging()
    asyncio.run(main())
