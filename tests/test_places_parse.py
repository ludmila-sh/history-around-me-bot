import json
from pathlib import Path

import pytest

from src.places_parse import (
    categorize,
    merge_wikipedia,
    parse_overpass,
    parse_wikipedia,
    remove_duplicates,
)

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


def _wikipedia(lang: str) -> list[dict]:
    data = json.loads((FIXTURES / f"wikipedia_{lang}.json").read_text(encoding="utf-8"))
    return parse_wikipedia(data, lang)


def _merged(lang_order: tuple[str, ...] = ("ru", "en", "tr")) -> dict[str, dict]:
    places = list(_parse(lang="en").values())
    pages = [page for lang in lang_order for page in _wikipedia(lang)]
    return {place["name"]: place for place in merge_wikipedia(places, pages)}


def test_wikipedia_pages_keep_fields_apart():
    tower = _wikipedia("ru")[0]
    assert tower["wikidata"] == "Q1001"
    assert tower["title"] == "Красная башня"
    assert tower["url"] == "https://ru.example.org/Kizil"
    assert (tower["latitude"], tower["longitude"]) == (36.5340, 32.0010)


def test_merge_matches_by_wikidata_and_prefers_first_language():
    tower = _merged()["Kızıl Kule"]
    assert tower["wikipedia_lang"] == "ru"
    assert tower["wikipedia_extract"].startswith("Красная башня")


def test_merge_falls_back_to_next_language_when_extract_is_empty():
    mosque = _merged()["Eski Cami"]
    assert mosque["wikipedia_lang"] == "en"
    assert mosque["wikipedia_url"] == "https://en.example.org/Old_Mosque"


def test_merge_matches_by_proximity_and_name_when_osm_has_no_wiki_tags():
    park = _merged()["Atatürk Parkı"]
    assert park["wikipedia_lang"] == "tr"


def test_merge_does_not_attach_unrelated_article_at_same_spot():
    # The "Алания" town article sits at the search point but matches no OSM place.
    merged = _merged()
    assert all("город" not in p.get("wikipedia_extract", "") for p in merged.values())
    assert "wikipedia_extract" not in merged["Museum Cafe"]


def test_merge_never_matches_places_with_different_wikidata():
    place = {
        "name": "Kızıl Kule",
        "wikidata": "Q1",
        "wikipedia": "",
        "latitude": 36.5340,
        "longitude": 32.0010,
    }
    (merged,) = merge_wikipedia([place], _wikipedia("en"))
    assert "wikipedia_extract" not in merged


def test_duplicates_of_same_object_are_merged_but_different_places_kept():
    near = {"name": "Kızıl Kule", "latitude": 36.5340, "longitude": 32.0010}
    same_object = {"name": "kızıl kule", "latitude": 36.5341, "longitude": 32.0011}
    same_name_far = {"name": "Kızıl Kule", "latitude": 36.5400, "longitude": 32.0100}
    other = {"name": "Eski Cami", "latitude": 36.5340, "longitude": 32.0010}

    result = remove_duplicates([near, same_object, same_name_far, other])

    assert result == [near, same_name_far, other]
