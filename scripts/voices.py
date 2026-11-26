"""Voice rotation for Off-Brand reviews.

Every new triage issue gets a writing assignment: a comedic voice and an
edge level. The picker keeps the site from going stale:

- no voice repeats within the last RECENT_WINDOW reviews or assignments
- voices used less often overall are more likely to come up
- no two "Roast" (edge 3) reviews in a row
- each voice only allows the edge levels it suits

The pick is seeded from the candidate id, so rerunning ingestion for the
same candidate gives the same assignment.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOICES_PATH = ROOT / "data" / "voices.json"

RECENT_WINDOW = 4
EDGE_WEIGHTS = {1: 3, 2: 5, 3: 2}  # Spicy is home base; Roast is a treat


def load_roster(path: Path = VOICES_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def history_from_reviews(items: list[dict]) -> list[tuple[str, int]]:
    """Newest first, as stored in reviews.json."""
    out = []
    for it in items:
        v = it.get("voice")
        if v:
            out.append((v, int(it.get("edge") or 2)))
    return out


def pick(history: list[tuple[str, int]], seed: str, roster: dict | None = None) -> dict:
    """history: newest first list of (voice_id, edge). Returns an assignment dict."""
    roster = roster or load_roster()
    voices = roster["voices"]
    rng = random.Random(seed)

    recent = {v for v, _ in history[:RECENT_WINDOW]}
    uses = Counter(v for v, _ in history)
    pool = [v for v in voices if v["id"] not in recent] or voices

    # Fewer past uses -> higher weight, so the whole roster gets airtime.
    top = max([uses[v["id"]] for v in pool] + [0])
    weights = [1 + top - uses[v["id"]] for v in pool]
    voice = rng.choices(pool, weights=weights, k=1)[0]

    last_edge = history[0][1] if history else None
    edges = [e for e in voice["edges"] if not (e == 3 and last_edge == 3)] or [min(voice["edges"])]
    edge = rng.choices(edges, weights=[EDGE_WEIGHTS[e] for e in edges], k=1)[0]

    return {
        "voice": voice["id"],
        "voice_name": voice["name"],
        "brief": voice["brief"],
        "tells_shape": voice["tells_shape"],
        "sample": voice["sample"],
        "edge": edge,
        "edge_name": roster["edges"][str(edge)]["name"],
        "edge_brief": roster["edges"][str(edge)]["brief"],
    }


def assign_batch(published: list[dict], candidate_ids: list[str]) -> dict[str, dict]:
    """Assign voices to several new candidates at once, each one counting
    as history for the next so a batch doesn't come out all the same."""
    roster = load_roster()
    history = history_from_reviews(published)
    out = {}
    for cid in candidate_ids:
        a = pick(history, seed=cid, roster=roster)
        out[cid] = a
        history.insert(0, (a["voice"], a["edge"]))
    return out


def assignment_markdown(a: dict) -> list[str]:
    return [
        "### 🎭 Writing assignment",
        f"**Voice:** {a['voice_name']}: {a['brief']}",
        f"**Edge:** {a['edge_name']}: {a['edge_brief']}",
        f"**Tells shape:** {a['tells_shape']}",
        f"**Tone sample:** _{a['sample']}_",
        "Don't like it? Change the `voice:` / `edge:` lines in your reply. Rules in VOICE.md still apply.",
    ]


def validate(voice_id: str | None, edge: str | int | None, roster: dict | None = None):
    """Returns (voice_id, voice_name, edge) or None if invalid/missing."""
    if not voice_id:
        return None
    roster = roster or load_roster()
    match = next((v for v in roster["voices"] if v["id"] == voice_id.strip()), None)
    if not match:
        return None
    try:
        e = int(edge) if edge not in (None, "") else 2
    except ValueError:
        return None
    if e not in match["edges"]:
        return None
    return match["id"], match["name"], e
