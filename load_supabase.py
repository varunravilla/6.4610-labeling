"""Step 3: create the Supabase tables and functions, load the queue, set the passcode.

    python load_supabase.py

Reads everything from labeling/.env: applies schema.sql, writes site/config.js, loads
queue.csv for ANNOTATORS, and sets TEAM_PASSCODE. Safe to rerun: once anyone has
labeled, posts are frozen and only the schema, config, and passcode are updated.
"""
from __future__ import annotations

import argparse
import csv
import json
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


def write_site_config(url: str, anon_key: str) -> None:
    (HERE / "site" / "config.js").write_text(
        "// Written by load_supabase.py from .env. Public values: the anon key can only call the\n"
        "// labeling functions, and every write also needs the team passcode.\n"
        f"window.LABELING_CONFIG = {{\n  supabaseUrl: {json.dumps(url)},\n  supabaseAnonKey: {json.dumps(anon_key)},\n}};\n")


def _env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return None if not value or value.startswith(("PASTE_", "PICK_")) else value


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotators", nargs="+", help="defaults to ANNOTATORS in .env")
    ap.add_argument("--passcode", help="defaults to TEAM_PASSCODE in .env")
    args = ap.parse_args()
    load_env()
    url = _env("SUPABASE_DB_URL")
    if not url:
        raise SystemExit("Fill in SUPABASE_DB_URL in labeling/.env (see .env.example).")
    annotators = args.annotators or (_env("ANNOTATORS") or "").split()
    passcode = args.passcode or _env("TEAM_PASSCODE")

    if _env("SUPABASE_URL") and _env("SUPABASE_ANON_KEY"):
        write_site_config(_env("SUPABASE_URL").rstrip("/"), _env("SUPABASE_ANON_KEY"))
        print("Wrote site/config.js. Commit and push it to update the live site.")
    else:
        print("SUPABASE_URL / SUPABASE_ANON_KEY not filled in; site/config.js left unchanged.")

    with psycopg.connect(url, autocommit=True) as conn:
        apply_migration(conn)
        print("Database tables and functions are up to date.")
        if conn.execute("select exists (select 1 from labels)").fetchone()[0]:
            print("Labels already exist, so the queue is frozen; posts were not reloaded.")
        elif annotators:
            rows = read_queue(HERE / "queue.csv")
            load_posts(conn, rows, annotators)
            print(f"Loaded {len(rows)} posts for {', '.join(annotators)}.")
        if passcode:
            set_passcode(conn, passcode)
            print("Team passcode set.")
        else:
            print("TEAM_PASSCODE not filled in; nobody can log in until it is set.")


if __name__ == "__main__":
    main()
