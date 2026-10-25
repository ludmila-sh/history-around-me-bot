import pytest

from src import bot_ui

NO_DESCRIPTION = {"en": "No description available", "ru": "Описания этого места нет"}


def _place(i: int, **extra) -> dict:
    return {
        "name": f"Place {i}",
        "category_key": "history_culture",
        "distance": 100 + i,
        "latitude": 41.0 + i / 1000,
        "longitude": 29.0 + i / 1000,
        "rate": 2,
        **extra,
    }


def _buttons(markup) -> list:
    return [button for row in markup.inline_keyboard for button in row]


def _callbacks(markup) -> list[str]:
    return [b.callback_data for b in _buttons(markup) if b.callback_data]


def _overview(by_category, lang="en", location="Istanbul, Türkiye", radius=500, expanded=False):
    return bot_ui.overview(by_category, location, lang, radius, expanded, 500)


def test_overview_escapes_html_and_shows_counts_without_distance_buttons():
    by_category = {
        "history_culture": [_place(1), _place(2)],
        "parks_nature": [_place(3, category_key="parks_nature")],
    }

    text, markup = _overview(by_category, location="Alanya <Antalya>")

    assert "Alanya &lt;Antalya&gt;" in text and "<Antalya>" not in text
    assert "History &amp; Culture (2)" in text and "Parks &amp; Nature (1)" in text
    assert _callbacks(markup) == [
        "cat:history_culture:0",
        "cat:parks_nature:0",
        "cat:all:0",
        "food",
    ]
    assert not any(c.startswith("distance") for c in _callbacks(markup))


def test_overview_food_is_always_offered_even_when_no_sights_found():
    text, markup = _overview({}, radius=1500, expanded=True)

    assert "Nothing notable within 1.5 km" in text
    assert _callbacks(markup) == ["food"]  # no empty category buttons, but food stays


def test_overview_says_when_the_radius_was_widened():
    text, _ = _overview({"history_culture": [_place(1)]}, lang="ru", radius=1500, expanded=True)
    assert "В радиусе 500 м почти ничего нет, поэтому ищу в радиусе 1.5 км" in text


def test_list_shows_eight_per_page_with_navigation_and_range():
    places = [_place(i) for i in range(20)]

    text, markup = bot_ui.place_list("history_culture", places, 0, "en")
    assert "1–8 of 20" in text
    assert _callbacks(markup)[:8] == [f"pl:history_culture:{i}" for i in range(8)]
    assert "cat:history_culture:1" in _callbacks(markup)  # next
    assert "cat:history_culture:-1" not in _callbacks(markup)  # no previous on the first page

    text, markup = bot_ui.place_list("history_culture", places, 2, "en")
    assert "17–20 of 20" in text
    assert "cat:history_culture:1" in _callbacks(markup)  # previous
    assert "cat:history_culture:3" not in _callbacks(markup)  # no next on the last page


def test_list_clamps_out_of_range_pages():
    places = [_place(i) for i in range(10)]
    text, _ = bot_ui.place_list("all", places, 99, "en")
    assert "9–10 of 10" in text
    text, _ = bot_ui.place_list("all", places, -5, "en")
    assert "1–8 of 10" in text


def test_list_with_a_single_page_has_no_navigation():
    _, markup = bot_ui.place_list("parks_nature", [_place(1), _place(2)], 0, "en")
    assert not any(c.startswith("cat:") for c in _callbacks(markup))
    assert "noop" not in _callbacks(markup)


def test_every_callback_fits_telegrams_64_byte_limit():
    long_names = [_place(i, name="Очень длинное название места " * 5) for i in range(30)]
    screens = [
        _overview({"history_culture": long_names}),
        bot_ui.place_list("history_culture", long_names, 3, "ru"),
        bot_ui.place_card(long_names[29], "history_culture", 29, "ru", "Istanbul, Türkiye"),
    ]
    for _, markup in screens:
        assert all(len(c.encode()) <= 64 for c in _callbacks(markup))
    names = [b.text for b in _buttons(screens[1][1]) if b.callback_data.startswith("pl:")]
    assert all(len(name) < 50 for name in names)  # long names are shortened on buttons


def test_list_escapes_names_and_keeps_special_characters_literal():
    place = _place(1, name="Kızıl Kule <Red Tower> & Co", distance=120.4)
    _, markup = bot_ui.place_list("all", [place], 0, "en")
    assert any(
        "Kızıl Kule <Red Tower> & Co" in b.text for b in _buttons(markup)
    )  # buttons are plain text
    assert any("120 m" in b.text for b in _buttons(markup))


def test_card_shows_extract_source_language_and_links():
    place = _place(
        1,
        name="Kızıl Kule <Red Tower>",
        wikipedia_extract="A tower built in the 13th century & still standing.",
        wikipedia_lang="tr",
        wikipedia_url="https://tr.wikipedia.org/wiki/Kızıl_Kule",
    )

    text, markup = bot_ui.place_card(place, "history_culture", 9, "en", "Alanya, Türkiye")

    assert "<b>Kızıl Kule &lt;Red Tower&gt;</b>" in text
    assert "built in the 13th century &amp; still standing" in text
    assert "Source: Wikipedia article in Turkish" in text
    urls = [b.url for b in _buttons(markup) if b.url]
    assert urls[0].startswith("https://www.google.com/maps/search/") and "Alanya" in urls[0]
    assert urls[1] == "https://tr.wikipedia.org/wiki/Kızıl_Kule"
    assert "cat:history_culture:1" in _callbacks(markup)  # place 9 lives on page 2 of the list


def test_card_without_extract_says_so_instead_of_inventing_a_description():
    text, markup = bot_ui.place_card(_place(1), "all", 0, "en", "Istanbul, Türkiye")
    assert NO_DESCRIPTION["en"] in text
    assert not any("Wikipedia" in b.text for b in _buttons(markup))
    assert any(b.url for b in _buttons(markup))  # the map button is still there


def test_long_extract_is_cut_at_a_sentence_end():
    sentence = "This is a sentence about the place. "
    place = _place(1, wikipedia_extract=sentence * 40, wikipedia_lang="en")
    text, _ = bot_ui.place_card(place, "all", 0, "en", "Istanbul, Türkiye")
    body = text.split("\n\n")[1]
    assert len(body) <= bot_ui.EXTRACT_MAX_CHARS and body.endswith("place.")


@pytest.mark.parametrize(
    ("place", "location", "expected"),
    [
        (
            {"name": "Cafe", "place_id": "ChIJabc"},
            "Istanbul, Türkiye",
            "query=Cafe&query_place_id=ChIJabc",
        ),
        (
            {"name": "Rock & Roll", "latitude": 1.5, "longitude": 2.5},
            "Istanbul, Türkiye",
            "query=Rock+%26+Roll+Istanbul",
        ),
        (
            {"name": "Tower", "latitude": 41.5, "longitude": 28.5},
            "Coordinates: 41.5000, 28.5000",
            "query=41.5,28.5",
        ),
    ],
)
def test_maps_url_prefers_place_id_then_name_with_city_then_coordinates(place, location, expected):
    url = bot_ui.maps_url(place, location)
    assert url.startswith("https://www.google.com/maps/search/?api=1")
    assert expected in url


def test_food_screen_credits_google_and_shows_rating_price_and_map_links():
    places = [
        {
            "name": "Kebab <House>",
            "rating": 4.7,
            "review_count": 329,
            "price": "₺400–600",
            "distance": 446,
            "place_id": "ChIJ1",
        },
        {
            "name": "No Price Cafe",
            "rating": 4.5,
            "review_count": 156,
            "price": "",
            "distance": 158,
            "place_id": "ChIJ2",
        },
    ]

    text, markup = bot_ui.food_screen(places, "en", "Istanbul, Türkiye")

    assert "Google Maps" in text  # required next to Google's data
    assert "Kebab &lt;House&gt;" in text
    assert "⭐ 4.7 (329) · ₺400–600 · 450 m" in text
    assert "⭐ 4.5 (156) · 160 m" in text  # no empty price slot
    urls = [b.url for b in _buttons(markup) if b.url]
    assert (
        len(urls) == 2 and "query_place_id=ChIJ1" in urls[0] and "query_place_id=ChIJ2" in urls[1]
    )


def test_food_screen_with_no_places_says_so_and_offers_a_way_back():
    text, markup = bot_ui.food_screen([], "ru", "Istanbul, Türkiye")
    assert "достаточным числом отзывов" in text
    assert _callbacks(markup) == ["back"]


def test_all_scope_orders_by_notability_then_distance_across_categories():
    by_category = {
        "history_culture": [_place(1, rate=2, distance=50), _place(2, rate=7, distance=400)],
        "parks_nature": [_place(3, rate=3, distance=10, category_key="parks_nature")],
        "food_drinks": [_place(4, rate=9, distance=1)],  # food is never mixed into sights
    }
    names = [p["name"] for p in bot_ui.sights_in_scope(by_category, "all")]
    assert names == ["Place 2", "Place 3", "Place 1"]
    assert bot_ui.sights_in_scope(by_category, "parks_nature") == by_category["parks_nature"]


@pytest.mark.parametrize(
    ("meters", "lang", "expected"),
    [(42, "en", "42 m"), (126.4, "ru", "130 м"), (999, "en", "1.0 km"), (1500, "en", "1.5 km")],
)
def test_distance_formatting(meters, lang, expected):
    assert bot_ui.format_distance(meters, lang) == expected


def test_both_languages_have_the_same_texts():
    assert bot_ui.TEXTS["en"].keys() == bot_ui.TEXTS["ru"].keys()
    assert bot_ui.TEXTS["en"]["languages"].keys() == bot_ui.TEXTS["ru"]["languages"].keys()


def test_every_html_screen_escapes_ampersands_in_category_names():
    # "History & Culture" must reach Telegram as "&amp;" or HTML parsing may be rejected.
    places = [_place(1)]
    screens = {
        "overview": _overview({"history_culture": places, "parks_nature": places})[0],
        "empty overview": _overview({})[0],
        "list": bot_ui.place_list("history_culture", places, 0, "en")[0],
        "card": bot_ui.place_card(places[0], "history_culture", 0, "en", "Istanbul, Türkiye")[0],
        "food": bot_ui.food_screen([], "en", "Istanbul, Türkiye")[0],
    }
    for name, text in screens.items():
        assert " & " not in text, name


def test_extract_cut_by_wikipedia_is_trimmed_to_a_whole_sentence():
    api_cut = "The mosque was built in 1557. It has a large dome. It was damaged by fi..."
    place = _place(1, wikipedia_extract=api_cut, wikipedia_lang="en")

    text, _ = bot_ui.place_card(place, "all", 0, "en", "Istanbul, Türkiye")

    assert "It has a large dome." in text and "damaged" not in text and "..." not in text


def test_source_line_names_the_article_language_in_the_users_language():
    place = _place(1, wikipedia_extract="Text.", wikipedia_lang="en")
    ru_text, _ = bot_ui.place_card(place, "all", 0, "ru", "Стамбул, Турция")
    en_text, _ = bot_ui.place_card(place, "all", 0, "en", "Istanbul, Türkiye")
    assert "Источник: статья Википедии на английском" in ru_text
    assert "Source: Wikipedia article in English" in en_text
