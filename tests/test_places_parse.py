import json
from pathlib import Path

import pytest

from src.places_parse import categorize, parse_overpass

FIXTURES = Path(__file__).parent / "fixtures"
ORIGIN = (36.5320, 32.0000)


def _parse(lang: str = "en", radius: int = 500) -> dict[str, dict]:
    data = json.loads((FIXTURES / "overpass_alanya.json").read_text(encoding="utf-8"))
    places = parse_overpass(data, *ORIGIN, radius, lang)
    return {place["name"]: place for place in places}


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"historic": "castle"}, "history_culture"),
        ({"tourism": "museum"}, "history_culture"),
        ({"tourism": "viewpoint"}, "history_culture"),
        ({"amenity": "place_of_worship", "wikidata": "Q1"}, "history_culture"),
        ({"amenity": "place_of_worship"}, None),
        ({"amenity": "cafe"}, "food_drinks"),
        ({"shop": "souvenir"}, "shopping"),
        ({"leisure": "park"}, "parks_nature"),
        ({"natural": "beach"}, "parks_nature"),
        ({"tourism": "hotel"}, None),
        ({"amenity": "school"}, None),
        ({"shop": "supermarket"}, None),
        ({}, None),
    ],
)
def test_category_comes_from_tags(tags, expected):
    assert categorize(tags) == expected


def test_name_never_changes_category():
    # A cafe named after a landmark must stay a cafe, not get a landmark card.
    assert categorize({"amenity": "cafe", "name": "Museum Castle Art Cafe"}) == "food_drinks"


def test_overpass_keeps_only_named_notable_places_within_radius():
    assert set(_parse()) == {
        "Kızıl Kule",
        "Кофе и чай",
        "Eski Cami",
        "Hediyelik",
        "Atatürk Parkı",
        "Museum Cafe",
    }


def test_overpass_cafes_are_food_even_with_landmark_names():
    places = _parse()
    assert places["Кофе и чай"]["category_key"] == "food_drinks"
    assert places["Museum Cafe"]["category_key"] == "food_drinks"


def test_overpass_widening_radius_adds_far_places():
    assert "Far Ruins" not in _parse(radius=500)
    assert "Far Ruins" in _parse(radius=5000)


def test_overpass_uses_name_in_user_language_with_local_fallback():
    assert "Красная башня" in _parse(lang="ru")
    assert "Kızıl Kule" in _parse(lang="en")
    assert "Hediyelik" in _parse(lang="ru")


def test_overpass_place_fields_are_not_swapped():
    tower = _parse()["Kızıl Kule"]
    assert tower["wikidata"] == "Q1001"
    assert tower["wikipedia"] == "tr:Kızıl Kule"
    assert (tower["latitude"], tower["longitude"]) == (36.5340, 32.0010)
    assert 200 < tower["distance"] < 300
    assert tower["category"] == "Historic: Tower"
    shop = _parse()["Hediyelik"]
    assert shop["address"] == "Iskele Caddesi, 7, Alanya"


def test_overpass_places_sorted_by_distance():
    distances = [place["distance"] for place in _parse().values()]
    assert distances == sorted(distances)
