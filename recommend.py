"""
recommend.py — live niche movie recommendations.

Type whatever you want ("a movie for when I have a fever", "something that
makes me feel uplifted and fulfilled") and this:
  1. turns your request into Reddit search terms,
  2. searches the movie subreddits LIVE for threads about exactly that,
  3. reads the recommendations in those threads,
  4. returns one personal pick + a few runners-up, with reasons —
     favoring movies that show up across multiple threads (lots of people vouch).

Usage:
    python3 recommend.py "movies to watch while having a fever"
    python3 recommend.py            # then type your request when prompted

Reuses the Arctic Shift fetch helpers + Claude client from scrape.py.
"""

import sys
import json
import time

import scrape  # _arctic_get, fetch_comments, client, MODEL — no scrape runs on import
import streaming  # "where to watch" via TMDB

client = scrape.client
MODEL = scrape.MODEL

# subreddits to search live (r/suggestmeamovie is the biggest rec-request sub)
SEARCH_SUBS        = ["suggestmeamovie", "MovieSuggestions", "movies", "netflix"]
RESULTS_PER_QUERY  = 25   # posts to pull per (query, subreddit)
MIN_COMMENTS       = 8    # a thread needs some discussion to be worth reading
MAX_COMMENTS       = 400  # skip giant generic "rank every movie" megathreads
CANDIDATE_POOL     = 18   # shortlist this many before filtering for relevance
MAX_THREADS        = 6    # how many of those to actually read
COMMENTS_PER_THREAD = 12  # top comments to show Claude per thread


# ── 1. turn the request into search terms ─────────────────────────────────────
def make_search_queries(user_request: str) -> list[str]:
    prompt = f"""A user wants a movie recommendation for this request:
"{user_request}"

Generate 3 short search queries (2-5 words each) that would find Reddit threads
where people asked for — and recommended — movies matching this request. Use the
kind of plain words people actually put in Reddit post titles.

Return ONLY JSON: {{"queries": ["...", "...", "..."]}}"""
    msg = client.messages.create(
        model=MODEL, max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(raw)["queries"]


# ── 2. find the matching threads, live ────────────────────────────────────────
def find_threads(queries: list[str]) -> list[dict]:
    seen: dict[str, dict] = {}
    for q in queries:
        for sub in SEARCH_SUBS:
            try:
                posts = scrape._arctic_get("posts/search", {
                    "query": q, "subreddit": sub, "limit": RESULTS_PER_QUERY,
                    "sort": "desc", "sort_type": "created_utc",
                })
            except Exception:
                continue
            for p in posts:
                n = p.get("num_comments", 0)
                if MIN_COMMENTS <= n <= MAX_COMMENTS:
                    seen[p["id"]] = p
            time.sleep(0.3)
    # most-discussed threads first, as a shortlist to filter for relevance next
    return sorted(seen.values(), key=lambda p: p.get("num_comments", 0),
                  reverse=True)[:CANDIDATE_POOL]


# ── 2b. keep only the threads genuinely about the request ─────────────────────
def select_relevant(user_request: str, candidates: list[dict]) -> list[dict]:
    """Search matches on keywords, so the shortlist includes off-topic threads.
    Have Claude pick the ones actually about the request (by title)."""
    if len(candidates) <= MAX_THREADS:
        return candidates
    listing = "\n".join(f"{i}. {p['title']}" for i, p in enumerate(candidates))
    prompt = f"""A user asked for a movie recommendation: "{user_request}"

Here are Reddit thread titles found by search. Some genuinely match their request;
others just matched a keyword by accident (generic ranking lists, off-topic chat).
Pick the up to {MAX_THREADS} threads that ACTUALLY fit what they're asking for.

{listing}

Return ONLY JSON with the thread numbers to keep, best match first:
{{"keep": [3, 0, 7]}}"""
    msg = client.messages.create(
        model=MODEL, max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    idxs = json.loads(raw).get("keep", [])
    picked = [candidates[i] for i in idxs if isinstance(i, int) and 0 <= i < len(candidates)]
    return picked[:MAX_THREADS] or candidates[:MAX_THREADS]


# ── 3 + 4. read threads and synthesize a personal recommendation ──────────────
SYNTH_PROMPT = """You're a friend who watches a ton of movies, giving ONE person a recommendation.

THEIR REQUEST: "{request}"

Below are real Reddit threads where people asked for similar things, each followed
by the movies others recommended (most-upvoted first):

{context}

Choose the movies that best fit THEIR SPECIFIC request. Prioritize movies recommended
across MULTIPLE threads (lots of people vouch for them) AND that genuinely match what
they asked for. Don't invent movies that aren't in the threads.

For each "why": paraphrase the actual reasons commenters gave for that movie, but say
it the way a friend would out loud — warm, casual, specific. Use plain words and
contractions. One or two natural sentences. No clinical or essay-style phrasing, no
em-dashes, no "soothes rather than stimulates" type lines. Sound like a person texting
a friend, not a film review. When it fits, nod to the crowd ("a bunch of people swear
by this for exactly this").

Return ONLY JSON:
{{
  "top_pick": {{"title": "...", "year": 2001, "why": "..."}},
  "runners_up": [
    {{"title": "...", "year": 2001, "mentions": 2, "why": "..."}}
  ]
}}
Include up to 5 runners_up. "mentions" = how many of the threads above recommended it."""


def recommend(user_request: str) -> dict | None:
    print(f'\nThinking about: "{user_request}"')
    queries = make_search_queries(user_request)
    print(f"  searching Reddit for: {', '.join(queries)}")

    candidates = find_threads(queries)
    if not candidates:
        return None
    threads = select_relevant(user_request, candidates)
    print(f"  reading {len(threads)} of {len(candidates)} threads (most relevant):")
    for t in threads:
        print(f"    • {t['title'][:65]}  ({t['num_comments']} comments)")

    blocks = []
    for t in threads:
        comments = scrape.fetch_comments(t["id"])[:COMMENTS_PER_THREAD]
        if not comments:
            continue
        body = "\n".join(f"- {c['body'][:200]}" for c in comments)
        blocks.append(f"THREAD: {t['title']}\n{body}")
        time.sleep(0.3)
    context = "\n\n".join(blocks)

    msg = client.messages.create(
        model=MODEL, max_tokens=1500,
        messages=[{"role": "user",
                   "content": SYNTH_PROMPT.format(request=user_request, context=context)}],
    )
    raw = msg.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    rec = json.loads(raw)

    # enrich every pick with TMDB details: overview, poster, rating, where to watch
    for movie in [rec.get("top_pick", {})] + rec.get("runners_up", []):
        if movie.get("title"):
            info = streaming.movie_info(movie["title"], movie.get("year"))
            if info:
                movie["overview"] = info["overview"]
                movie["poster"] = info["poster"]
                movie["tmdb_rating"] = info["tmdb_rating"]
                movie["streaming"] = info["streaming"]
                if info.get("year") and not movie.get("year"):
                    movie["year"] = info["year"]
    return rec


# ── pretty print ──────────────────────────────────────────────────────────────
def show(rec: dict) -> None:
    tp = rec["top_pick"]
    rating = f"   ★ {tp['tmdb_rating']}" if tp.get("tmdb_rating") else ""
    print("\n" + "─" * 60)
    print(f"  🎬  {tp['title']} ({tp.get('year', '—')}){rating}")
    if tp.get("overview"):
        print(f"      {tp['overview']}")
    print(f"      → {tp['why']}")
    where = streaming.summary_line(tp.get("streaming"))
    if where:
        print(f"      ▸ {where}")
    runners = rec.get("runners_up", [])
    if runners:
        print("\n  also worth a look:")
        for m in runners:
            mentions = m.get("mentions")
            tag = f"  ({mentions} threads rec'd it)" if mentions and mentions > 1 else ""
            print(f"    • {m['title']} ({m.get('year', '—')}){tag}")
            print(f"        {m['why']}")
            mwhere = streaming.summary_line(m.get("streaming"))
            if mwhere:
                print(f"        ▸ {mwhere}")
    print("─" * 60)


# ── main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    request = " ".join(sys.argv[1:]).strip()
    if not request:
        request = input("What kind of movie are you in the mood for? ").strip()

    result = recommend(request)
    if result is None:
        print("\n  Couldn't find Reddit threads for that one — try rephrasing, "
              "or make it a little less specific.")
    else:
        show(result)
