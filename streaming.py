"""
streaming.py — "where to watch" via TMDB.

Given a movie title (+ optional year), returns where it's streaming, rentable, or
buyable in a region, using TMDB's /watch/providers (data powered by JustWatch).

Degrades gracefully: if the key is missing or a lookup fails, returns None so the
recommender just shows no streaming line instead of crashing.
"""

import json
import urllib.parse
import urllib.request

from scrape import load_key  # env-first key loader (falls back to "credentials copy.py")

TMDB_API_KEY = load_key("TMDB_API_KEY") or ""

TMDB = "https://api.themoviedb.org/3"
REGION = "US"
_cache: dict = {}   # (title, year) -> result, so repeats in one run are free


def _clean_providers(names: list[str]) -> list[str]:
    """Collapse TMDB's granular variants to clean brand names and dedupe.
    'Netflix Standard with Ads' -> 'Netflix'; 'AMC+ Amazon Channel' -> 'AMC+'."""
    noise = [" Standard with Ads", " with Ads", " Apple TV Channel",
             " Amazon Channel", " Basic with Ads", " Premium"]
    out, seen = [], set()
    for name in names:
        n = name.strip()
        for suffix in noise:
            if n.endswith(suffix):
                n = n[: -len(suffix)].strip()
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def _get(path: str, params: dict) -> dict:
    params = {**params, "api_key": TMDB_API_KEY}
    url = f"{TMDB}/{path}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.load(resp)


def streaming_for(title: str, year=None, region: str = REGION) -> dict | None:
    """Return {'flatrate': [...], 'rent': [...], 'buy': [...], 'link': '...'} or None.

    'flatrate' = included with a subscription (Netflix, Max, ...). 'rent'/'buy' = paid.
    """
    if not TMDB_API_KEY or not title:
        return None
    key = (title.lower(), year)
    if key in _cache:
        return _cache[key]

    result = None
    try:
        params = {"query": title}
        if year:
            params["year"] = year
        hits = (_get("search/movie", params).get("results") or [])
        if hits:
            movie_id = hits[0]["id"]
            region_data = (_get(f"movie/{movie_id}/watch/providers", {})
                           .get("results") or {}).get(region) or {}
            out = {"link": region_data.get("link")}
            for kind in ("flatrate", "rent", "buy"):
                names = _clean_providers([p["provider_name"] for p in region_data.get(kind, [])])
                if names:
                    out[kind] = names
            # only return something if we actually found a provider
            if any(k in out for k in ("flatrate", "rent", "buy")):
                result = out
    except Exception:
        result = None

    _cache[key] = result
    return result


def summary_line(s: dict | None) -> str:
    """One-line human summary, e.g. 'Stream on Netflix, Max · rent on Apple TV'."""
    if not s:
        return ""
    parts = []
    if s.get("flatrate"):
        parts.append("Stream on " + ", ".join(s["flatrate"][:3]))
    if s.get("rent"):
        parts.append("rent on " + ", ".join(s["rent"][:2]))
    elif s.get("buy"):
        parts.append("buy on " + ", ".join(s["buy"][:2]))
    return " · ".join(parts)
