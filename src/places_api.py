import asyncio
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests

from src import places_parse as parse
from src.config.config import app_settings
from src.config.logging_config import get_logger

logger = get_logger(__name__)

# Contact in the User-Agent is required by the Wikimedia and OSM usage policies.
USER_AGENT = "HistoryAroundMeBot/1.0 (https://github.com/ludmila-sh)"
HEADERS = {"User-Agent": USER_AGENT}

OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
)
OPENTRIPMAP_HOST = "opentripmap-places-v1.p.rapidapi.com"  # RapidAPI listing
GOOGLE_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
WIKIPEDIA_API = "https://{lang}.wikipedia.org/w/api.php"

NEAR_RADIUS = 500  # ~5 minutes on foot
WIDE_RADIUS = 1500
MIN_PLACES = 3
MAX_PER_CATEGORY = 10
MAX_FOOD_PLACES = 5
SIGHT_CATEGORIES = {parse.HISTORY, parse.NATURE, parse.VIEWPOINT}
MAX_LOCAL_WIKIS = 1
TOTAL_TIMEOUT = 15  # seconds for the whole search
REQUEST_TIMEOUT = (3, 7)  # connect, read

LANG_CODE = re.compile(r"[a-z]{2,3}")


class PlacesUnavailable(Exception):
    """No place data source answered; different from "nothing interesting nearby"."""


@dataclass
class NearbyPlaces:
    by_category: dict[str, list[dict[str, Any]]]
    radius: int
    expanded: bool  # True when the near radius had too few places and the wide one was used


def describe_error(error: Exception) -> str:
    """Describe a request error without its URL, which may contain user coordinates."""
    if isinstance(error, requests.HTTPError) and error.response is not None:
        host = urlparse(error.response.url).hostname
        return f"HTTP {error.response.status_code} from {host}"
    return type(error).__name__


async def get_nearby_places(lat: float, lon: float, lang: str = "en") -> NearbyPlaces:
    """Find sights near a point: OpenTripMap picks and ranks them, Wikipedia adds the text.

    Overpass (OSM) replaces OpenTripMap if it fails. Food is searched separately, on demand,
    by get_nearby_food. Raises PlacesUnavailable if no source answered in time.
    """
    try:
        async with asyncio.timeout(TOTAL_TIMEOUT):
            radius = NEAR_RADIUS
            places = await _search_sights(lat, lon, radius, lang)
            expanded = len(places) < MIN_PLACES
            if expanded:
                radius = WIDE_RADIUS
                places = await _search_sights(lat, lon, radius, lang)
            pages = await _fetch_wikipedia_pages(lat, lon, lang, places)
    except TimeoutError as e:
        raise PlacesUnavailable("search timed out") from e

    chosen = parse.merge_wikipedia(places, pages)

    # Most notable first (OpenTripMap rate), nearest first among equals; Overpass has no rate.
    by_category: dict[str, list[dict[str, Any]]] = {}
    for place in sorted(chosen, key=lambda p: (-p.get("rate", 0), p["distance"])):
        category_places = by_category.setdefault(place["category_key"], [])
        if len(category_places) < MAX_PER_CATEGORY:
            category_places.append(place)
    logger.info(f"Found {len(chosen)} places within {radius} m (expanded={expanded})")
    return NearbyPlaces(by_category=by_category, radius=radius, expanded=expanded)


async def _search_sights(lat: float, lon: float, radius: int, lang: str) -> list[dict[str, Any]]:
    try:
        # OpenTripMap serves only English and Russian.
        items = await asyncio.to_thread(
            _fetch_opentripmap, lat, lon, radius, lang if lang == "ru" else "en"
        )
        places = parse.parse_opentripmap(items)
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"OpenTripMap failed: {describe_error(e)}; falling back to Overpass")
        osm_places = await _search_osm(lat, lon, radius, lang)
        places = [p for p in osm_places if p["category_key"] in SIGHT_CATEGORIES]
    return parse.remove_duplicates(places)


async def _search_osm(lat: float, lon: float, radius: int, lang: str) -> list[dict[str, Any]]:
    data = await asyncio.to_thread(_fetch_overpass, _overpass_query(lat, lon, radius))
    return parse.parse_overpass(data, lat, lon, radius, lang)


def _regex(values: set[str]) -> str:
    return "^(" + "|".join(sorted(values)) + ")$"


def _overpass_query(lat: float, lon: float, radius: int) -> str:
    around = f"(around:{radius},{lat},{lon})"

    def select(kinds: str, tag_filter: str) -> str:
        return "".join(f"{kind}{tag_filter}{around};" for kind in kinds.split())

    # Cafes and shops are the bulk of the data in a city centre: skipping relations for them
    # keeps the query within the public server's time and rate limits.
    worship = "".join(
        select("nwr", f'["amenity"="place_of_worship"]["{key}"]')
        for key in parse.NOTABLE_WORSHIP_TAGS
    )
    return (
        "[out:json][timeout:10];("
        + select("nwr", '["historic"]')
        + select("nwr", f'["tourism"~"{_regex(parse.HISTORY_TOURISM)}"]')
        + select("nwr", f'["amenity"~"{_regex(parse.HISTORY_AMENITY)}"]')
        + worship
        + select("nwr", f'["leisure"~"{_regex(parse.NATURE_LEISURE)}"]')
        + select("nwr", f'["natural"~"{_regex(parse.NATURE_NATURAL)}"]')
        + select("node way", f'["amenity"~"{_regex(parse.FOOD_AMENITY | {"marketplace"})}"]')
        + select("node way", f'["shop"~"{_regex(parse.SHOPPING_SHOP)}"]')
        + ");out center tags;"
    )


def _fetch_overpass(query: str) -> dict[str, Any]:
    """POST the query to the first Overpass instance that answers."""
    for url in OVERPASS_URLS:
        try:
            response = requests.post(
                url, data={"data": query}, headers=HEADERS, timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as e:
            logger.warning(f"Overpass failed on {urlparse(url).hostname}: {describe_error(e)}")
    raise PlacesUnavailable("all Overpass instances failed")


def _fetch_opentripmap(lat: float, lon: float, radius: int, lang: str) -> list[dict[str, Any]]:
    """Notable sights around a point; `lang` is "en" or "ru", the only languages it serves."""
    response = requests.get(
        f"https://{OPENTRIPMAP_HOST}/{lang}/places/radius",
        params={
            "lon": lon,
            "lat": lat,
            "radius": radius,
            "kinds": "interesting_places",
            "format": "json",
            "limit": 500,
        },
        headers={
            "X-RapidAPI-Key": app_settings.OPENTRIPMAP_API_KEY,
            "X-RapidAPI-Host": OPENTRIPMAP_HOST,
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


# Rating, review count and price are in the Enterprise billing tier; ask for nothing else.
GOOGLE_FOOD_FIELDS = (
    "places.id,places.displayName,places.primaryType,places.types,places.location,"
    "places.rating,places.userRatingCount,places.priceRange"
)
GOOGLE_FOOD_TYPES = ["restaurant", "cafe", "coffee_shop", "bakery"]


def _fetch_google_food(lat: float, lon: float, radius: int, lang: str) -> list[dict[str, Any]]:
    response = requests.post(
        GOOGLE_NEARBY_URL,
        headers={
            "X-Goog-Api-Key": app_settings.GOOGLE_PLACES_API_KEY,
            "X-Goog-FieldMask": GOOGLE_FOOD_FIELDS,
        },
        json={
            "includedTypes": GOOGLE_FOOD_TYPES,
            "maxResultCount": 20,
            "rankPreference": "POPULARITY",
            "languageCode": lang,
            "locationRestriction": {
                "circle": {"center": {"latitude": lat, "longitude": lon}, "radius": radius}
            },
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json().get("places", [])


async def get_nearby_food(lat: float, lon: float, lang: str = "en") -> list[dict[str, Any]]:
    """Best-rated food and coffee places near a point, widening the radius if few qualify.

    Called only when the user opens the food category: each request is billed.
    Raises PlacesUnavailable if Google cannot be reached; there is no fallback source.
    """
    try:
        async with asyncio.timeout(TOTAL_TIMEOUT):
            for radius in (NEAR_RADIUS, WIDE_RADIUS):
                raw = await asyncio.to_thread(_fetch_google_food, lat, lon, radius, lang)
                places = parse.parse_google_food(raw, lat, lon)
                if len(places) >= MIN_PLACES:
                    break
    except TimeoutError as e:
        raise PlacesUnavailable("food search timed out") from e
    except requests.RequestException as e:
        logger.warning(f"Google Places failed: {describe_error(e)}")
        raise PlacesUnavailable("Google Places failed") from e
    logger.info(f"Found {len(places)} food places within {radius} m")
    return places[:MAX_FOOD_PLACES]


def _wikipedia_languages(lang: str, places: list[dict[str, Any]]) -> list[str]:
    """User language, English, then the most common language of the OSM `wikipedia` tags."""
    tagged = Counter(
        place["wikipedia"].split(":", 1)[0] for place in places if ":" in place["wikipedia"]
    )
    local = [code for code, _ in tagged.most_common() if LANG_CODE.fullmatch(code)]
    return list(dict.fromkeys([lang, "en", *local[:MAX_LOCAL_WIKIS]]))


def _fetch_wikipedia(lat: float, lon: float, lang: str) -> dict[str, Any]:
    params = {
        "action": "query",
        "format": "json",
        "generator": "geosearch",
        "ggscoord": f"{lat}|{lon}",
        "ggsradius": WIDE_RADIUS,
        "ggslimit": 20,
        "prop": "extracts|coordinates|pageprops|info",
        "exintro": 1,
        "explaintext": 1,
        "exchars": 600,
        "exlimit": "max",
        "colimit": "max",
        "ppprop": "wikibase_item",
        "inprop": "url",
    }
    response = requests.get(
        WIKIPEDIA_API.format(lang=lang), params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return response.json()


async def _fetch_wikipedia_pages(
    lat: float, lon: float, lang: str, places: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fetch articles in all languages at once; a failing language is skipped, not fatal."""
    langs = _wikipedia_languages(lang, places)
    results = await asyncio.gather(
        *(asyncio.to_thread(_fetch_wikipedia, lat, lon, code) for code in langs),
        return_exceptions=True,
    )
    pages: list[dict[str, Any]] = []
    for code, result in zip(langs, results, strict=True):
        if isinstance(result, Exception):
            logger.warning(f"Wikipedia ({code}) failed: {describe_error(result)}")
            continue
        pages.extend(parse.parse_wikipedia(result, code))
    return pages
