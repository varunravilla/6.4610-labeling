"""Step 1: build the keyword candidate queue from data.json and the CSV.

    python build_candidates.py

Writes candidates.csv, excluded_no_keyword.csv, excluded_sample.csv, MANIFEST.txt.
"""
import csv
import hashlib
import json
import random
import sys
from pathlib import Path

from queue_builder import SEED, WINDOW_END, WINDOW_START, find_candidates, load_lexicon

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

    fields = ["id", "created_at", "era", "tier", "matched_terms", "url", "text"]
    write_csv(HERE / "candidates.csv", result.candidates, fields)
    write_csv(HERE / "excluded_no_keyword.csv", result.excluded, fields[:3] + fields[5:])
    write_csv(HERE / "excluded_sample.csv", year_spread_sample(result.excluded), fields[:3] + fields[5:])

    digest = hashlib.sha256("\n".join(c["id"] + "\t" + c["text"] for c in result.candidates).encode()).hexdigest()
    counts = {}
    for c in result.candidates:
        counts[(c["era"], c["tier"])] = counts.get((c["era"], c["tier"]), 0) + 1
    lines = [
        f"window_start\t{WINDOW_START}",
        f"window_end_exclusive\t{WINDOW_END}",
        f"candidates\t{len(result.candidates)}",
        f"excluded_no_keyword\t{len(result.excluded)}",
        *[f"count\t{era}\ttier{tier}\t{n}" for (era, tier), n in sorted(counts.items())],
        f"candidate_text_sha256\t{digest}",
        "candidate_ids\t" + ",".join(c["id"] for c in result.candidates),
    ]
    (HERE / "MANIFEST.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:-1]))


if __name__ == "__main__":
    main()
