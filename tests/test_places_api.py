import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from src import places_api
from src.places_api import describe_error

FIXTURES = Path(__file__).parent / "fixtures"
ORIGIN = (36.5320, 32.0000)


def test_error_description_hides_url_with_user_coordinates():
    response = requests.Response()
    response.status_code = 403
    response.url = "https://en.wikipedia.org/w/api.php?gscoord=36.5437%7C31.9998&key=secret"
    error = requests.HTTPError("403 Client Error: Forbidden for url: " + response.url)
    error.response = response

    description = describe_error(error)

    assert description == "HTTP 403 from en.wikipedia.org"
    assert "36.5437" not in description
    assert "secret" not in description


def test_error_description_for_network_errors_has_no_details():
    error = requests.ConnectionError("Failed for https://example.org/?lat=36.54&lon=31.99")
    assert describe_error(error) == "ConnectionError"


SULEYMANIYE = (41.0155, 28.9650)
NO_PAGES = {"query": {"pages": {}}}


def _search(lang: str, at: tuple[float, float] = SULEYMANIYE):
    return asyncio.run(places_api.get_nearby_places(*at, lang=lang))


def _fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeNetwork:
    """Serves fixtures instead of the network and records what was asked."""

    def __init__(self):
        self.opentripmap = _fixture("otm_suleymaniye.json")
        self.opentripmap_error: Exception | None = None
        self.overpass = _fixture("overpass_alanya.json")
        self.wikipedia = {"en": _fixture("wikipedia_en_suleymaniye.json")}
        self.opentripmap_calls: list[tuple[int, str]] = []
        self.wikipedia_asked: list[str] = []

    def fetch_opentripmap(self, lat, lon, radius, lang):
        self.opentripmap_calls.append((radius, lang))
        if self.opentripmap_error:
            raise self.opentripmap_error
        return self.opentripmap

    def fetch_overpass(self, query):
        return self.overpass

    def fetch_wikipedia(self, lat, lon, lang):
        self.wikipedia_asked.append(lang)
        return self.wikipedia.get(lang, NO_PAGES)


@pytest.fixture
def network(monkeypatch):
    fake = FakeNetwork()
    monkeypatch.setattr(places_api, "_fetch_opentripmap", fake.fetch_opentripmap)
    monkeypatch.setattr(places_api, "_fetch_overpass", fake.fetch_overpass)
    monkeypatch.setattr(places_api, "_fetch_wikipedia", fake.fetch_wikipedia)
    return fake


def _names(result) -> set[str]:
    return {p["name"] for places in result.by_category.values() for p in places}


def test_sights_come_from_opentripmap_most_notable_first_with_wikipedia_text(network):
    result = _search("ru")

    assert network.opentripmap_calls == [(500, "ru")]
    assert result.radius == 500 and not result.expanded
    assert set(result.by_category) <= {"history_culture", "parks_nature", "viewpoints"}
    assert "food_drinks" not in result.by_category  # food is a separate, on-demand search
    mosque = result.by_category["history_culture"][0]
    assert mosque["name"] == "Süleymaniye Mosque" and mosque["rate"] == 7
    assert mosque["wikipedia_extract"].startswith("Test extract")  # matched by wikidata
    assert mosque["wikipedia_lang"] == "en"  # the ru Wikipedia has no page here
    assert network.wikipedia_asked == ["ru", "en"]


def test_unsupported_language_is_requested_from_opentripmap_in_english(network):
    _search("de")
    assert network.opentripmap_calls[0][1] == "en"


def test_sparse_area_widens_the_radius_once(network):
    network.opentripmap = [i for i in network.opentripmap if i["xid"] == "R1564032"]

    result = _search("en")

    assert network.opentripmap_calls == [(500, "en"), (1500, "en")]
    assert result.expanded and result.radius == 1500
    assert _names(result) == {"Süleymaniye Mosque"}


def test_residential_area_reports_nothing_instead_of_minor_places(network):
    network.opentripmap = _fixture("otm_bakirkoy.json")  # five places, all rate 1

    result = _search("en")

    assert result.by_category == {} and result.expanded
    assert network.opentripmap_calls == [(500, "en"), (1500, "en")]


def test_overpass_replaces_opentripmap_when_it_fails_and_returns_sights_only(network):
    network.opentripmap_error = requests.ConnectionError("down")
    network.wikipedia = {"tr": _fixture("wikipedia_tr.json")}

    result = _search("en", at=ORIGIN)  # the Overpass fixture was taken around Alanya

    assert set(result.by_category) == {"history_culture", "parks_nature"}
    assert "Кофе и чай" not in _names(result)  # cafes and shops come from elsewhere
    assert {"Kızıl Kule", "Eski Cami", "Atatürk Parkı"} <= _names(result)
    assert network.wikipedia_asked == ["en", "tr"]  # "tr" comes from the OSM tag "tr:Kızıl Kule"


def test_search_is_unavailable_when_both_sources_fail(network, monkeypatch):
    network.opentripmap_error = requests.ConnectionError("down")

    def down(query):
        raise places_api.PlacesUnavailable("down")

    monkeypatch.setattr(places_api, "_fetch_overpass", down)
    with pytest.raises(places_api.PlacesUnavailable):
        _search("en")


def test_wikipedia_failure_keeps_places_without_text(network, monkeypatch):
    def broken(lat, lon, lang):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(places_api, "_fetch_wikipedia", broken)
    result = _search("en")
    assert result.by_category["history_culture"]
    assert all("wikipedia_extract" not in p for p in result.by_category["history_culture"])


def test_search_gives_up_after_total_timeout(network, monkeypatch):
    def slow(lat, lon, radius, lang):
        time.sleep(0.5)
        return []

    monkeypatch.setattr(places_api, "_fetch_opentripmap", slow)
    monkeypatch.setattr(places_api, "TOTAL_TIMEOUT", 0.05)
    with pytest.raises(places_api.PlacesUnavailable):
        _search("en")


def test_overpass_falls_back_to_second_instance(monkeypatch):
    calls: list[str] = []

    def post(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            response = requests.Response()
            response.status_code = 406
            response.url = url
            return response
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"elements": []})

    monkeypatch.setattr(places_api.requests, "post", post)
    assert places_api._fetch_overpass("q") == {"elements": []}
    assert calls == list(places_api.OVERPASS_URLS)


def test_wikipedia_language_codes_from_osm_are_validated_before_use_in_host():
    places = [{"wikipedia": "evil.com/x:Title"}, {"wikipedia": "tr:Kule"}, {"wikipedia": ""}]
    assert places_api._wikipedia_languages("en", places) == ["en", "tr"]


def test_overpass_query_covers_all_tag_keys_within_requested_radius():
    query = places_api._overpass_query(36.5, 32.0, 500)
    assert "around:500,36.5,32.0" in query
    for key in ("historic", "tourism", "amenity", "leisure", "natural", "shop"):
        assert f'["{key}"' in query
    # dense categories skip relations on purpose, rarer ones keep them
    assert 'nwr["shop"' not in query and 'node["shop"' in query
    assert 'nwr["historic"' in query


def test_opentripmap_request_uses_rapidapi_headers_and_language(monkeypatch):
    seen = {}

    def get(url, **kwargs):
        seen.update(url=url, **kwargs)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: [{"name": "x"}])

    monkeypatch.setattr(places_api.requests, "get", get)

    assert places_api._fetch_opentripmap(41.0, 29.0, 500, "ru") == [{"name": "x"}]
    assert seen["url"] == f"https://{places_api.OPENTRIPMAP_HOST}/ru/places/radius"
    assert seen["params"]["radius"] == 500 and seen["params"]["kinds"] == "interesting_places"
    assert seen["headers"]["X-RapidAPI-Key"] == "test-opentripmap-key"
    assert "test-opentripmap-key" not in seen["url"]  # the key must never travel in the URL


def test_opentripmap_http_error_is_raised_not_swallowed(monkeypatch):
    def get(url, **kwargs):
        response = requests.Response()
        response.status_code = 429
        response.url = url
        return SimpleNamespace(
            raise_for_status=lambda: (_ for _ in ()).throw(requests.HTTPError(response=response))
        )

    monkeypatch.setattr(places_api.requests, "get", get)
    with pytest.raises(requests.HTTPError) as error:
        places_api._fetch_opentripmap(41.0, 29.0, 500, "en")
    assert places_api.describe_error(error.value) == f"HTTP 429 from {places_api.OPENTRIPMAP_HOST}"


def _food_fixture() -> list[dict]:
    return json.loads((FIXTURES / "google_food_ankara.json").read_text(encoding="utf-8"))


def test_google_request_asks_only_for_needed_fields_and_keeps_key_in_header(monkeypatch):
    seen = {}

    def post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: {"places": [{"id": "x"}]}
        )

    monkeypatch.setattr(places_api.requests, "post", post)

    assert places_api._fetch_google_food(39.9, 32.8, 500, "ru") == [{"id": "x"}]
    assert seen["headers"]["X-Goog-Api-Key"] == "test-google-key"
    assert "photos" not in seen["headers"]["X-Goog-FieldMask"]
    assert "editorialSummary" not in seen["headers"]["X-Goog-FieldMask"]
    assert seen["json"]["languageCode"] == "ru"
    assert seen["json"]["locationRestriction"]["circle"]["radius"] == 500


def test_food_returns_five_best_places_in_one_request_when_enough_qualify(monkeypatch):
    radii = []

    def fetch(lat, lon, radius, lang):
        radii.append(radius)
        return _food_fixture()

    monkeypatch.setattr(places_api, "_fetch_google_food", fetch)

    places = asyncio.run(places_api.get_nearby_food(*ORIGIN, lang="en"))

    assert len(places) == 5 and radii == [500]


def test_food_widens_radius_when_few_places_qualify(monkeypatch):
    radii = []

    def fetch(lat, lon, radius, lang):
        radii.append(radius)
        return [] if radius == 500 else _food_fixture()

    monkeypatch.setattr(places_api, "_fetch_google_food", fetch)

    assert asyncio.run(places_api.get_nearby_food(*ORIGIN, lang="en"))
    assert radii == [500, 1500]


def test_food_failure_is_reported_not_hidden(monkeypatch):
    def fetch(lat, lon, radius, lang):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(places_api, "_fetch_google_food", fetch)

    with pytest.raises(places_api.PlacesUnavailable):
        asyncio.run(places_api.get_nearby_food(*ORIGIN, lang="en"))
