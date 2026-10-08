"""Pure parsing of OSM responses into place dicts: no network, no I/O."""

import math
from typing import Any

HISTORY = "history_culture"
FOOD = "food_drinks"
SHOPPING = "shopping"
NATURE = "parks_nature"

HISTORY_TOURISM = {"attraction", "museum", "gallery", "viewpoint", "artwork"}
HISTORY_AMENITY = {"theatre", "arts_centre"}
FOOD_AMENITY = {"restaurant", "cafe", "bar", "pub", "fast_food", "ice_cream"}
SHOPPING_SHOP = {
    "books",
    "art",
    "antiques",
    "gift",
    "souvenir",
    "craft",
    "jewelry",
    "carpet",
    "ceramics",
    "tea",
    "spices",
    "confectionery",
}
NATURE_LEISURE = {"park", "garden", "nature_reserve"}
NATURE_NATURAL = {"beach", "peak", "cave_entrance", "waterfall"}

# Tags that make a mosque or church a landmark; ordinary neighbourhood ones are skipped.
NOTABLE_WORSHIP_TAGS = ("wikidata", "wikipedia", "heritage", "historic")

DISPLAY_KEYS = ("historic", "tourism", "amenity", "leisure", "natural", "shop")


def categorize(tags: dict[str, str]) -> str | None:
    """Return the bot category for OSM tags, or None if the place is not worth showing.

    Only tags decide: a name like "Museum Cafe" never turns a cafe into a landmark.
    """
    amenity = tags.get("amenity")
    if tags.get("historic") or tags.get("tourism") in HISTORY_TOURISM or amenity in HISTORY_AMENITY:
        return HISTORY
    if amenity == "place_of_worship":
        return HISTORY if any(tags.get(key) for key in NOTABLE_WORSHIP_TAGS) else None
    if tags.get("leisure") in NATURE_LEISURE or tags.get("natural") in NATURE_NATURAL:
        return NATURE
    if amenity in FOOD_AMENITY:
        return FOOD
    if tags.get("shop") in SHOPPING_SHOP or amenity == "marketplace":
        return SHOPPING
    return None


def best_name(tags: dict[str, str], lang: str) -> str:
    """Name in the user's language, then the local name, then English."""
    for key in (f"name:{lang}", "name", "name:en"):
        if tags.get(key):
            return tags[key]
    return ""


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in meters."""
    earth_radius = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return earth_radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _display_category(tags: dict[str, str]) -> str:
    for key in DISPLAY_KEYS:
        if tags.get(key):
            return f"{key.title()}: {tags[key].replace('_', ' ').title()}"
    return ""


def _format_address(tags: dict[str, str]) -> str:
    keys = ("addr:street", "addr:housenumber", "addr:city")
    return ", ".join(tags[key] for key in keys if tags.get(key))


def parse_overpass(
    data: dict[str, Any], lat: float, lon: float, radius: int, lang: str
) -> list[dict[str, Any]]:
    """Turn an Overpass JSON response into categorized places within `radius` of the point."""
    places = []
    for element in data.get("elements", []):
        point = element if element.get("type") == "node" else element.get("center")
        if not point:
            continue
        tags = element.get("tags", {})
        category_key = categorize(tags)
        name = best_name(tags, lang)
        if not category_key or not name:
            continue
        distance = distance_m(lat, lon, point["lat"], point["lon"])
        if distance > radius:
            continue
        places.append(
            {
                "name": name,
                "category_key": category_key,
                "category": _display_category(tags),
                "description": tags.get("description", ""),
                "address": _format_address(tags),
                "latitude": point["lat"],
                "longitude": point["lon"],
                "distance": distance,
                "source": "openstreetmap",
                "wikipedia": tags.get("wikipedia", ""),
                "wikidata": tags.get("wikidata", ""),
            }
        )
    return sorted(places, key=lambda place: place["distance"])


def remove_duplicates(places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop the same object mapped twice (e.g. as a node and a way): same name within 75 m.

    `places` must be sorted by distance, so the nearest copy is kept.
    """
    unique: list[dict[str, Any]] = []
    for place in places:
        name = _normalize(place["name"])
        is_copy = any(
            _normalize(kept["name"]) == name
            and distance_m(
                place["latitude"], place["longitude"], kept["latitude"], kept["longitude"]
            )
            < 75
            for kept in unique
        )
        if not is_copy:
            unique.append(place)
    return unique


def parse_wikipedia(data: dict[str, Any], lang: str) -> list[dict[str, Any]]:
    """Turn a geosearch-generator response (extracts, coordinates, pageprops) into pages."""
    pages = []
    for page in data.get("query", {}).get("pages", {}).values():
        coordinates = page.get("coordinates")
        if not coordinates:
            continue
        pages.append(
            {
                "lang": lang,
                "title": page.get("title", ""),
                "latitude": coordinates[0]["lat"],
                "longitude": coordinates[0]["lon"],
                "wikidata": page.get("pageprops", {}).get("wikibase_item", ""),
                "extract": page.get("extract", "").strip(),
                "url": page.get("fullurl", ""),
            }
        )
    return pages


def _normalize(name: str) -> str:
    return "".join(char for char in name.casefold() if char.isalnum())


def _is_same_place(place: dict[str, Any], page: dict[str, Any]) -> bool:
    if place["wikidata"] and page["wikidata"]:
        return place["wikidata"] == page["wikidata"]
    if place["wikipedia"] == f"{page['lang']}:{page['title']}":
        return True
    if distance_m(place["latitude"], place["longitude"], page["latitude"], page["longitude"]) > 75:
        return False
    place_name, page_title = _normalize(place["name"]), _normalize(page["title"])
    return bool(place_name and page_title) and (
        place_name in page_title or page_title in place_name
    )


def merge_wikipedia(
    places: list[dict[str, Any]], pages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Attach the first non-empty extract to each OSM place.

    `pages` must be ordered by language priority (user language first). Articles that match
    no OSM place are dropped: OSM tags decide whether something is worth showing.
    """
    for place in places:
        for page in pages:
            if page["extract"] and _is_same_place(place, page):
                place["wikipedia_extract"] = page["extract"]
                place["wikipedia_url"] = page["url"]
                place["wikipedia_lang"] = page["lang"]
                break
    return places
