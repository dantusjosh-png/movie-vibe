"""
merge_vibes.py — collapse near-duplicate vibes into a clean canonical set.

scrape.py produces vibe_graph_raw.json, where every vibe label is exactly the
string Claude happened to emit. That means "cozy and warm", "feel-good and
comforting", and "comfort watch" all live as separate buckets even though
they're the same request.

This step:
  1. Loads the raw vibes + how often each was requested.
  2. Asks Claude to group near-identical vibes under one canonical label,
     targeting the ~50-100 most common things people actually ask for.
  3. Re-merges every movie's stats under its canonical vibe.
  4. Ranks vibes by total demand, keeps the top N, and writes vibe_graph.json.

Re-runnable for free-ish (one Claude call) — tune without re-scraping Reddit.
"""

import json
import importlib.util
from pathlib import Path
from collections import defaultdict

import anthropic

from scrape import rank_movies  # single source of truth for the score formula

# ── config ──────────────────────────────────────────────────────────────────────
RAW_FILE      = "vibe_graph_raw.json"
OUTPUT_FILE   = "vibe_graph.json"
MAP_FILE      = "vibe_canonical_map.json"   # raw->canonical mapping, for inspection
TARGET_VIBES  = 80      # aim for ~50-100 canonical vibes
MAX_VIBES     = 100     # hard cap kept in final output
TOP_MOVIES    = 20      # per vibe
MODEL         = "claude-sonnet-4-6"

# ── credentials (filename has a space, so load it explicitly) ────────────────────
_cred_path = Path(__file__).resolve().parent / "credentials copy.py"
_spec = importlib.util.spec_from_file_location("movie_vibe_credentials", _cred_path)
_credentials = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_credentials)
client = anthropic.Anthropic(api_key=_credentials.ANTHROPIC_API_KEY)


# ── canonicalization ────────────────────────────────────────────────────────────
CANON_PROMPT = """You are cleaning up a list of "movie vibes" that people ask for on Reddit.

Each line below is a vibe label followed by how many times people asked for it:

{vibe_lines}

Many of these mean the same thing in different words (e.g. "cozy and warm",
"feel-good and comforting", and "comfort watch" are one vibe). Group every label
that is practically the same request under a single clear CANONICAL label.

Rules:
- Aim for roughly {target} canonical groups — the distinct things people actually
  look for. Merge aggressively when labels mean the same thing; keep genuinely
  different requests (e.g. "slow burn dread" vs "feel-good adventure") separate.
- The canonical label should be short (1-5 words), lowercase, and natural-sounding
  — prefer the clearest phrasing, which may be one of the inputs or your own.
- EVERY input label must appear in exactly one group.

Return ONLY valid JSON in this exact shape:
{{
  "groups": [
    {{"canonical": "cozy and comforting", "members": ["cozy and warm", "comfort watch", ...]}},
    ...
  ]
}}
"""


def canonicalize(raw_vibes: dict) -> dict[str, str]:
    """Ask Claude to map each raw vibe -> a canonical vibe label.

    Returns {raw_vibe: canonical_vibe}. Any vibe the model drops falls back to
    itself so nothing is silently lost.
    """
    # demand = how many movie-mentions sat under each raw vibe (rough popularity)
    demand = {
        vibe: sum(m["mention_count"] for m in movies.values())
        for vibe, movies in raw_vibes.items()
    }
    vibe_lines = "\n".join(
        f"- {vibe} ({demand[vibe]})"
        for vibe in sorted(demand, key=demand.get, reverse=True)
    )

    msg = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        messages=[{
            "role": "user",
            "content": CANON_PROMPT.format(vibe_lines=vibe_lines, target=TARGET_VIBES),
        }],
    )
    raw = msg.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    groups = json.loads(raw)["groups"]

    mapping: dict[str, str] = {}
    for g in groups:
        canon = g["canonical"].strip().lower()
        for member in g["members"]:
            mapping[member] = canon

    # safety net: anything Claude forgot maps to itself
    for vibe in raw_vibes:
        mapping.setdefault(vibe, vibe)
    return mapping


# ── merge ───────────────────────────────────────────────────────────────────────
def _blank_node():
    return {"total_confidence": 0.0, "total_upvotes": 0, "mention_count": 0, "year": None}


def merge_raw_vibes(raw_vibes: dict, mapping: dict[str, str]) -> dict:
    """Collapse raw vibes into canonical buckets, summing each movie's stats."""
    merged: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(_blank_node))

    for vibe, movies in raw_vibes.items():
        canon = mapping.get(vibe, vibe)
        for title, stats in movies.items():
            node = merged[canon][title]
            node["total_confidence"] += stats["total_confidence"]
            node["total_upvotes"]    += stats["total_upvotes"]
            node["mention_count"]    += stats["mention_count"]
            node["year"]              = stats.get("year") or node["year"]
    return merged


def build_final(merged: dict) -> dict:
    """Rank vibes by total demand, keep the top MAX_VIBES, rank movies within each."""
    by_demand = sorted(
        merged.items(),
        key=lambda kv: sum(m["mention_count"] for m in kv[1].values()),
        reverse=True,
    )
    final = {}
    for vibe, movies in by_demand[:MAX_VIBES]:
        final[vibe] = rank_movies(movies, TOP_MOVIES)
    return final


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    raw_vibes = json.loads(Path(RAW_FILE).read_text())
    print(f"Loaded {len(raw_vibes)} raw vibes from {RAW_FILE}")

    print("Asking Claude to group near-duplicate vibes...")
    mapping = canonicalize(raw_vibes)

    merged = merge_raw_vibes(raw_vibes, mapping)
    final = build_final(merged)

    Path(OUTPUT_FILE).write_text(json.dumps(final, indent=2))
    Path(MAP_FILE).write_text(json.dumps(mapping, indent=2))

    print(f"\nMerged {len(raw_vibes)} raw vibes -> {len(merged)} canonical "
          f"(kept top {len(final)}).")
    print(f"Saved final graph to {OUTPUT_FILE}")
    print(f"Saved raw->canonical map to {MAP_FILE}")

    print("\nTop 10 vibes by demand:")
    for vibe, movies in list(final.items())[:10]:
        top = movies[0]["title"] if movies else "none"
        print(f"  '{vibe}' → {top} ({len(movies)} movies)")


if __name__ == "__main__":
    main()
