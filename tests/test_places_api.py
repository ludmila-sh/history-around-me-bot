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


def _search(lang: str):
    return asyncio.run(places_api.get_nearby_places(*ORIGIN, lang=lang))


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def fake_network(monkeypatch):
    """Serve fixtures instead of the network; records which Wikipedia languages were asked."""
    asked: list[str] = []

    def fetch_wikipedia(lat, lon, lang):
        asked.append(lang)
        return _fixture(f"wikipedia_{lang}.json")

    monkeypatch.setattr(
        places_api, "_fetch_overpass", lambda query: _fixture("overpass_alanya.json")
    )
    monkeypatch.setattr(places_api, "_fetch_wikipedia", fetch_wikipedia)
    return asked


def test_search_returns_categorized_places_with_wikipedia_text(fake_network):
    result = _search("ru")

    assert result.radius == 500 and not result.expanded
    assert set(result.by_category) == {"history_culture", "food_drinks", "shopping", "parks_nature"}
    tower = next(p for p in result.by_category["history_culture"] if p["name"] == "Красная башня")
    assert tower["wikipedia_extract"].startswith("Красная башня")
    assert "Far Ruins" not in [p["name"] for ps in result.by_category.values() for p in ps]


def test_search_asks_user_language_english_then_language_from_osm_tags(fake_network):
    _search("ru")
    assert fake_network == ["ru", "en", "tr"]  # "tr" comes from the OSM tag "tr:Kızıl Kule"


def test_search_expands_radius_when_near_area_is_sparse(monkeypatch, fake_network):
    sparse = {
        "elements": [e for e in _fixture("overpass_alanya.json")["elements"] if e["id"] in (1, 9)]
    }
    monkeypatch.setattr(places_api, "_fetch_overpass", lambda query: sparse)
    monkeypatch.setattr(places_api, "WIDE_RADIUS", 5000)

    result = _search("en")

    assert result.expanded and result.radius == 5000
    names = [p["name"] for ps in result.by_category.values() for p in ps]
    assert set(names) == {"Kızıl Kule", "Far Ruins"}


def test_search_reports_nothing_when_area_is_empty(monkeypatch, fake_network):
    monkeypatch.setattr(places_api, "_fetch_overpass", lambda query: {"elements": []})
    result = _search("en")
    assert result.by_category == {} and result.expanded


def test_wikipedia_failure_keeps_places_without_text(monkeypatch, fake_network):
    def broken(lat, lon, lang):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(places_api, "_fetch_wikipedia", broken)
    result = _search("en")
    assert result.by_category["history_culture"]
    assert all("wikipedia_extract" not in p for p in result.by_category["history_culture"])


def test_overpass_failure_is_not_reported_as_empty_area(monkeypatch, fake_network):
    def down(query):
        raise places_api.PlacesUnavailable("down")

    monkeypatch.setattr(places_api, "_fetch_overpass", down)
    with pytest.raises(places_api.PlacesUnavailable):
        _search("en")


def test_search_gives_up_after_total_timeout(monkeypatch, fake_network):
    def slow(query):
        time.sleep(0.5)
        return {"elements": []}

    monkeypatch.setattr(places_api, "_fetch_overpass", slow)
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


def test_overpass_query_uses_wide_radius_and_all_tag_keys():
    query = places_api._overpass_query(36.5, 32.0)
    assert f"around:{places_api.WIDE_RADIUS},36.5,32.0" in query
    for key in ("historic", "tourism", "amenity", "leisure", "natural", "shop"):
        assert f'nwr["{key}"' in query
