# 6.4610 trade post labeling

Human labels for Trump Truth Social posts: is the post trade- or market-relevant, and what is its impact (positive / negative / neutral / uncertain) on each of ten core industries. Spec: `SPEC.md`.

The site is a static page on GitHub Pages. Labels live in Supabase Postgres. The page can only call the labeling functions in `supabase/schema.sql`, and every write needs the team passcode.

## For labelers

Open the site link, pick your name, and enter the team passcode.

| Key | Action |
|---|---|
| `Y` / `N` | Relevant yes / no. `N` saves immediately. |
| `1` `2` `3` `4` | Positive / negative / neutral / uncertain on the highlighted row, then move down |
| `↑` `↓` | Move between rows |
| `R` | Set every unanswered row to neutral |
| `Enter` | Submit |
| `S` | Skip. The post comes back to you after your other work. |
| `B` | Reopen your previous label to edit it |

Resolve (top bar) shows double-labeled posts where two people disagree. You only see posts you didn't label.

## For Varun: running the pipeline

The raw files `data.json` and `djt_posts_dec2025.csv` sit in the folder above this one.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env              # fill in every PASTE_/PICK_ value
.venv/bin/python build_candidates.py   # keyword queue -> queue.csv, excluded.csv, MANIFEST.txt
.venv/bin/python load_supabase.py       # schema + docs/config.js + posts + passcode, all from .env
.venv/bin/python export.py             # any time: labels -> CSVs + agreement.txt
```

The queue keeps posts that match a tier 1 (explicit trade) or tier 2 (economic mechanism) term in `lexicon.txt`. Endorsement posts are left out, because their stock "Grow our Economy, Cut Taxes" wording trips the economic terms. Posts are served newest first. `excluded.csv` lists every left-out post with its reason.

The posts table freezes once anyone has labeled. After that, `load_supabase.py` only updates the schema, `config.js` and the passcode, so change `TEAM_PASSCODE` and rerun to rotate it.

## Local preview without Supabase

```bash
.venv/bin/python dev_server.py --db postgresql://postgres@127.0.0.1:5432/postgres
```

This serves the page and imitates Supabase's RPC endpoint against any Postgres that has `schema.sql` applied and an `anon` role.

## Tests

```bash
.venv/bin/pytest
```

The database tests start a throwaway Postgres 15 (`PG_BIN` overrides the default `/opt/homebrew/opt/postgresql@15/bin`), apply `schema.sql`, and call the functions as the `anon` role, exactly as the site does.
