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
POSTER_BASE = "https://image.tmdb.org/t/p/w342"
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


def movie_info(title: str, year=None, region: str = REGION) -> dict | None:
    """Look a movie up on TMDB and return everything we show about it:

    {overview, poster, tmdb_rating, year, streaming: {flatrate, rent, buy, link}}

    'streaming.flatrate' = included with a subscription (Netflix, Max, ...);
    'rent'/'buy' = paid. Returns None if the movie isn't found or no key is set.
    One TMDB search + one providers call, cached per (title, year).
    """
    if not TMDB_API_KEY or not title:
        return None
    key = (title.lower(), year)
    if key in _cache:
        return _cache[key]

    info = None
    try:
        params = {"query": title}
        if year:
            params["year"] = year
        hits = (_get("search/movie", params).get("results") or [])
        if hits:
            m = hits[0]
            region_data = (_get(f"movie/{m['id']}/watch/providers", {})
                           .get("results") or {}).get(region) or {}
            streaming = {"link": region_data.get("link")}
            for kind in ("flatrate", "rent", "buy"):
                names = _clean_providers([p["provider_name"] for p in region_data.get(kind, [])])
                if names:
                    streaming[kind] = names
            if not any(k in streaming for k in ("flatrate", "rent", "buy")):
                streaming = None

            rating = m.get("vote_average")
            info = {
                "overview": m.get("overview") or "",
                "poster": (POSTER_BASE + m["poster_path"]) if m.get("poster_path") else None,
                "tmdb_rating": round(rating, 1) if rating else None,
                "year": (m.get("release_date") or "")[:4] or year,
                "streaming": streaming,
            }
    except Exception:
        info = None

    _cache[key] = info
    return info


def streaming_for(title: str, year=None) -> dict | None:
    """Back-compat helper — just the streaming portion of movie_info()."""
    info = movie_info(title, year)
    return info.get("streaming") if info else None


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
