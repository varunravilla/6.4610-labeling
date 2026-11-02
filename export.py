"""Step 4: pull every label out of Supabase into CSVs in this folder.

    python export.py

Writes labels_wide.csv, labels_long.csv, gold.csv, agreement.txt, collect_report.txt.
"""
from __future__ import annotations

import csv
import os
from collections import Counter
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from env import load_env

HERE = Path(__file__).parent
CORE = ["steel_aluminum", "autos", "semiconductors", "agriculture", "energy", "pharmaceuticals",
        "technology", "financials", "consumer_retail", "broad_economy"]
POST_FIELDS = ["post_id", "created_at", "era", "queue_group", "tier", "gemini_relevant", "double_label"]


def cohen_kappa(a: list, b: list) -> float | None:
    n = len(a)
    if n == 0:
        return None
    observed = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def _write(path: Path, rows: list[dict], fields: list[str]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _extras_cell(extras: list[dict]) -> str:
    return " || ".join(f"{e['industry']}{'(' + e['other_name'] + ')' if e.get('other_name') else ''}:{e['impact']}"
                       for e in extras)


def _same(x: dict, y: dict) -> bool:
    return (x["relevant"], x["impacts"], x["extras"]) == (y["relevant"], y["impacts"], y["extras"])


def export(conn, out: Path) -> None:
    cur = conn.cursor(row_factory=dict_row)
    posts = {p["id"]: p for p in cur.execute("select * from posts order by queue_rank")}
    labels = cur.execute("select * from labels order by post_id, annotator").fetchall()
    gold = {g["post_id"]: g for g in cur.execute("select * from gold")}

    def post_cols(pid):
        p = posts[pid]
        return {"post_id": pid, "created_at": p["created_at"].isoformat(), "era": p["era"],
                "queue_group": p["queue_group"], "tier": p["tier"], "gemini_relevant": p["gemini_relevant"],
                "double_label": p["double_label"]}

    by_post: dict[str, list[dict]] = {}
    for l in labels:
        by_post.setdefault(l["post_id"], []).append(l)

    wide, long = [], []
    for l in labels:
        base = {**post_cols(l["post_id"]), "annotator": l["annotator"], "relevant": l["relevant"],
                "labeled_at": l["labeled_at"].isoformat()}
        wide.append({**base, **l["impacts"], "extras": _extras_cell(l["extras"])})
        for ind in CORE:
            long.append({**base, "industry": ind, "other_name": "", "impact": l["impacts"][ind]})
        for e in l["extras"]:
            long.append({**base, "industry": e["industry"], "other_name": e.get("other_name", ""), "impact": e["impact"]})

    gold_rows, open_conflicts = [], []
    for pid, ls in by_post.items():
        if pid in gold:
            final, resolved = gold[pid], True
        elif len(ls) == 1 or _same(ls[0], ls[1]):
            final, resolved = ls[0], False
        else:
            open_conflicts.append(pid)
            continue
        base = {**post_cols(pid), "relevant": final["relevant"], "n_labels": len(ls), "resolved": resolved}
        gold_rows += [{**base, "industry": ind, "other_name": "", "impact": final["impacts"][ind]} for ind in CORE]
        gold_rows += [{**base, "industry": e["industry"], "other_name": e.get("other_name", ""), "impact": e["impact"]}
                      for e in final["extras"]]

    lab_fields = POST_FIELDS + ["annotator", "relevant", "labeled_at"]
    _write(out / "labels_wide.csv", wide, lab_fields + CORE + ["extras"])
    _write(out / "labels_long.csv", long, lab_fields + ["industry", "other_name", "impact"])
    _write(out / "gold.csv", gold_rows, POST_FIELDS + ["relevant", "n_labels", "resolved", "industry", "other_name", "impact"])

    pairs = [ls for ls in by_post.values() if len(ls) == 2]
    rel_k = cohen_kappa([p[0]["relevant"] for p in pairs], [p[1]["relevant"] for p in pairs])
    imp_k = cohen_kappa([p[0]["impacts"][i] for p in pairs for i in CORE], [p[1]["impacts"][i] for p in pairs for i in CORE])
    both_rel = [p for p in pairs if p[0]["relevant"] and p[1]["relevant"]]
    imp_rel_k = cohen_kappa([p[0]["impacts"][i] for p in both_rel for i in CORE],
                            [p[1]["impacts"][i] for p in both_rel for i in CORE])
    fmt = lambda k: "n/a" if k is None else f"{k:.3f}"
    (out / "agreement.txt").write_text(
        f"Double-labeled posts with two labels: {len(pairs)} (before resolution)\n"
        f"Cohen's kappa, relevance: {fmt(rel_k)}\n"
        f"Cohen's kappa, core impacts over all (post, industry) pairs: {fmt(imp_k)}\n"
        f"Cohen's kappa, core impacts where both said relevant ({len(both_rel)} posts): {fmt(imp_rel_k)}\n"
        f"Target: 0.6 or higher.\n")

    unlabeled = sum(1 for pid in posts if pid not in by_post)
    (out / "collect_report.txt").write_text(
        f"Posts with no label yet: {unlabeled} of {len(posts)}\n"
        f"Open conflicts (left out of gold.csv until resolved): {len(open_conflicts)}\n"
        + "".join(f"  {pid}\n" for pid in open_conflicts))


def main():
    load_env()
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise SystemExit("Set SUPABASE_DB_URL in labeling/.env")
    with psycopg.connect(url) as conn:
        export(conn, HERE)
    print((HERE / "agreement.txt").read_text() + (HERE / "collect_report.txt").read_text().split("\n")[0])


if __name__ == "__main__":
    main()
