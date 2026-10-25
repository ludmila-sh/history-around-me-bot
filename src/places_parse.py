"""Pure parsing of OSM responses into place dicts: no network, no I/O."""

import math
from typing import Any

HISTORY = "history_culture"
FOOD = "food_drinks"
SHOPPING = "shopping"
NATURE = "parks_nature"
VIEWPOINT = "viewpoints"

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

# OpenTripMap rate: 1 is mostly places without a Wikidata entry, 2-3 notable, 7 the best known.
OTM_MIN_RATE = 2
# Top-level OpenTripMap kinds (https://dev.opentripmap.org/catalog). Food comes from Google.
OTM_EXCLUDED_KINDS = {"foods", "restaurants", "tourist_facilities", "cinemas", "destroyed_objects"}
OTM_NATURE_KINDS = {"gardens_and_parks", "natural"}
OTM_HISTORY_KINDS = {
    "religion",
    "cultural",
    "historic",
    "architecture",
    "museums",
    "fortifications",
    "archaeology",
}
OTM_VIEW_KINDS = {"view_points"}


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
    """Drop the same object mapped twice (e.g. as a node and a way) within 75 m.

    Copies share a name or a Wikidata id (names differ when one copy is in another language).
    `places` must be sorted by distance, so the nearest copy is kept.
    """

    def is_same(place: dict[str, Any], kept: dict[str, Any]) -> bool:
        wikidata = place.get("wikidata")
        same_object = _normalize(kept["name"]) == _normalize(place["name"]) or (
            bool(wikidata) and wikidata == kept.get("wikidata")
        )
        return same_object and (
            distance_m(place["latitude"], place["longitude"], kept["latitude"], kept["longitude"])
            < 75
        )

    unique: list[dict[str, Any]] = []
    for place in places:
        is_copy = any(is_same(place, kept) for kept in unique)
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


def otm_category(kinds: str) -> str | None:
    """Map OpenTripMap `kinds` (comma-separated) to a bot category, or None to skip the place."""
    parts = set(kinds.split(","))
    if parts & OTM_EXCLUDED_KINDS:
        return None
    if parts & OTM_NATURE_KINDS:
        return NATURE
    if parts & OTM_HISTORY_KINDS:
        return HISTORY
    if parts & OTM_VIEW_KINDS:
        return VIEWPOINT
    return None


def _otm_rate(item: dict[str, Any]) -> int:
    """Rate as int; tolerates the documented "2h" form (h marks cultural heritage)."""
    return int(str(item.get("rate", 0)).rstrip("h") or 0)


def _otm_display_category(kinds: str) -> str:
    parts = [kind for kind in kinds.split(",") if kind and kind != "interesting_places"]
    if not parts:
        return ""
    names = [kind.replace("_", " ").title() for kind in dict.fromkeys((parts[0], parts[-1]))]
    return ": ".join(names)


def parse_opentripmap(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn an OpenTripMap `radius` response into notable, named, categorized places."""
    places = []
    for item in items:
        name = item.get("name", "")
        category_key = otm_category(item.get("kinds", ""))
        point = item.get("point")
        if not name or not category_key or not point or _otm_rate(item) < OTM_MIN_RATE:
            continue
        places.append(
            {
                "name": name,
                "category_key": category_key,
                "category": _otm_display_category(item["kinds"]),
                "description": "",
                "address": "",
                "latitude": point["lat"],
                "longitude": point["lon"],
                "distance": item.get("dist", 0),
                "source": "opentripmap",
                "rate": _otm_rate(item),
                "xid": item.get("xid", ""),
                "wikipedia": "",
                "wikidata": item.get("wikidata", ""),
            }
        )
    return sorted(places, key=lambda place: place["distance"])


# Google food ranking: ratings are shrunk toward PRIOR_RATING by PRIOR_REVIEWS imaginary votes,
# so 4.9 from 60 reviews does not beat 4.6 from 4000.
MIN_REVIEWS = 50
PRIOR_REVIEWS = 50
PRIOR_RATING = 4.0
CURRENCY_SYMBOLS = {"TRY": "₺", "USD": "$", "EUR": "€", "GBP": "£", "RUB": "₽", "JPY": "¥"}


def rating_score(rating: float, reviews: int) -> float:
    return (rating * reviews + PRIOR_RATING * PRIOR_REVIEWS) / (reviews + PRIOR_REVIEWS)


def format_price_range(price_range: dict[str, Any] | None) -> str:
    """ "₺400–1400", "₺2000+" for an open range, "CHF 20–40" for a currency without a symbol."""
    start = (price_range or {}).get("startPrice")
    if not start:
        return ""
    code = start["currencyCode"]
    prefix = CURRENCY_SYMBOLS.get(code, f"{code} ")
    end = price_range.get("endPrice")
    if not end:
        return f"{prefix}{start['units']}+"
    return f"{prefix}{start['units']}–{end['units']}"


def parse_google_food(
    google_places: list[dict[str, Any]], lat: float, lon: float
) -> list[dict[str, Any]]:
    """Turn Places API (New) nearby results into food places, best first.

    Dropped: hotels (lodging), places with few reviews. The price is empty when Google has none.
    """
    places = []
    for item in google_places:
        reviews = item.get("userRatingCount", 0)
        rating = item.get("rating")
        name = item.get("displayName", {}).get("text", "")
        location = item.get("location")
        if (
            not name
            or not location
            or rating is None
            or reviews < MIN_REVIEWS
            or "lodging" in item.get("types", [])
        ):
            continue
        places.append(
            {
                "name": name,
                "category_key": FOOD,
                "category": item.get("primaryType", "").replace("_", " ").title(),
                "description": "",
                "address": "",
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "distance": distance_m(lat, lon, location["latitude"], location["longitude"]),
                "source": "google",
                "rating": rating,
                "review_count": reviews,
                "price": format_price_range(item.get("priceRange")),
                "place_id": item.get("id", ""),
                "wikipedia": "",
                "wikidata": "",
            }
        )
    return sorted(
        places,
        key=lambda place: (
            -rating_score(place["rating"], place["review_count"]),
            place["distance"],
        ),
    )
