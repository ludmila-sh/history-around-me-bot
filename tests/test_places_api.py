import requests

from src.places_api import describe_error


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
