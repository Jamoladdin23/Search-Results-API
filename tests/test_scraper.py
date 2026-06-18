import time
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.scraper import sanitize_query, search, MAX_QUERY_LENGTH
from app.main import app, _rate_store, RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def clear_rate_store():
    _rate_store.clear()
    yield
    _rate_store.clear()


# ── sanitize_query ────────────────────────────────────────────────────────────

class TestSanitizeQuery:

    def test_valid_query_returned_stripped(self):
        assert sanitize_query("  python fastapi  ") == "python fastapi"

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="empty"):
            sanitize_query("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="empty"):
            sanitize_query("   ")

    def test_too_long_raises(self):
        with pytest.raises(ValueError, match="too long"):
            sanitize_query("a" * (MAX_QUERY_LENGTH + 1))

    def test_max_length_accepted(self):
        q = "a" * MAX_QUERY_LENGTH
        assert sanitize_query(q) == q

    def test_null_byte_raises(self):
        with pytest.raises(ValueError, match="invalid characters"):
            sanitize_query("hello\x00world")

    def test_control_character_raises(self):
        with pytest.raises(ValueError, match="invalid characters"):
            sanitize_query("query\x1binjection")

    def test_non_string_raises(self):
        with pytest.raises((ValueError, AttributeError)):
            sanitize_query(123)  # type: ignore

    def test_unicode_query_accepted(self):
        q = "Hledám práci v Praze — Python developer"
        assert sanitize_query(q) == q


# ── search() ─────────────────────────────────────────────────────────────────

MOCK_SERPAPI_RESULTS = [
    {"title": "FastAPI Docs", "link": "https://fastapi.tiangolo.com", "snippet": "Modern Python API framework."},
    {"title": "Python Org",   "link": "https://www.python.org",       "snippet": "Official Python site."},
    {"title": "No URL",       "link": "",                              "snippet": "Should be skipped."},
    {"title": "Bad scheme",   "link": "javascript:alert(1)",          "snippet": "XSS attempt, skip."},
]


class TestSearch:

    @patch("app.scraper.GoogleSearch")
    def test_returns_list(self, MockGS):
        MockGS.return_value.get_dict.return_value = {"organic_results": MOCK_SERPAPI_RESULTS}
        results = search("python fastapi")
        assert isinstance(results, list)
        assert len(results) == 2  # пустой link и javascript: отфильтрованы

    @patch("app.scraper.GoogleSearch")
    def test_result_has_required_fields(self, MockGS):
        MockGS.return_value.get_dict.return_value = {"organic_results": MOCK_SERPAPI_RESULTS[:2]}
        results = search("python")
        for r in results:
            assert "position"    in r
            assert "title"       in r
            assert "url"         in r
            assert "description" in r

    @patch("app.scraper.GoogleSearch")
    def test_positions_are_sequential(self, MockGS):
        MockGS.return_value.get_dict.return_value = {"organic_results": MOCK_SERPAPI_RESULTS[:2]}
        results = search("python")
        positions = [r["position"] for r in results]
        assert positions == list(range(1, len(results) + 1))

    @patch("app.scraper.GoogleSearch")
    def test_all_urls_are_http(self, MockGS):
        MockGS.return_value.get_dict.return_value = {"organic_results": MOCK_SERPAPI_RESULTS}
        results = search("python")
        for r in results:
            assert r["url"].startswith(("http://", "https://"))

    @patch("app.scraper.GoogleSearch")
    def test_empty_response_returns_empty_list(self, MockGS):
        MockGS.return_value.get_dict.return_value = {"organic_results": []}
        results = search("python")
        assert results == []

    @patch("app.scraper.GoogleSearch")
    def test_exception_returns_none(self, MockGS):
        MockGS.return_value.get_dict.side_effect = RuntimeError("api error")
        result = search("python")
        assert result is None

    @patch("app.scraper.GoogleSearch")
    def test_unexpected_exception_returns_none(self, MockGS):
        MockGS.side_effect = Exception("unexpected")
        result = search("python")
        assert result is None

    def test_invalid_query_raises_value_error(self):
        with pytest.raises(ValueError):
            search("")

    @patch("app.scraper.GoogleSearch")
    def test_max_results_capped_at_10(self, MockGS):
        MockGS.return_value.get_dict.return_value = {"organic_results": []}
        search("python", max_results=999)
        called_params = MockGS.call_args[0][0]
        assert called_params["num"] <= 10


# ── GET /search ───────────────────────────────────────────────────────────────

MOCK_RESULTS = [
    {"position": 1, "title": "FastAPI", "url": "https://fastapi.tiangolo.com", "description": "Desc"}
]


class TestSearchEndpoint:

    @patch("app.main.search")
    def test_happy_path_returns_200(self, mock_search):
        mock_search.return_value = MOCK_RESULTS
        resp = client.get("/search?q=python")
        assert resp.status_code == 200

    @patch("app.main.search")
    def test_response_contains_query_and_results(self, mock_search):
        mock_search.return_value = MOCK_RESULTS
        resp = client.get("/search?q=python")
        data = resp.json()
        assert data["query"] == "python"
        assert len(data["results"]) == 1

    @patch("app.main.search")
    def test_result_fields_present(self, mock_search):
        mock_search.return_value = MOCK_RESULTS
        resp = client.get("/search?q=python")
        r = resp.json()["results"][0]
        assert all(k in r for k in ["position", "title", "url", "description"])

    def test_missing_q_returns_422(self):
        resp = client.get("/search")
        assert resp.status_code == 422

    def test_empty_q_returns_422(self):
        resp = client.get("/search?q=")
        assert resp.status_code == 422

    def test_too_long_q_returns_422(self):
        resp = client.get("/search?q=" + "a" * 301)
        assert resp.status_code == 422

    @patch("app.main.search")
    def test_backend_unavailable_returns_503(self, mock_search):
        mock_search.return_value = None
        resp = client.get("/search?q=python")
        assert resp.status_code == 503

    @patch("app.main.search")
    def test_empty_results_returns_200(self, mock_search):
        mock_search.return_value = []
        resp = client.get("/search?q=xyzzynotfound")
        assert resp.status_code == 200
        assert resp.json()["results"] == []

    @patch("app.main.search")
    def test_rate_limit_triggers_429(self, mock_search):
        mock_search.return_value = MOCK_RESULTS
        for i in range(RATE_LIMIT_REQUESTS):
            r = client.get("/search?q=python")
            assert r.status_code == 200, f"Request {i+1} should succeed"
        resp = client.get("/search?q=python")
        assert resp.status_code == 429

    def test_index_page_returns_html(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    @patch("app.main.search")
    def test_security_headers_present(self, mock_search):
        mock_search.return_value = MOCK_RESULTS
        resp = client.get("/search?q=python")
        assert "x-content-type-options"  in resp.headers
        assert "x-frame-options"         in resp.headers
        assert "content-security-policy" in resp.headers
