"""Key path through the real handlers, with fake Telegram objects and no network."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src import run_bot
from src.places_api import NearbyPlaces, PlacesUnavailable

USER_ID = 424242
SIGHT = {
    "name": "Süleymaniye Mosque",
    "category_key": "history_culture",
    "category": "Religion: Mosques",
    "distance": 126.0,
    "latitude": 41.0163,
    "longitude": 28.9640,
    "rate": 7,
    "wikipedia_extract": "Test extract about the mosque.",
    "wikipedia_lang": "en",
    "wikipedia_url": "https://en.example.org/wiki/Mosque",
}
FOOD = {
    "name": "Topkapı Kebap",
    "category_key": "food_drinks",
    "rating": 4.7,
    "review_count": 329,
    "price": "₺400–600",
    "distance": 446.0,
    "place_id": "ChIJ1",
}


def _update(lang: str = "en") -> SimpleNamespace:
    user = SimpleNamespace(id=USER_ID, language_code=lang, first_name="Test")
    message = SimpleNamespace(
        location=SimpleNamespace(latitude=41.0155, longitude=28.9650),
        from_user=user,
        reply_text=AsyncMock(),
    )
    return SimpleNamespace(
        message=message, effective_user=user, effective_chat=SimpleNamespace(id=1)
    )


def _press(data: str, lang: str = "en", user_id: int = USER_ID) -> SimpleNamespace:
    user = SimpleNamespace(id=user_id, language_code=lang, first_name="Test")
    query = SimpleNamespace(
        data=data, from_user=user, answer=AsyncMock(), edit_message_text=AsyncMock()
    )
    return SimpleNamespace(
        callback_query=query, effective_user=user, effective_chat=SimpleNamespace(id=1)
    )


def _context() -> SimpleNamespace:
    return SimpleNamespace(bot=SimpleNamespace(send_chat_action=AsyncMock()))


def _shown(update) -> str:
    return update.callback_query.edit_message_text.call_args.args[0]


@pytest.fixture(autouse=True)
def fake_services(monkeypatch):
    run_bot.user_contexts.clear()
    calls = {"food": 0}

    async def nearby(lat, lon, lang="en"):
        return NearbyPlaces(by_category={"history_culture": [SIGHT]}, radius=500, expanded=False)

    async def food(lat, lon, lang="en"):
        calls["food"] += 1
        return [FOOD]

    monkeypatch.setattr(run_bot, "get_nearby_places", nearby)
    monkeypatch.setattr(run_bot, "get_nearby_food", food)
    monkeypatch.setattr(run_bot, "_get_location_name", lambda lat, lon: "Istanbul, Türkiye")
    return calls


def _send_location(update=None) -> SimpleNamespace:
    update = update or _update()
    asyncio.run(run_bot.location(update, _context()))
    return update


def _press_button(data: str, **kwargs) -> SimpleNamespace:
    update = _press(data, **kwargs)
    asyncio.run(run_bot.handle_callback_query(update, _context()))
    return update


def test_location_to_card_to_food_and_back(fake_services):
    update = _send_location()
    text = update.message.reply_text.call_args.args[0]
    assert "Istanbul, Türkiye" in text and "History &amp; Culture (1)" in text

    listing = _press_button("cat:history_culture:0")
    assert "History &amp; Culture" in _shown(listing) and "1–1 of 1" in _shown(listing)

    card = _press_button("pl:history_culture:0")
    assert "Süleymaniye Mosque" in _shown(card) and "Test extract about the mosque." in _shown(card)

    food = _press_button("food")
    assert "Topkapı Kebap" in _shown(food) and "Google Maps" in _shown(food)

    back = _press_button("back")
    assert "History &amp; Culture (1)" in _shown(back)


def test_food_is_requested_from_google_only_once_per_search(fake_services):
    _send_location()
    _press_button("food")
    _press_button("back")
    _press_button("food")
    assert fake_services["food"] == 1  # every request is billed, so a repeat press reuses it

    _send_location()  # a new location starts a new search
    _press_button("food")
    assert fake_services["food"] == 2


def test_food_button_works_when_no_sights_were_found(monkeypatch, fake_services):
    async def nothing(lat, lon, lang="en"):
        return NearbyPlaces(by_category={}, radius=1500, expanded=True)

    monkeypatch.setattr(run_bot, "get_nearby_places", nothing)
    update = _send_location()
    assert "Nothing notable within 1.5 km" in update.message.reply_text.call_args.args[0]

    assert "Topkapı Kebap" in _shown(_press_button("food"))


def test_unavailable_sights_search_tells_the_user_and_keeps_no_session(monkeypatch):
    async def down(lat, lon, lang="en"):
        raise PlacesUnavailable("down")

    monkeypatch.setattr(run_bot, "get_nearby_places", down)
    update = _send_location(_update("ru"))

    assert "Сервис карт сейчас не отвечает" in update.message.reply_text.call_args.args[0]
    assert USER_ID not in run_bot.user_contexts


def test_unavailable_food_search_keeps_the_user_in_the_bot_and_can_be_retried(
    monkeypatch, fake_services
):
    async def down(lat, lon, lang="en"):
        raise PlacesUnavailable("down")

    _send_location()
    monkeypatch.setattr(run_bot, "get_nearby_food", down)
    failed = _press_button("food")
    assert "Google Maps isn't responding" in _shown(failed)

    monkeypatch.setattr(run_bot, "get_nearby_food", lambda lat, lon, lang="en": _food_ok())
    assert "Topkapı Kebap" in _shown(_press_button("food"))  # not cached after a failure


async def _food_ok():
    return [FOOD]


def test_button_without_a_session_asks_to_send_the_location_again():
    update = _press_button("cat:all:0", lang="ru")
    assert "Сессия устарела" in _shown(update)


@pytest.mark.parametrize(
    "data", ["cat:evil:0", "cat:all:abc", "pl:all:999", "pl:history_culture:-1", "garbage", "cat::"]
)
def test_malformed_callback_data_is_ignored_without_errors(data):
    _send_location()
    update = _press_button(data)
    update.callback_query.edit_message_text.assert_not_called()


def test_only_the_most_recent_users_are_kept_in_memory():
    for user_id in range(run_bot.MAX_USERS + 5):
        run_bot._remember(user_id, {"n": user_id})
    assert len(run_bot.user_contexts) == run_bot.MAX_USERS
    assert 0 not in run_bot.user_contexts and run_bot.MAX_USERS + 4 in run_bot.user_contexts


def test_pressing_a_button_keeps_that_user_from_being_evicted():
    run_bot._remember(
        1, {"nearby": NearbyPlaces({}, 500, False), "language": "en", "location": "x"}
    )
    for user_id in range(100, 100 + run_bot.MAX_USERS - 1):
        run_bot._remember(user_id, {})
    asyncio.run(run_bot.handle_callback_query(_press("back", user_id=1), _context()))
    run_bot._remember(999_999, {})  # one more user arrives
    assert 1 in run_bot.user_contexts
