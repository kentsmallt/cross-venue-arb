from cross_venue_arb.http import HttpStatusError, _snippet, join_url, request_json


def test_error_snippet_uses_api_message():
    raw = b'{\n  "code": 0,\n  "msg": "Service unavailable from a restricted location"\n}'
    assert _snippet(raw) == "Service unavailable from a restricted location"


def test_only_https_urls():
    try:
        join_url("http://example.com", "/info")
    except HttpStatusError as exc:
        assert exc.status == 0
    else:
        raise AssertionError("http base URL was accepted")
    try:
        request_json("GET", "http://example.com/book")
    except HttpStatusError as exc:
        assert "https" in str(exc)
    else:
        raise AssertionError("http request was accepted")
