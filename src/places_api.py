import asyncio
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests

from src import places_parse as parse
from src.config.logging_config import get_logger

logger = get_logger(__name__)

# Contact in the User-Agent is required by the Wikimedia and OSM usage policies.
USER_AGENT = "HistoryAroundMeBot/1.0 (https://github.com/ludmila-sh)"
HEADERS = {"User-Agent": USER_AGENT}

OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
)
WIKIPEDIA_API = "https://{lang}.wikipedia.org/w/api.php"

NEAR_RADIUS = 500  # ~5 minutes on foot
WIDE_RADIUS = 1500
MIN_PLACES = 3
MAX_PER_CATEGORY = 10
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
    """Find notable places near a point: OSM decides what and where, Wikipedia adds the text.

    Raises PlacesUnavailable if OSM cannot be reached.
    """
    try:
        async with asyncio.timeout(TOTAL_TIMEOUT):
            radius = NEAR_RADIUS
            places = await _search_osm(lat, lon, radius, lang)
            expanded = len(places) < MIN_PLACES
            if expanded:
                radius = WIDE_RADIUS
                places = await _search_osm(lat, lon, radius, lang)
            pages = await _fetch_wikipedia_pages(lat, lon, lang, places)
    except TimeoutError as e:
        raise PlacesUnavailable("search timed out") from e

    chosen = parse.merge_wikipedia(places, pages)

    by_category: dict[str, list[dict[str, Any]]] = {}
    for place in chosen:
        category_places = by_category.setdefault(place["category_key"], [])
        if len(category_places) < MAX_PER_CATEGORY:
            category_places.append(place)
    logger.info(f"Found {len(chosen)} places within {radius} m (expanded={expanded})")
    return NearbyPlaces(by_category=by_category, radius=radius, expanded=expanded)


async def _search_osm(lat: float, lon: float, radius: int, lang: str) -> list[dict[str, Any]]:
    data = await asyncio.to_thread(_fetch_overpass, _overpass_query(lat, lon, radius))
    places = parse.parse_overpass(data, lat, lon, radius, lang)
    return parse.remove_duplicates(places)


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
