"""Step 1: build the labeling queue from data.json and the CSV.

    python build_candidates.py

Keeps tier 1 and tier 2 keyword matches, minus endorsements, newest first.
Writes queue.csv, excluded.csv (with a reason per post), excluded_sample.csv
(100 no-keyword posts across years, for a recall spot-check), and MANIFEST.txt.
"""
import csv
import hashlib
import json
import random
import sys
from pathlib import Path

from queue_builder import SEED, WINDOW_END, WINDOW_START, find_candidates, load_lexicon, order_queue

HERE = Path(__file__).parent
ROOT = HERE.parent
csv.field_size_limit(sys.maxsize)


def write_csv(path, rows, fields):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({**r, "matched_terms": "|".join(r.get("matched_terms", []))})


def year_spread_sample(rows, n=100):
    rng = random.Random(SEED)
    by_year = {}
    for r in rows:
        by_year.setdefault(r["created_at"][:4], []).append(r)
    years = sorted(by_year)
    picked = []
    for i, y in enumerate(years):
        k = n // len(years) + (1 if i < n % len(years) else 0)
        picked += rng.sample(by_year[y], min(k, len(by_year[y])))
    return sorted(picked, key=lambda r: r["created_at"])


def main():
    json_records = json.loads((ROOT / "data.json").read_text())
    with open(ROOT / "djt_posts_dec2025.csv", newline="") as f:
        csv_rows = list(csv.DictReader(f))
    result = find_candidates(json_records, csv_rows, load_lexicon(HERE / "lexicon.txt"))

    queue = order_queue(result.candidates)
    write_csv(HERE / "queue.csv", queue, ["queue_rank", "queue_group", "id", "created_at", "era", "tier",
                                          "matched_terms", "double_label", "url", "text"])
    write_csv(HERE / "excluded.csv", result.excluded, ["id", "created_at", "era", "reason", "tier", "matched_terms", "url", "text"])
    no_keyword = [r for r in result.excluded if r["reason"] == "no_keyword"]
    write_csv(HERE / "excluded_sample.csv", year_spread_sample(no_keyword), ["id", "created_at", "era", "url", "text"])

    digest = hashlib.sha256("\n".join(c["id"] + "\t" + c["text"] for c in queue).encode()).hexdigest()
    counts = {}
    for c in queue:
        counts[(c["era"], c["tier"])] = counts.get((c["era"], c["tier"]), 0) + 1
    reasons = {}
    for r in result.excluded:
        reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    lines = [
        f"window_start\t{WINDOW_START}",
        f"window_end_exclusive\t{WINDOW_END}",
        "rule\ttier 1 + tier 2 keyword match, endorsements removed, newest first",
        f"queue\t{len(queue)}",
        f"double_labeled\t{sum(r['double_label'] for r in queue)}",
        *[f"excluded\t{reason}\t{n}" for reason, n in sorted(reasons.items())],
        *[f"count\t{era}\ttier{tier}\t{n}" for (era, tier), n in sorted(counts.items())],
        f"queue_text_sha256\t{digest}",
        "queue_ids_in_order\t" + ",".join(c["id"] for c in queue),
    ]
    (HERE / "MANIFEST.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:-1]))


if __name__ == "__main__":
    main()
