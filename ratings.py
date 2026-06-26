"""
ratings.py — Rotten Tomatoes + IMDb scores via OMDb (omdbapi.com).

RT has no official API; OMDb is the standard free way to get the Tomatometer
(plus IMDb and Metacritic) in one call. Degrades gracefully: missing key or
missing data just returns None, so cards render without scores rather than break.
"""

import json
import urllib.parse
import urllib.request

from scrape import load_key  # env-first key loader (falls back to "credentials copy.py")

OMDB_API_KEY = load_key("OMDB_API_KEY") or ""
_cache: dict = {}   # (title, year) -> {rt, imdb} | None


def ratings_for(title: str, year=None) -> dict | None:
    """Return {'rt': '90%', 'imdb': '7.3'} (either key may be absent), or None."""
    if not OMDB_API_KEY or not title:
        return None
    key = (title.lower(), year)
    if key in _cache:
        return _cache[key]

    out = None
    try:
        params = {"apikey": OMDB_API_KEY, "t": title}
        if year:
            params["y"] = str(year)
        url = "https://www.omdbapi.com/?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=15) as resp:
            d = json.load(resp)
        if d.get("Response") == "True":
            res = {}
            for r in d.get("Ratings", []):
                if r.get("Source") == "Rotten Tomatoes":
                    res["rt"] = r.get("Value")        # e.g. "90%"
            imdb = d.get("imdbRating")
            if imdb and imdb != "N/A":
                res["imdb"] = imdb                    # e.g. "7.3"
            out = res or None
    except Exception:
        out = None

    _cache[key] = out
    return out
