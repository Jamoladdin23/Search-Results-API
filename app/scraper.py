import os
import re
import logging
from typing import Optional
from serpapi import GoogleSearch

logger = logging.getLogger(__name__)

MAX_QUERY_LENGTH = 300

_DANGEROUS_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_query(query: str) -> str:
    if not isinstance(query, str):
        raise ValueError("Query must be a string")
    query = query.strip()
    if not query:
        raise ValueError("Query cannot be empty")
    if len(query) > MAX_QUERY_LENGTH:
        raise ValueError(f"Query too long (max {MAX_QUERY_LENGTH} characters)")
    if _DANGEROUS_PATTERN.search(query):
        raise ValueError("Query contains invalid characters")
    return query


def search(query: str, max_results: int = 10) -> Optional[list[dict]]:
    query = sanitize_query(query)
    max_results = max(1, min(max_results, 10))

    api_key = os.getenv("SERPAPI_KEY")
    if not api_key:
        logger.error("SERPAPI_KEY is not set")
        return None

    try:
        params = {
            "q": query,
            "num": max_results,
            "api_key": api_key,
            "engine": "google",
        }
        results_raw = GoogleSearch(params).get_dict().get("organic_results", [])
    except Exception as exc:
        logger.error("Search failed: %s", exc)
        return None

    results = []
    for position, item in enumerate(results_raw[:max_results], start=1):
        url = (item.get("link") or "").strip()
        if not url or not url.startswith(("http://", "https://")):
            continue
        results.append({
            "position": position,
            "title": (item.get("title") or "").strip(),
            "url": url,
            "description": (item.get("snippet") or "").strip(),
        })

    return results
