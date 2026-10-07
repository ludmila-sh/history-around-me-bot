from src.run_bot import generate_category_overview, generate_category_places_response

PLACES = {
    "history_culture": [
        {"name": "Kızıl Kule <Red Tower> & Co", "distance": 120.4, "description": "1226 tower"},
    ],
    "food_drinks": [{"name": "Kebab_House *best*", "distance": 300, "description": ""}],
}


def test_overview_escapes_html_in_place_and_location_names():
    text = generate_category_overview(PLACES, "Alanya <Antalya>", "en")["text"]
    assert "Alanya &lt;Antalya&gt;" in text
    assert "<Antalya>" not in text


def test_place_list_escapes_names_and_keeps_markdown_chars_literal():
    response = generate_category_places_response(PLACES["history_culture"], "history_culture")
    assert "Kızıl Kule &lt;Red Tower&gt; &amp; Co" in response["text"]
    assert "(120m)" in response["text"]

    response = generate_category_places_response(PLACES["food_drinks"], "food_drinks")
    assert "Kebab_House *best*" in response["text"]
    assert "\\" not in response["text"]  # no leftover MarkdownV2 escaping
