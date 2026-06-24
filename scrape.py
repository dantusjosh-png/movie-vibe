import os
import json
import time
import urllib.parse
import urllib.request
import anthropic
import importlib.util
from pathlib import Path
from collections import defaultdict


def load_key(name: str) -> str | None:
    """Read a key from the environment first (used when deployed), falling back to
    the local "credentials copy.py" file (used on Josh's machine; the space in the
    filename means it can't be imported normally). Keys are NEVER committed — see .gitignore."""
    if os.environ.get(name):
        return os.environ[name]
    cred_path = Path(__file__).resolve().parent / "credentials copy.py"
    if cred_path.exists():
        spec = importlib.util.spec_from_file_location("movie_vibe_credentials", cred_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return getattr(mod, name, None)
    return None


ANTHROPIC_API_KEY = load_key("ANTHROPIC_API_KEY")

# ── config ────────────────────────────────────────────────────────────────────
# Reddit's own JSON API now 403s without OAuth, and registering an OAuth app was
# blocked on the account. So we pull the same post/comment data from Arctic Shift,
# a community Reddit mirror that needs no auth. Data may lag live Reddit slightly.
SUBREDDITS            = ["MovieSuggestions", "movies", "netflix"]
ARCTIC                = "https://arctic-shift.photon-reddit.com/api"
HEADERS               = {"User-Agent": "movie-vibe-bot/1.0"}  # Arctic Shift 403s with no UA

TARGET_THREADS_PER_SUB = 40    # how many comment-rich recommendation threads to mine per sub
MAX_PAGES              = 20    # safety cap on pagination (100 posts/page) so a sub can't run away
MIN_COMMENTS           = 20    # only mine threads with enough discussion to carry signal
TOP_COMMENTS           = 15    # take the N highest-scored comments per thread (no hard upvote floor —
                               # the mirror captures comments at ingestion, so scores are unreliable)

RAW_FILE              = "vibe_graph_raw.json"   # every raw vibe Claude produced (pre-merge)
CACHE_FILE            = "scrape_cache.json"     # post_id -> extraction result; makes re-runs free & resumable
MODEL                 = "claude-haiku-4-5"      # cheap + plenty capable for this extraction

KEYWORDS = ["recommend", "looking for", "suggest", "what to watch", "similar to",
            "movies like", "feel like", "vibe", "in the mood", "something like"]

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ── arctic shift helpers ──────────────────────────────────────────────────────
def _arctic_get(endpoint: str, params: dict) -> list[dict]:
    url = f"{ARCTIC}/{endpoint}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.load(resp)
    if body.get("error"):
        raise RuntimeError(body["error"])
    return body.get("data") or []


def _is_request_post(post: dict) -> bool:
    text = (post.get("title", "") + " " + post.get("selftext", "")).lower()
    return any(k in text for k in KEYWORDS)


def fetch_candidate_posts(subreddit: str) -> list[dict]:
    """Page backward through a subreddit (newest first) collecting comment-rich
    recommendation-request threads, until we have enough or hit the page cap."""
    candidates: list[dict] = []
    before = None
    for page in range(MAX_PAGES):
        params = {"subreddit": subreddit, "limit": 100,
                  "sort": "desc", "sort_type": "created_utc"}
        if before is not None:
            params["before"] = int(before)
        posts = _arctic_get("posts/search", params)
        if not posts:
            break

        for p in posts:
            if p.get("num_comments", 0) >= MIN_COMMENTS and _is_request_post(p):
                candidates.append(p)

        before = posts[-1]["created_utc"]
        print(f"  page {page+1}: scanned {len(posts)} posts, "
              f"{len(candidates)}/{TARGET_THREADS_PER_SUB} candidates so far")
        if len(candidates) >= TARGET_THREADS_PER_SUB:
            break
        time.sleep(0.4)  # be polite to the mirror

    return candidates[:TARGET_THREADS_PER_SUB]


def fetch_comments(post_id: str) -> list[dict]:
    """Return the TOP_COMMENTS highest-scored comments for a post."""
    comments = _arctic_get("comments/search",
                           {"link_id": f"t3_{post_id}", "limit": 100})
    cleaned = [
        {"body": c.get("body", ""), "score": c.get("score", 0)}
        for c in comments
        if c.get("body") and c.get("body") not in ("[deleted]", "[removed]")
    ]
    cleaned.sort(key=lambda c: c["score"], reverse=True)
    return cleaned[:TOP_COMMENTS]


# ── claude extraction ─────────────────────────────────────────────────────────
EXTRACT_PROMPT = """
You are extracting structured data from a Reddit movie recommendation thread.

POST TITLE: {title}

TOP COMMENTS (most-upvoted first):
{comments}

Your job:
1. Identify the core VIBE the person is asking for (1-5 words, lowercase, descriptive).
   Examples: "cozy and comforting", "slow burn dread", "feel-good adventure", "mind-bending twists"

2. Extract every movie title mentioned in the comments.

3. For each movie, estimate a confidence score (0.0-1.0) that it genuinely matches
   the vibe, based on how strongly and how often commenters recommend it.

Return ONLY valid JSON in this exact format:
{{
  "vibe": "string",
  "movies": [
    {{"title": "Movie Title", "year": 2001, "confidence": 0.85}},
    ...
  ]
}}

If the post is not asking for movie recommendations, return: {{"vibe": null, "movies": []}}
"""

def extract_vibe_and_movies(title: str, comments: list[dict]) -> dict:
    if not comments:
        return {"vibe": None, "movies": []}

    comments_text = "\n".join(
        f"[{c['score']} pts] {c['body'][:300]}" for c in comments
    )

    msg = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": EXTRACT_PROMPT.format(title=title, comments=comments_text)
        }]
    )

    raw = msg.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


# ── cache ───────────────────────────────────────────────────────────────────────
def _load_cache() -> dict:
    if Path(CACHE_FILE).exists():
        return json.loads(Path(CACHE_FILE).read_text())
    return {}


def _save_cache(cache: dict) -> None:
    Path(CACHE_FILE).write_text(json.dumps(cache, indent=2))


# ── build the graph ───────────────────────────────────────────────────────────
def build_vibe_graph():
    # vibe -> movie -> {total_confidence, total_upvotes, mention_count, year}
    graph: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {
        "total_confidence": 0.0,
        "total_upvotes": 0,
        "mention_count": 0,
        "year": None
    }))

    cache = _load_cache()
    cache_hits = 0
    new_calls = 0

    for subreddit in SUBREDDITS:
        print(f"\nScraping r/{subreddit} via Arctic Shift...")
        try:
            posts = fetch_candidate_posts(subreddit)
        except Exception as e:
            print(f"  ERROR fetching posts: {e}")
            continue
        print(f"  -> {len(posts)} candidate threads")

        for i, post in enumerate(posts):
            pid   = post["id"]
            title = post.get("title", "")
            print(f"  [{i+1}/{len(posts)}] {title[:60]}")

            if pid in cache:
                result = cache[pid]
                cache_hits += 1
            else:
                try:
                    comments = fetch_comments(pid)
                    time.sleep(0.4)
                except Exception as e:
                    print(f"    skip (comment fetch error): {e}")
                    continue
                if not comments:
                    continue
                try:
                    result = extract_vibe_and_movies(title, comments)
                except Exception as e:
                    print(f"    skip (Claude parse error): {e}")
                    continue
                cache[pid] = result
                _save_cache(cache)   # persist after every call so a crash loses nothing
                new_calls += 1

            vibe = result.get("vibe")
            if not vibe:
                continue

            for movie in result.get("movies", []):
                m_title = movie.get("title", "").strip()
                if not m_title:
                    continue
                node = graph[vibe][m_title]
                node["total_confidence"] += movie.get("confidence", 0.5)
                node["total_upvotes"]    += movie.get("upvotes", 0)  # absent now → 0; kept for schema
                node["mention_count"]    += 1
                node["year"]              = movie.get("year") or node["year"]

            print(f"    vibe: '{vibe}' | movies: {len(result.get('movies', []))}"
                  f" {'(cached)' if pid in cache and result is cache[pid] else ''}")

    print(f"\nCache hits: {cache_hits} | new Claude calls: {new_calls}")
    # return the RAW aggregation (vibe -> title -> stats), un-merged & un-truncated.
    # near-duplicate vibes get collapsed later in merge_vibes.py.
    return {vibe: dict(movies) for vibe, movies in graph.items()}


# ── shared scoring ──────────────────────────────────────────────────────────────
def rank_movies(movie_stats: dict, top_n: int = 20) -> list[dict]:
    """Turn a {title -> stats} dict into a ranked list of movies.

    Shared by merge_vibes.py so the score formula lives in exactly one place.
    With the mirror, comment upvotes are unreliable, so avg_upvotes is ~0 and the
    ranking is driven by Claude's confidence and how often a movie is recommended.
    """
    ranked = []
    for title, stats in movie_stats.items():
        n = stats["mention_count"]
        avg_conf  = stats["total_confidence"] / n
        avg_votes = stats["total_upvotes"] / n
        score     = avg_conf * (1 + (avg_votes / 500))  # upvote boost (neutral when votes are 0)
        ranked.append({
            "title":         title,
            "year":          stats["year"],
            "score":         round(score, 3),
            "avg_confidence": round(avg_conf, 3),
            "avg_upvotes":   round(avg_votes),
            "mention_count": n
        })
    ranked.sort(key=lambda x: (x["score"], x["mention_count"]), reverse=True)
    return ranked[:top_n]


# ── main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Building raw vibe graph from Reddit (via Arctic Shift)...\n")
    raw = build_vibe_graph()

    with open(RAW_FILE, "w") as f:
        json.dump(raw, f, indent=2)

    print(f"\nDone. {len(raw)} raw vibes extracted.")
    print(f"Saved to {RAW_FILE}")
    print("Next: run `python3 merge_vibes.py` to collapse near-duplicate vibes "
          "and write the final vibe_graph.json")
