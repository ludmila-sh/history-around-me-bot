import json
from pathlib import Path

import pytest

from src.places_parse import (
    categorize,
    merge_wikipedia,
    otm_category,
    parse_opentripmap,
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


def _otm(name: str) -> list[dict]:
    return json.loads((FIXTURES / f"otm_{name}.json").read_text(encoding="utf-8"))


def _otm_places(name: str) -> dict[str, dict]:
    return {place["name"]: place for place in parse_opentripmap(_otm(name))}


@pytest.mark.parametrize(
    ("kinds", "expected"),
    [
        ("religion,mosques,interesting_places", "history_culture"),
        ("cultural,museums,interesting_places,art_galleries", "history_culture"),
        ("historic,archaeology,interesting_places", "history_culture"),
        ("urban_environment,gardens_and_parks,cultural,interesting_places", "parks_nature"),
        ("mountain_peaks,geological_formations,natural,interesting_places", "parks_nature"),
        ("view_points,other,interesting_places", "viewpoints"),
        # A restaurant tagged as a museum must not become a sight: food comes from Google.
        ("cultural,museums,interesting_places,restaurants,foods", None),
        ("cultural,theatres_and_entertainments,cinemas,interesting_places", None),
        ("other,unclassified_objects,interesting_places,tourist_object", None),
    ],
)
def test_opentripmap_kinds_map_to_categories(kinds, expected):
    assert otm_category(kinds) == expected


def test_opentripmap_residential_area_has_nothing_notable():
    # Bakırköy: 5 named places, all rate 1 (no Wikidata entry). The bot must say "nothing".
    assert _otm("bakirkoy") and parse_opentripmap(_otm("bakirkoy")) == []


def test_opentripmap_keeps_best_known_place_and_sorts_by_distance():
    places = _otm_places("suleymaniye")
    mosque = places["Süleymaniye Mosque"]
    assert mosque["rate"] == 7 and mosque["category_key"] == "history_culture"
    assert places["Alfred Heilbronn Botanical Garden"]["category_key"] == "parks_nature"
    assert all(place["rate"] >= 2 for place in places.values())
    distances = [place["distance"] for place in parse_opentripmap(_otm("suleymaniye"))]
    assert distances == sorted(distances)


def test_opentripmap_drops_food_places_tagged_as_sights():
    names = _otm_places("istiklal")
    assert "Nizam Pide Galatasaray" not in names and "pera" not in names
    assert "Pera Museum" in names


def test_opentripmap_place_fields_are_not_swapped():
    mosque = _otm_places("suleymaniye")["Süleymaniye Mosque"]
    assert mosque["wikidata"] == "Q178643"
    assert mosque["xid"] == "R1564032"
    assert (mosque["latitude"], mosque["longitude"]) == (41.016300201416016, 28.963977813720703)
    assert 100 < mosque["distance"] < 150
    assert mosque["category"] == "Religion: Mosques"


def test_opentripmap_same_mosque_mapped_twice_is_shown_once():
    raw = [
        p for p in parse_opentripmap(_otm("karagumruk")) if p["name"] == "Kara Ahmet Pasha Mosque"
    ]
    assert len(raw) == 2
    deduped = remove_duplicates(parse_opentripmap(_otm("karagumruk")))
    assert [p["name"] for p in deduped].count("Kara Ahmet Pasha Mosque") == 1


def test_opentripmap_rate_tolerates_heritage_suffix_and_skips_incomplete_items():
    items = [
        {"name": "A", "kinds": "historic", "rate": "2h", "point": {"lat": 1, "lon": 2}, "dist": 5},
        {"name": "B", "kinds": "historic", "rate": 3, "dist": 5},  # no coordinates
        {"name": "", "kinds": "historic", "rate": 3, "point": {"lat": 1, "lon": 2}},  # no name
    ]
    assert [p["name"] for p in parse_opentripmap(items)] == ["A"]
