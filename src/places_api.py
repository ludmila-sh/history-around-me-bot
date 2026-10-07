import math
from typing import Any
from urllib.parse import urlparse

import requests

from src.config.logging_config import get_logger

logger = get_logger(__name__)


def describe_error(error: Exception) -> str:
    """Describe a request error without its URL, which may contain user coordinates."""
    if isinstance(error, requests.HTTPError) and error.response is not None:
        host = urlparse(error.response.url).hostname
        return f"HTTP {error.response.status_code} from {host}"
    return type(error).__name__


def get_nearby_places(
    lat: float, lon: float, radius: int = 10000, lang: str = "en"
) -> dict[str, list[dict[Any, Any]]]:
    """Get nearby places from OpenStreetMap and Wikipedia, grouped by category."""
    all_places = []
    for source, fetch in (("OSM", _get_osm_places_improved), ("Wikipedia", _get_wikipedia_places)):
        try:
            places = fetch(lat, lon, radius, lang)
        except Exception as e:
            logger.warning(f"{source} failed: {describe_error(e)}")
            continue
        logger.info(f"Found {len(places)} places from {source}")
        all_places.extend(places)

    if not all_places:
        logger.warning("All POI sources failed or returned no results")
        return {}

    unique_places = _remove_duplicate_places(all_places)
    categorized_places = _categorize_places(unique_places)
    for category in categorized_places:
        categorized_places[category].sort(key=lambda x: x["distance"])
    return categorized_places


def _get_osm_places_improved(
    lat: float, lon: float, radius: int, lang: str = "en"
) -> list[dict[Any, Any]]:
    """
    Improved OpenStreetMap query with broader categories and larger radius.
    """
    overpass_url = "http://overpass-api.de/api/interpreter"

    # More comprehensive query including shops, restaurants, and broader categories
    overpass_query = f"""
    [out:json][timeout:30];
    (
      node["tourism"~"^(attraction|museum|gallery|viewpoint|monument|memorial|artwork|castle|ruins|information|hotel|hostel)$"](around:{radius},{lat},{lon});
      node["historic"~"^(monument|memorial|castle|ruins|archaeological_site|building|manor|palace|city_gate|fort|tower)$"](around:{radius},{lat},{lon});
      node["amenity"~"^(museum|gallery|theatre|arts_centre|library|university|school|place_of_worship|restaurant|cafe|bar|pub)$"](around:{radius},{lat},{lon});
      node["leisure"~"^(park|garden|playground|sports_centre|stadium)$"](around:{radius},{lat},{lon});
      node["shop"~"^(books|art|antiques|gift|souvenir)$"](around:{radius},{lat},{lon});
      way["tourism"~"^(attraction|museum|gallery|viewpoint|monument|memorial|artwork|castle|ruins)$"](around:{radius},{lat},{lon});
      way["historic"~"^(monument|memorial|castle|ruins|archaeological_site|building|manor|palace|city_gate|fort|tower)$"](around:{radius},{lat},{lon});
      way["amenity"~"^(museum|gallery|theatre|arts_centre|library|university|place_of_worship)$"](around:{radius},{lat},{lon});
      way["leisure"~"^(park|garden|sports_centre|stadium)$"](around:{radius},{lat},{lon});
    );
    out center meta;
    """

    try:
        response = requests.post(overpass_url, data=overpass_query, timeout=30)
        response.raise_for_status()
        data = response.json()

        places = []
        seen_names = set()  # Avoid duplicates

        for element in data.get("elements", []):
            # Extract coordinates
            if element["type"] == "node":
                place_lat, place_lon = element["lat"], element["lon"]
            elif element["type"] == "way" and "center" in element:
                place_lat, place_lon = element["center"]["lat"], element["center"]["lon"]
            else:
                continue

            tags = element.get("tags", {})
            name = _get_best_name(tags, lang)

            # Skip if no name or duplicate
            if not name or name == "Unknown Place" or name in seen_names:
                continue

            seen_names.add(name)
            distance = _calculate_distance(lat, lon, place_lat, place_lon)

            if distance > radius:
                continue

            # Determine category
            category = "Point of Interest"
            if tags.get("tourism"):
                category = f"Tourism: {tags['tourism'].title()}"
            elif tags.get("historic"):
                category = f"Historic: {tags['historic'].title()}"
            elif tags.get("amenity"):
                category = f"Amenity: {tags['amenity'].title()}"
            elif tags.get("leisure"):
                category = f"Leisure: {tags['leisure'].title()}"

            place = {
                "name": name,
                "description": tags.get("description", ""),
                "address": _format_address(tags),
                "latitude": place_lat,
                "longitude": place_lon,
                "distance": distance,
                "source": "openstreetmap",
                "category": category,
                "wikipedia": tags.get("wikipedia", ""),
                "wikidata": tags.get("wikidata", ""),
            }
            places.append(place)

        # Sort by distance and return more results for 10km search
        return sorted(places, key=lambda x: x["distance"])[:30]

    except Exception as e:
        logger.error(f"OSM Overpass API error: {describe_error(e)}")
        return []


def _get_wikipedia_places(
    lat: float, lon: float, radius: int, lang: str = "en"
) -> list[dict[Any, Any]]:
    """
    Get places from Wikipedia geosearch API and fetch extracts for each place.
    """
    if lang == "ru":
        url = "https://ru.wikipedia.org/w/api.php"
    else:
        url = "https://en.wikipedia.org/w/api.php"

    # First, get nearby places
    params = {
        "action": "query",
        "list": "geosearch",
        "gscoord": f"{lat}|{lon}",
        "gsradius": min(radius, 10000),  # Wikipedia max is 10km
        "gslimit": 20,
        "format": "json",
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        places = []
        page_ids = []

        # Collect places and page IDs
        for page in data.get("query", {}).get("geosearch", []):
            distance = page.get("dist", 0)
            if distance > radius:
                continue

            page_ids.append(str(page.get("pageid")))

            place = {
                "name": page.get("title", "Unknown Place"),
                "description": "Wikipedia Article",
                "address": f"~{distance}m away",
                "latitude": page.get("lat", lat),
                "longitude": page.get("lon", lon),
                "distance": distance,
                "source": "wikipedia",
                "category": "Encyclopedia Entry",
                "wikipedia_title": page.get("title", ""),
                "pageid": page.get("pageid", 0),
            }
            places.append(place)

        # If we have page IDs, fetch extracts for them
        if page_ids:
            # Get extracts for all pages in one request
            extract_params = {
                "action": "query",
                "prop": "extracts|info",
                "exintro": 1,  # Only get intro paragraph
                "explaintext": 1,  # Get plain text
                "pageids": "|".join(page_ids),
                "inprop": "url",  # Get URL
                "format": "json",
            }

            try:
                extract_response = requests.get(url, params=extract_params, timeout=15)
                extract_response.raise_for_status()
                extract_data = extract_response.json()

                # Add extracts to places
                for place in places:
                    pageid = place.get("pageid")
                    if pageid and str(pageid) in extract_data.get("query", {}).get("pages", {}):
                        page_data = extract_data["query"]["pages"][str(pageid)]
                        place["wikipedia_extract"] = page_data.get("extract", "")
                        place["wikipedia_url"] = page_data.get("fullurl", "")

                        # Set category based on extract content
                        if place["wikipedia_extract"]:
                            place["description"] = place["wikipedia_extract"][:100] + "..."

                            # Determine if it's a historical place
                            historical_keywords = [
                                "history",
                                "historic",
                                "ancient",
                                "century",
                                "built",
                                "castle",
                                "monument",
                                "memorial",
                                "museum",
                                "palace",
                                "ruins",
                            ]

                            extract_lower = place["wikipedia_extract"].lower()
                            if any(keyword in extract_lower for keyword in historical_keywords):
                                place["category"] = "Historical Site"

            except Exception as e:
                logger.error(f"Wikipedia extract fetch failed: {describe_error(e)}")

        return sorted(places, key=lambda x: x["distance"])[:8]

    except Exception as e:
        logger.error(f"Wikipedia geosearch failed: {describe_error(e)}")
        return []


def _remove_duplicate_places(places: list[dict[Any, Any]]) -> list[dict[Any, Any]]:
    """
    Remove duplicate places based on name similarity and proximity (within 50m).
    """
    if not places:
        return []

    unique_places = []
    seen_names = set()

    for place in places:
        name = place.get("name", "").lower().strip()
        lat = place.get("latitude", 0)
        lon = place.get("longitude", 0)

        # Skip if no name
        if not name or len(name) < 2:
            continue

        # Check for exact name duplicates
        if name in seen_names:
            continue

        # Check for proximity duplicates (within 50m)
        is_duplicate = False
        for existing_place in unique_places:
            existing_lat = existing_place.get("latitude", 0)
            existing_lon = existing_place.get("longitude", 0)

            # Calculate distance between places
            distance = _calculate_distance(lat, lon, existing_lat, existing_lon)

            # If within 50m and similar names, consider duplicate
            if distance < 50:
                existing_name = existing_place.get("name", "").lower().strip()
                # Check if names are similar (one contains the other or very similar)
                if (
                    name in existing_name
                    or existing_name in name
                    or _names_are_similar(name, existing_name)
                ):
                    is_duplicate = True
                    break

        if not is_duplicate:
            unique_places.append(place)
            seen_names.add(name)

    return unique_places


def _names_are_similar(name1: str, name2: str) -> bool:
    """
    Check if two place names are similar enough to be considered duplicates.
    """
    # Remove common words and punctuation
    import re

    def clean_name(name):
        # Remove common words and normalize
        common_words = {"the", "of", "and", "church", "museum", "park", "street", "square"}
        words = re.findall(r"\w+", name.lower())
        return " ".join([w for w in words if w not in common_words])

    clean1 = clean_name(name1)
    clean2 = clean_name(name2)

    if not clean1 or not clean2:
        return False

    # Check if one is contained in the other
    if clean1 in clean2 or clean2 in clean1:
        return True

    # Check for high similarity (simple word overlap)
    words1 = set(clean1.split())
    words2 = set(clean2.split())

    if len(words1) == 0 or len(words2) == 0:
        return False

    overlap = len(words1.intersection(words2))
    total_unique = len(words1.union(words2))

    # If more than 60% overlap, consider similar
    similarity = overlap / total_unique if total_unique > 0 else 0
    return similarity > 0.6


def _categorize_places(places: list[dict[Any, Any]]) -> dict[str, list[dict[Any, Any]]]:
    """
    Categorize places into main categories for user discovery.
    """
    categories = {
        "history_culture": [],
        "food_drinks": [],
        "shopping": [],
        "parks_nature": [],
        "entertainment": [],
        "other": [],
    }

    for place in places:
        category = _determine_place_category(place)
        categories[category].append(place)

    # Remove empty categories
    return {k: v for k, v in categories.items() if v}


def _determine_place_category(place: dict[Any, Any]) -> str:
    """
    Determine the category of a place based on its properties.
    """
    name = place.get("name", "").lower()
    description = place.get("description", "").lower()
    category = place.get("category", "").lower()

    # Check for historical/cultural keywords
    history_keywords = [
        "museum",
        "castle",
        "church",
        "cathedral",
        "monument",
        "memorial",
        "historic",
        "archaeological",
        "palace",
        "fort",
        "tower",
        "ruins",
        "gallery",
        "art",
        "culture",
        "heritage",
        "temple",
        "synagogue",
        "mosque",
        "basilica",
        "abbey",
        "monastery",
        "library",
        "theatre",
        "opera",
        "concert",
        "university",
        "school",
        "historic",
    ]

    # Check for food/drinks keywords
    food_keywords = [
        "restaurant",
        "cafe",
        "bar",
        "pub",
        "bistro",
        "pizzeria",
        "bakery",
        "food",
        "dining",
        "kitchen",
        "grill",
        "tavern",
        "brewery",
        "wine",
        "coffee",
        "tea",
        "lunch",
        "dinner",
        "breakfast",
        "fast food",
        "street food",
        "market",
        "deli",
    ]

    # Check for shopping keywords
    shopping_keywords = [
        "shop",
        "store",
        "market",
        "mall",
        "boutique",
        "souvenir",
        "gift",
        "antique",
        "books",
        "art",
        "craft",
        "shopping",
        "retail",
        "center",
    ]

    # Check for parks/nature keywords
    nature_keywords = [
        "park",
        "garden",
        "forest",
        "lake",
        "river",
        "beach",
        "nature",
        "botanical",
        "zoo",
        "playground",
        "green",
        "square",
        "plaza",
    ]

    # Check for entertainment keywords
    entertainment_keywords = [
        "cinema",
        "theater",
        "club",
        "disco",
        "entertainment",
        "sports",
        "stadium",
        "gym",
        "fitness",
        "bowling",
        "arcade",
        "casino",
        "nightlife",
        "music",
        "venue",
        "hall",
    ]

    # Combine all text for checking
    all_text = f"{name} {description} {category}".lower()

    # Check categories in order of priority
    if any(keyword in all_text for keyword in history_keywords):
        return "history_culture"
    elif any(keyword in all_text for keyword in food_keywords):
        return "food_drinks"
    elif any(keyword in all_text for keyword in shopping_keywords):
        return "shopping"
    elif any(keyword in all_text for keyword in nature_keywords):
        return "parks_nature"
    elif any(keyword in all_text for keyword in entertainment_keywords):
        return "entertainment"
    else:
        return "other"


def _format_address(tags: dict) -> str:
    """
    Format address from OSM tags.
    """
    address_parts = []
    for key in ["addr:housenumber", "addr:street", "addr:city", "addr:country"]:
        if tags.get(key):
            address_parts.append(tags[key])
    return ", ".join(address_parts) if address_parts else ""


def _get_best_name(tags: dict, preferred_lang: str = "en") -> str:
    """
    Get the best name for a place based on user's language preference.
    Priority: name:en/name:ru > inscription:en/inscription:ru > name > fallback
    """
    # Priority 1: Localized name in preferred language
    if preferred_lang == "ru" and tags.get("name:ru"):
        return tags["name:ru"]
    elif preferred_lang == "en" and tags.get("name:en"):
        return tags["name:en"]

    # Priority 2: Inscription in preferred language (for monuments/memorials)
    if preferred_lang == "ru" and tags.get("inscription:ru"):
        return tags["inscription:ru"]
    elif preferred_lang == "en" and tags.get("inscription:en"):
        return tags["inscription:en"]

    # Priority 3: Try the other language if preferred not available
    if preferred_lang == "ru" and tags.get("name:en"):
        return tags["name:en"]
    elif preferred_lang == "en" and tags.get("name:ru"):
        return tags["name:ru"]

    # Priority 4: Try inscriptions in other language
    if preferred_lang == "ru" and tags.get("inscription:en"):
        return tags["inscription:en"]
    elif preferred_lang == "en" and tags.get("inscription:ru"):
        return tags["inscription:ru"]

    # Priority 5: Default name (might be in local language)
    if tags.get("name"):
        name = tags["name"]
        # If it contains non-Latin characters and we prefer English, mark it for translation
        import re

        if preferred_lang == "en" and re.search(r"[^\x00-\x7F]", name):
            # Contains non-ASCII characters, might need translation
            return name  # Will be handled by AI translation in the overview
        return name

    # Fallback
    return "Unknown Place"


def _calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate approximate distance between two points in meters using Haversine formula.
    """

    R = 6371000  # Earth's radius in meters

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c
