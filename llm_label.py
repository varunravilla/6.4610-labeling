"""AI labels: Gemini fills in the same form humans do, for every post in the human queue.

    python llm_label.py

Reads queue.csv, asks one Gemini model (GEMINI_LABEL_MODEL, default gemini-3.5-flash-lite)
about 25 posts per request, caches each valid answer in llm_cache.jsonl, and writes
labels_llm_wide.csv and labels_llm_long.csv. These never go into the human database.

An answer that breaks the form's rules is not stored; that post is asked again on the
next run. If the key fails or quota runs out, rerun later to finish.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from env import load_env
from gemini_screen import GeminiClient, ScreenStopped

HERE = Path(__file__).parent
csv.field_size_limit(sys.maxsize)

CORE = ["steel_aluminum", "autos", "semiconductors", "agriculture", "energy", "pharmaceuticals",
        "technology", "financials", "consumer_retail", "broad_economy"]
EXTRAS = {"defense", "aerospace", "minerals_metals", "shipping", "lumber_housing", "other"}
IMPACTS = {"positive", "negative", "neutral", "uncertain"}

PROMPT = """You label Donald Trump Truth Social posts for a research project on how political statements affect industries.
Apply exactly the rubric human annotators use.

RELEVANT is true when the post concerns cross-border trade policy or flows (tariffs, duties, quotas, trade deals, import/export restrictions, trade deficits) OR states a policy or concrete claim that would change costs, prices, production, employment, or demand for an industry or the economy over the next year.
Rallies, endorsements, legal fights, media criticism, and cheerleading that names no policy or mechanism are NOT relevant.

If relevant, give an impact for EVERY core industry, judging the following year, conditional on the stated policy being implemented, using only the post and what was public at its timestamp:
- positive / negative: a material benefit or harm for that industry
- neutral: no identifiable material effect
- uncertain: the text is too thin, or effects compete and do not resolve
Industries named or implied get their own value when the mechanism differs (steel tariffs: steel positive, automakers who buy steel often negative).
broad_economy is for across-the-board claims with no industry split.

Core industries (reference ETF): steel_aluminum (SLX), autos (CARZ), semiconductors (SOXX), agriculture (MOO), energy (XLE), pharmaceuticals (PPH), technology (XLK), financials (XLF), consumer_retail (XRT), broad_economy.
Optional extras, only when materially affected: defense, aerospace, minerals_metals, shipping, lumber_housing, other (other needs "other_name").

If NOT relevant: every core industry is "neutral" and extras is empty.

Return only a JSON array with one object per post:
[{"id": "<post id>", "relevant": true|false, "impacts": {"steel_aluminum": "...", ... all 10 ...}, "extras": [{"industry": "...", "impact": "...", "other_name": "..."}]}]

Posts:
"""
PROMPT_HASH = hashlib.sha256(PROMPT.encode()).hexdigest()[:12]


def valid(label: dict) -> bool:
    """The same rules the database enforces on human labels."""
    impacts, extras = label.get("impacts"), label.get("extras", [])
    if not isinstance(label.get("relevant"), bool) or not isinstance(impacts, dict) or not isinstance(extras, list):
        return False
    if set(impacts) != set(CORE) or any(v not in IMPACTS for v in impacts.values()):
        return False
    if not label["relevant"] and (any(v != "neutral" for v in impacts.values()) or extras):
        return False
    for e in extras:
        if not isinstance(e, dict) or e.get("industry") not in EXTRAS or e.get("impact") not in IMPACTS:
            return False
        if e["industry"] == "other" and not str(e.get("other_name") or "").strip():
            return False
    return True


def _parse(text: str) -> list[dict]:
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return [d for d in data if isinstance(d, dict)]


def _read_cache(path: Path) -> dict[str, dict]:
    labels = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                labels[row["id"]] = row
    return labels


def label_posts(posts: list[dict], ask, cache_path: Path, batch_size: int = 25, model: str = "") -> dict[str, dict]:
    """Return {post_id: label} for every post labeled so far, this run or earlier."""
    labels = _read_cache(cache_path)
    todo = [p for p in posts if p["id"] not in labels]
    with open(cache_path, "a") as cache:
        for start in range(0, len(todo), batch_size):
            batch = todo[start:start + batch_size]
            ids = {p["id"] for p in batch}
            body = "\n".join(json.dumps({"id": p["id"], "time": p["created_at"], "text": p["text"]}) for p in batch)
            try:
                text = ask(PROMPT + body, sorted(ids))
            except ScreenStopped as e:
                print(f"Gemini stopped: {e}. Kept {len(labels)} labels; rerun later to finish.", flush=True)
                break
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for item in _parse(text):
                pid = str(item.get("id"))
                if pid in ids and pid not in labels and valid(item):
                    row = {"id": pid, "relevant": item["relevant"], "impacts": item["impacts"],
                           "extras": [{k: e[k] for k in ("industry", "impact", "other_name") if e.get(k)} for e in item.get("extras", [])],
                           "model": model, "prompt_hash": PROMPT_HASH, "labeled_at": now}
                    labels[pid] = row
                    cache.write(json.dumps(row) + "\n")
            cache.flush()
            print(f"{len(labels)} of {len(posts)} labeled", flush=True)
    return labels


def main():
    load_env()
    with open(HERE / "queue.csv", newline="") as f:
        queue = list(csv.DictReader(f))
    model = os.environ.get("GEMINI_LABEL_MODEL", "gemini-3.5-flash-lite")
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    cache = HERE / "llm_cache.jsonl"
    if not key or key.startswith("PASTE_"):
        print("GEMINI_API_KEY not set in labeling/.env; writing CSVs from cached labels only.")
        labels = _read_cache(cache)
    else:
        try:
            client = GeminiClient(key, model, float(os.environ.get("GEMINI_PAUSE_SECONDS", "7")))
            print(f"Labeling {len(queue)} posts with {model}...", flush=True)
            labels = label_posts(queue, client, cache, int(os.environ.get("GEMINI_LABEL_BATCH_SIZE", "25")), model)
        except ScreenStopped as e:
            print(f"Gemini unavailable ({e}); writing CSVs from cached labels only.")
            labels = _read_cache(cache)

    post_cols = ["post_id", "created_at", "era", "tier", "queue_rank", "double_label"]
    meta = ["model", "prompt_hash", "labeled_at"]
    wide, long = [], []
    for q in queue:
        lab = labels.get(q["id"])
        if not lab:
            continue
        base = {"post_id": q["id"], "created_at": q["created_at"], "era": q["era"], "tier": q["tier"],
                "queue_rank": q["queue_rank"], "double_label": q["double_label"], "relevant": lab["relevant"],
                **{m: lab[m] for m in meta}}
        wide.append({**base, **lab["impacts"],
                     "extras": " || ".join(f"{e['industry']}{'(' + e['other_name'] + ')' if e.get('other_name') else ''}:{e['impact']}"
                                           for e in lab["extras"])})
        long += [{**base, "industry": ind, "other_name": "", "impact": lab["impacts"][ind]} for ind in CORE]
        long += [{**base, "industry": e["industry"], "other_name": e.get("other_name", ""), "impact": e["impact"]}
                 for e in lab["extras"]]
    for name, rows, fields in [
        ("labels_llm_wide.csv", wide, post_cols + ["relevant"] + CORE + ["extras"] + meta),
        ("labels_llm_long.csv", long, post_cols + ["relevant", "industry", "other_name", "impact"] + meta),
    ]:
        with open(HERE / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
    print(f"Wrote labels_llm_wide.csv and labels_llm_long.csv: {len(wide)} of {len(queue)} posts labeled "
          f"({sum(r['relevant'] for r in wide)} relevant). Model {model}, prompt {PROMPT_HASH}.")


if __name__ == "__main__":
    main()
