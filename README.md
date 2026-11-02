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
.venv/bin/python build_candidates.py --tiers 1 2 3   # keyword candidates -> candidates.csv, excluded.csv, MANIFEST.txt
.venv/bin/python gemini_screen.py      # Gemini yes/no -> queue.csv (yes posts), gemini_rejected.csv, RUN.md
.venv/bin/python load_supabase.py       # schema + docs/config.js + posts + passcode, all from .env
.venv/bin/python export.py             # any time: human labels -> CSVs + agreement.txt
.venv/bin/python llm_label.py          # AI labels for the queue -> labels_llm_wide.csv / labels_llm_long.csv
```

Candidates are posts that match any tier 1–3 term in `lexicon.txt`. Endorsement posts are left out, because their stock "Grow our Economy, Cut Taxes" wording trips the economic terms. `excluded.csv` lists every left-out post with its reason.

Gemini (free tier, 50 posts per request) answers yes/no for "trade-related or could affect markets". Only "yes" posts enter the queue, newest first.
- **If Gemini fails** (key missing, quota, network), answers so far are kept in `screen_cache.jsonl` and unscreened posts stay in the queue. Rerun to finish.
- **Without Gemini:** `build_candidates.py` alone (default tiers 1 2) writes a keyword-only `queue.csv`.

`llm_label.py` has one Gemini model (`GEMINI_LABEL_MODEL`, default `gemini-3.5-flash-lite`) fill in the same form humans use for every queued post, 25 per request.
- **Validity:** answers that break the form's rules are not stored, and those posts are asked again on the next run.
- **Kept separate:** the AI labels never touch the human database.
- **Recorded:** each row records the model, the prompt hash and the time.

The posts table freezes once anyone has labeled. After that, `load_supabase.py` only updates the schema, `config.js` and the passcode, so change `TEAM_PASSCODE` and rerun to rotate it. `load_supabase.py --reset` saves every label to `backups/` and clears them, so a new queue can be loaded.

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
