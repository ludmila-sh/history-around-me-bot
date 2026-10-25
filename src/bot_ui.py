"""Telegram texts and keyboards for the bot: pure functions, no I/O.

Callback data (Telegram limits it to 64 bytes):
  cat:<scope>:<page>  list of places; scope is a category key or "all"
  pl:<scope>:<index>  place card; index is the place's position in that scope's full list
  food                load "Food & Coffee"
  back                overview
  noop                page counter button
"""

import math
from html import escape
from typing import Any
from urllib.parse import quote_plus

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

PAGE_SIZE = 8
EXTRACT_MAX_CHARS = 700
BUTTON_NAME_MAX_CHARS = 32

ALL = "all"
FOOD = "food_drinks"
SIGHT_CATEGORIES = ("history_culture", "parks_nature", "viewpoints")

CATEGORY_INFO = {
    "history_culture": ("🏛️", {"en": "History & Culture", "ru": "История и культура"}),
    "parks_nature": ("🌳", {"en": "Parks & Nature", "ru": "Парки и природа"}),
    "viewpoints": ("🔭", {"en": "Viewpoints", "ru": "Виды"}),
    FOOD: ("☕", {"en": "Food & Coffee", "ru": "Еда и кофе"}),
}

TEXTS = {
    "en": {
        "welcome": (
            "🏛️ <b>Welcome to History Around Me!</b>\n\n"
            "Send your location and I'll show notable places within a short walk: history, "
            "culture, parks, viewpoints, and the best food and coffee.\n\n"
            "📍 Tap the button below to share where you are.\n\n"
            "<i>Descriptions come from Wikipedia and OpenStreetMap, food data from Google Maps. "
            "Double-check opening hours and prices.</i>"
        ),
        "choose": "🎯 <b>What are you looking for?</b>",
        "expanded": "Little within {near} m, so I searched within {radius}.",
        "nothing": "🔍 Nothing notable within {radius}. Try another spot, or look for food.",
        "everything": "📍 Everything nearby",
        "back": "⬅️ Back",
        "to_list": "⬅️ Back to the list",
        "to_overview": "⬅️ Back to categories",
        "list_range": "{first}–{last} of {total}",
        "on_map": "🗺 On the map",
        "wikipedia": "📖 Wikipedia",
        "no_description": "No description available for this place. Open it on the map.",
        "source_wikipedia": "Source: Wikipedia article in {language}",
        "food_title": "Best food and coffee nearby",
        "food_empty": "Nothing with enough reviews found nearby.",
        "food_unavailable": "⚠️ Google Maps isn't responding right now. Try again in a minute.",
        "places_unavailable": "⚠️ The map service isn't responding. Try again in a minute.",
        "expired": "❌ Session expired. Please send your location again.",
        "meters": "{n} m",
        "kilometers": "{n} km",
        "languages": {"en": "English", "ru": "Russian", "tr": "Turkish"},
    },
    "ru": {
        "welcome": (
            "🏛️ <b>Добро пожаловать в History Around Me!</b>\n\n"
            "Отправьте геолокацию, и я покажу значимые места в пешей доступности: история, "
            "культура, парки, виды и лучшие места, где поесть и выпить кофе.\n\n"
            "📍 Нажмите кнопку ниже, чтобы поделиться, где вы.\n\n"
            "<i>Описания берутся из Википедии и OpenStreetMap, данные о еде из Google Maps. "
            "Проверяйте часы работы и цены.</i>"
        ),
        "choose": "🎯 <b>Что вас интересует?</b>",
        "expanded": "В радиусе {near} м почти ничего нет, поэтому ищу в радиусе {radius}.",
        "nothing": "🔍 В радиусе {radius} не нашлось ничего значимого. Попробуйте другое место "
        "или поищите, где поесть.",
        "everything": "📍 Всё поблизости",
        "back": "⬅️ Назад",
        "to_list": "⬅️ К списку",
        "to_overview": "⬅️ К категориям",
        "list_range": "{first}–{last} из {total}",
        "on_map": "🗺 На карте",
        "wikipedia": "📖 Википедия",
        "no_description": "Описания этого места нет. Откройте его на карте.",
        "source_wikipedia": "Источник: статья Википедии на {language}",
        "food_title": "Лучшее поблизости: еда и кофе",
        "food_empty": "Рядом не нашлось мест с достаточным числом отзывов.",
        "food_unavailable": "⚠️ Google Maps сейчас не отвечает. Попробуйте через минуту.",
        "places_unavailable": "⚠️ Сервис карт сейчас не отвечает. Попробуйте через минуту.",
        "expired": "❌ Сессия устарела. Отправьте геолокацию ещё раз.",
        "meters": "{n} м",
        "kilometers": "{n} км",
        "languages": {"en": "английском", "ru": "русском", "tr": "турецком"},
    },
}

Screen = tuple[str, InlineKeyboardMarkup]


def _t(lang: str) -> dict[str, Any]:
    return TEXTS.get(lang, TEXTS["en"])


def category_name(category: str, lang: str) -> str:
    emoji, names = CATEGORY_INFO[category]
    return f"{emoji} {names.get(lang, names['en'])}"


def text(key: str, lang: str) -> str:
    """A plain UI string, for messages the handlers send on their own."""
    return _t(lang)[key]


def format_distance(meters: float, lang: str) -> str:
    strings = _t(lang)
    rounded = int(round(meters, -1)) if meters >= 100 else int(meters)
    if rounded < 1000:
        return strings["meters"].format(n=rounded)
    return strings["kilometers"].format(n=f"{meters / 1000:.1f}")


def _short(name: str) -> str:
    return name if len(name) <= BUTTON_NAME_MAX_CHARS else name[: BUTTON_NAME_MAX_CHARS - 1] + "…"


def sights_in_scope(
    by_category: dict[str, list[dict[str, Any]]], scope: str
) -> list[dict[str, Any]]:
    """Places for a category, or all sights most notable first (OpenTripMap rate, then distance)."""
    if scope != ALL:
        return by_category.get(scope, [])
    everything = [p for category in SIGHT_CATEGORIES for p in by_category.get(category, [])]
    return sorted(everything, key=lambda p: (-p.get("rate", 0), p["distance"]))


def welcome(lang: str) -> str:
    return _t(lang)["welcome"]


def message_with_back(message: str, lang: str) -> Screen:
    """A short notice with a button back to the category overview."""
    keyboard = [[InlineKeyboardButton(_t(lang)["to_overview"], callback_data="back")]]
    return message, InlineKeyboardMarkup(keyboard)


def overview(
    by_category: dict[str, list[dict[str, Any]]],
    location_name: str,
    lang: str,
    radius: int,
    expanded: bool,
    near_radius: int,
) -> Screen:
    strings = _t(lang)
    radius_text = format_distance(radius, lang)
    lines = [f"📍 <b>{escape(location_name)}</b>", ""]
    if expanded:
        note = strings["expanded"].format(near=near_radius, radius=radius_text)
        lines += [f"<i>{note}</i>", ""]

    available = [c for c in SIGHT_CATEGORIES if by_category.get(c)]
    keyboard: list[list[InlineKeyboardButton]] = []
    if available:
        lines.append(strings["choose"])
        lines.append("")
        lines += [f"{escape(category_name(c, lang))} ({len(by_category[c])})" for c in available]
        buttons = [
            InlineKeyboardButton(category_name(c, lang), callback_data=f"cat:{c}:0")
            for c in available
        ]
        keyboard = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
        keyboard.append([InlineKeyboardButton(strings["everything"], callback_data=f"cat:{ALL}:0")])
    else:
        lines.append(strings["nothing"].format(radius=radius_text))
    lines.append(escape(category_name(FOOD, lang)))
    keyboard.append([InlineKeyboardButton(category_name(FOOD, lang), callback_data="food")])
    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


def page_count(total: int) -> int:
    return max(1, math.ceil(total / PAGE_SIZE))


def place_list(scope: str, places: list[dict[str, Any]], page: int, lang: str) -> Screen:
    """One page of a scope's places; every place is a button that opens its card."""
    strings = _t(lang)
    pages = page_count(len(places))
    page = min(max(page, 0), pages - 1)
    first = page * PAGE_SIZE
    chunk = places[first : first + PAGE_SIZE]

    title = strings["everything"] if scope == ALL else category_name(scope, lang)
    shown = strings["list_range"].format(
        first=first + 1, last=first + len(chunk), total=len(places)
    )
    header = f"<b>{escape(title)}</b>\n{shown}"

    keyboard = [
        [
            InlineKeyboardButton(
                f"{_short(place['name'])} · {format_distance(place['distance'], lang)}",
                callback_data=f"pl:{scope}:{first + offset}",
            )
        ]
        for offset, place in enumerate(chunk)
    ]
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀", callback_data=f"cat:{scope}:{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page + 1}/{pages}", callback_data="noop"))
        if page < pages - 1:
            nav.append(InlineKeyboardButton("▶", callback_data=f"cat:{scope}:{page + 1}"))
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton(strings["to_overview"], callback_data="back")])
    return header, InlineKeyboardMarkup(keyboard)


def _trim_extract(extract: str) -> str:
    """Shorten to whole sentences; Wikipedia marks its own server-side cut with "..."."""
    api_cut = extract.endswith("...")
    if len(extract) <= EXTRACT_MAX_CHARS and not api_cut:
        return extract
    cut = extract[:EXTRACT_MAX_CHARS].removesuffix("...")
    sentence_end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if sentence_end > len(cut) // 2:
        return cut[: sentence_end + 1]
    return cut.rsplit(" ", 1)[0] + "…"


def maps_url(place: dict[str, Any], location_name: str) -> str:
    """Google Maps link, no API: by Google place id, by name and city, or by coordinates."""
    if place.get("place_id"):
        return (
            "https://www.google.com/maps/search/?api=1"
            f"&query={quote_plus(place['name'])}&query_place_id={place['place_id']}"
        )
    if location_name and not location_name.startswith("Coordinates:"):
        city = location_name.split(",")[0]
        return f"https://www.google.com/maps/search/?api=1&query={quote_plus(place['name'])}+{quote_plus(city)}"
    return (
        f"https://www.google.com/maps/search/?api=1&query={place['latitude']},{place['longitude']}"
    )


def place_card(
    place: dict[str, Any], scope: str, index: int, lang: str, location_name: str
) -> Screen:
    """Name, kind and distance, the Wikipedia extract if there is one, and link buttons.

    Nothing is generated: without an extract the card says so instead of guessing.
    """
    strings = _t(lang)
    emoji, _ = CATEGORY_INFO.get(place["category_key"], ("📍", {}))
    kind = (
        category_name(place["category_key"], lang) if place["category_key"] in CATEGORY_INFO else ""
    )
    lines = [
        f"{emoji} <b>{escape(place['name'])}</b>",
        f"<i>{escape(kind)} · {format_distance(place['distance'], lang)}</i>",
        "",
    ]
    extract = place.get("wikipedia_extract")
    if extract:
        lines.append(escape(_trim_extract(extract)))
        article_lang = place.get("wikipedia_lang", "")
        language = strings["languages"].get(article_lang, article_lang)
        lines += ["", f"<i>{strings['source_wikipedia'].format(language=escape(language))}</i>"]
    else:
        lines.append(strings["no_description"])

    links = [InlineKeyboardButton(strings["on_map"], url=maps_url(place, location_name))]
    if place.get("wikipedia_url"):
        links.append(InlineKeyboardButton(strings["wikipedia"], url=place["wikipedia_url"]))
    back_page = index // PAGE_SIZE
    keyboard = [
        links,
        [InlineKeyboardButton(strings["to_list"], callback_data=f"cat:{scope}:{back_page}")],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


def food_screen(places: list[dict[str, Any]], lang: str, location_name: str) -> Screen:
    """Best-rated food and coffee. "Google Maps" must stay next to Google's data."""
    strings = _t(lang)
    if not places:
        title = escape(category_name(FOOD, lang))
        return message_with_back(f"{title}\n\n{strings['food_empty']}", lang)
    lines = [f"<b>{escape(category_name(FOOD, lang))}</b>", strings["food_title"], ""]
    keyboard = []
    for number, place in enumerate(places, start=1):
        details = [f"⭐ {place['rating']} ({place['review_count']})"]
        if place.get("price"):
            details.append(escape(place["price"]))
        details.append(format_distance(place["distance"], lang))
        lines += [f"{number}. <b>{escape(place['name'])}</b>", "   " + " · ".join(details)]
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"🗺 {number}. {_short(place['name'])}", url=maps_url(place, location_name)
                )
            ]
        )
    lines += ["", "<i>Google Maps</i>"]
    keyboard.append([InlineKeyboardButton(strings["to_overview"], callback_data="back")])
    return "\n".join(lines), InlineKeyboardMarkup(keyboard)
