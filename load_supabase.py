"""Step 3: create the Supabase tables and functions, load the queue, set the passcode.

    python load_supabase.py --annotators Wyatt Matthew Varun Kevin --passcode '<team passcode>'

Reads SUPABASE_DB_URL from labeling/.env. Refuses to reload posts once any label exists.
Rerun with only --passcode to rotate the passcode.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

import psycopg

from gemini_screen import load_env

HERE = Path(__file__).parent
csv.field_size_limit(sys.maxsize)


def apply_migration(conn) -> None:
    conn.execute((HERE / "supabase" / "schema.sql").read_text())


def load_posts(conn, rows: list[dict], annotators: list[str]) -> None:
    if conn.execute("select exists (select 1 from labels)").fetchone()[0]:
        raise SystemExit("Labels already exist; the queue is frozen. Not reloading posts.")
    with conn.transaction():
        conn.execute("delete from claims; delete from skips; delete from posts; delete from annotators;")
        with conn.cursor() as cur:
            cur.executemany("insert into annotators (name) values (%s)", [(a,) for a in annotators])
            cur.executemany(
                "insert into posts (id, created_at, text, url, era, tier, matched_terms, gemini_relevant,"
                " queue_group, queue_rank, double_label) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [(r["id"], r["created_at"], r["text"], r["url"], r["era"], r["tier"], r["matched_terms"],
                  r["gemini_relevant"], r["queue_group"], r["queue_rank"], r["double_label"]) for r in rows],
            )


def set_passcode(conn, passcode: str) -> None:
    conn.execute(
        "insert into settings (key, value) values ('passcode_hash', extensions.crypt(%s, extensions.gen_salt('bf')))"
        " on conflict (key) do update set value = excluded.value", (passcode,))


def read_queue(path: Path) -> list[dict]:
    def boolish(v):
        return None if v == "" else v == "True"

    with open(path, newline="") as f:
        return [{**r, "tier": int(r["tier"]), "queue_group": int(r["queue_group"]),
                 "queue_rank": int(r["queue_rank"]), "matched_terms": r["matched_terms"].split("|"),
                 "gemini_relevant": boolish(r["gemini_relevant"]), "double_label": r["double_label"] == "True"}
                for r in csv.DictReader(f)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotators", nargs="+")
    ap.add_argument("--passcode")
    args = ap.parse_args()
    load_env()
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise SystemExit("Set SUPABASE_DB_URL in labeling/.env (Supabase > Connect > Session pooler URI).")

    with psycopg.connect(url, autocommit=True) as conn:
        apply_migration(conn)
        if args.annotators:
            rows = read_queue(HERE / "queue.csv")
            load_posts(conn, rows, args.annotators)
            print(f"Loaded {len(rows)} posts for {', '.join(args.annotators)}.")
        if args.passcode:
            set_passcode(conn, args.passcode)
            print("Passcode set.")


if __name__ == "__main__":
    main()
