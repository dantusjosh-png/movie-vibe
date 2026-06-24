# Project Handoff: Movie Vibe Graph

## What This Is
A Reddit-powered movie recommendation engine. The core idea: Reddit is the best source of human-validated, emotionally-tagged movie recommendations in existence. Posts like *"I want something that feels like a warm hug"* with hundreds of upvoted replies are essentially crowd-sourced vibe buckets. We're mining that signal and turning it into a structured dataset.

The end product is a `vibe_graph.json` — a dictionary where each key is a vibe (e.g. `"cozy and comforting"`, `"slow burn dread"`) and each value is a ranked list of movies that Reddit users have validated for that vibe, scored by upvotes and mention frequency.

---

## Why It's Different From Existing Apps
Apps like Taranify and Moodies use TMDB genre tags to map moods to movies — it's basically a lookup table. We use actual human language from Reddit threads, weighted by community upvotes. A movie like *Arrival* isn't just "sci-fi" — Reddit tells us it belongs in "quiet dread + emotional gut-punch + cerebral." That's the moat.

---

## Project Location
```
~/Desktop/movie_vibe_graph/
├── scrape.py          # main scraper (done)
├── credentials.py     # Anthropic API key lives here (user creates this)
└── vibe_graph.json    # output — may or may not exist yet
```

---

## credentials.py Format
```python
ANTHROPIC_API_KEY = "sk-ant-..."
```

---

## scrape.py — What It Does
1. Hits r/MovieSuggestions, r/movies, r/netflix via Reddit's public JSON API (no auth required — uses User-Agent header only)
2. Fetches top 100 posts per subreddit (top of year)
3. Filters for recommendation-request posts using keywords: `recommend`, `looking for`, `suggest`, `what to watch`, `similar to`, `movies like`, `feel like`, `vibe`
4. Fetches top comments for each post, filtered to ≥50 upvotes
5. Sends each thread to Claude (`claude-sonnet-4-6`) with a structured prompt to extract:
   - The core **vibe** the post is asking for (1-5 words, lowercase)
   - Every **movie title** mentioned in comments
   - A **confidence score** (0.0–1.0) per movie weighted by upvotes
6. Aggregates across all posts — same movie appearing in multiple threads for the same vibe gets compounded scoring
7. Final score formula: `avg_confidence * (1 + avg_upvotes / 500)`
8. Outputs top 20 movies per vibe to `vibe_graph.json`

Reddit rate limiting: 1 second sleep between comment fetches. Full run takes ~10-15 min for 300 posts.

---

## vibe_graph.json Structure
```json
{
  "cozy and comforting": [
    {
      "title": "Paddington 2",
      "year": 2017,
      "score": 1.42,
      "avg_confidence": 0.91,
      "avg_upvotes": 248,
      "mention_count": 7
    },
    ...
  ],
  "slow burn dread": [...],
  ...
}
```

---

## What's Not Built Yet (Next Steps)

### 1. Embedding-Based Vibe Clustering
Right now each unique vibe string is its own bucket. Problem: `"cozy and warm"` and `"feel-good and comforting"` are the same vibe but stored separately. Next step is to embed all vibe strings and cluster them so similar vibes merge. Suggested approach:
- Use `sentence-transformers` (`all-MiniLM-L6-v2`) to embed vibe strings
- DBSCAN or k-means to cluster
- Label each cluster with a canonical vibe name
- Re-map `vibe_graph.json` to use cluster labels

### 2. Query Layer
The user types a natural language description of what they want to watch. Claude maps it to the closest vibe bucket(s) and returns the top matches. Should also accept context like:
- Who they're watching with
- How much time they have
- Which streaming services they have

### 3. Streaming Availability Filter
Integrate the **Streaming Availability API** (https://www.movieofthenight.com/about/api) or **JustWatch** to filter results to what's actually watchable tonight on the user's services.

### 4. UI
Was discussed as a conversational interface — user describes their situation in plain English, gets back **one confident recommendation** with a short explanation. Not a list, not a quiz. Terminal CLI first, then optionally a simple web frontend.

### 5. Monetization (Later)
- Affiliate links via JustWatch
- Subscription tier with persistent taste profiling over time
- No decisions made yet — build first

---

## Tech Stack
- **Python 3** — everything
- **requests** — Reddit JSON API calls
- **anthropic** — Claude extraction (`pip install anthropic`)
- **sentence-transformers** — for clustering step (not yet implemented)
- No database yet — flat JSON file is fine for POC

## Reddit API Note
Using public JSON endpoints (no OAuth). Format: `https://www.reddit.com/r/{sub}/top.json?limit=100&t=year`
User-Agent header required: `"movie-vibe-bot/1.0"`
This is read-only public data and works without credentials.

---

## Current Status
- `scrape.py` is written and ready to run
- User needs to create `credentials.py` with Anthropic key
- Run `python3 scrape.py` to generate `vibe_graph.json`
- Everything after that (clustering, query layer, UI) is unbuilt
