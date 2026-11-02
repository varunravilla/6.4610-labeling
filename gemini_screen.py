"""Step 2: Gemini yes/no relevance screen, which decides what enters the queue.

    python gemini_screen.py

Reads candidates.csv, asks Gemini (free tier) about 50 posts per request, caches
every answer in screen_cache.jsonl, and writes queue.csv (Gemini "yes" posts,
newest first), gemini_rejected.csv (the "no" posts), and RUN.md.

If the key is missing, invalid, or out of quota, the script stops asking, keeps
what it has, and still writes queue.csv: unscreened posts stay in the queue.
Rerun later to screen the rest (only possible before anyone labels).
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from env import load_env
from queue_builder import order_queue

HERE = Path(__file__).parent
API = "https://generativelanguage.googleapis.com/v1beta"
csv.field_size_limit(sys.maxsize)

PROMPT = """You screen Donald Trump Truth Social posts for a research project on how political statements affect industries and markets.

For each post, answer "yes" if it is trade-related (tariffs, duties, quotas, trade deals, import/export restrictions, trade deficits, sanctions on commerce) OR states a policy or concrete claim that could plausibly change costs, prices, production, employment, or demand for an industry or the economy (factories, energy prices, drug prices, interest rates, taxes, farm purchases, reshoring, inflation tied to a cause).
Answer "no" for campaign rallies, endorsements, legal fights, media criticism, immigration with no commercial claim, and economic cheerleading that names no policy and no industry mechanism.

Judge each post on its own text as of its timestamp.
Return only a JSON object mapping each post id to "yes" or "no".

Posts:
"""
PROMPT_HASH = hashlib.sha256(PROMPT.encode()).hexdigest()[:12]


class ScreenStopped(Exception):
    """The API can't be used right now (bad key, quota, network). Keep partial results."""


def _parse(text: str, ids: list[str]) -> dict[str, bool] | None:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    out = {}
    for pid in ids:
        answer = str(data.get(pid, "")).strip().lower()
        if answer in {"yes", "no"}:
            out[pid] = answer == "yes"
    return out


def _read_cache(path: Path) -> dict[str, bool]:
    results = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                results[row["id"]] = row["relevant"]
    return results


def screen(candidates: list[dict], ask, cache_path: Path, batch_size: int = 50) -> dict[str, bool]:
    """Return {post_id: relevant} for every post screened so far, this run or earlier.

    `ask(prompt, ids)` returns the model's raw text, or raises ScreenStopped."""
    results = _read_cache(cache_path)
    todo = [c for c in candidates if c["id"] not in results]
    with open(cache_path, "a") as cache:
        for start in range(0, len(todo), batch_size):
            batch = todo[start:start + batch_size]
            ids = [c["id"] for c in batch]
            body = "\n".join(json.dumps({"id": c["id"], "time": c["created_at"], "text": c["text"]}) for c in batch)
            try:
                text = ask(PROMPT + body, ids)
            except ScreenStopped as e:
                print(f"Gemini stopped: {e}. Kept {len(results)} answers; rerun later to finish.")
                break
            for pid, relevant in (_parse(text, ids) or {}).items():
                results[pid] = relevant
                cache.write(json.dumps({"id": pid, "relevant": relevant}) + "\n")
            cache.flush()
    return results


class GeminiClient:
    def __init__(self, key: str, model: str | None, pause: float):
        self.key, self.pause = key, pause
        self.model = model or self._pick_model()

    def _request(self, url: str, payload: dict | None = None) -> dict:
        req = urllib.request.Request(url, headers={"x-goog-api-key": self.key, "Content-Type": "application/json"},
                                     data=json.dumps(payload).encode() if payload else None)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code in (429, 503):  # quota window or temporary overload: wait and retry
                raise RateLimited(detail) from e
            raise ScreenStopped(f"HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise ScreenStopped(f"network error: {e}") from e

    def _pick_model(self) -> str:
        names = [m["name"].removeprefix("models/") for m in self._request(f"{API}/models?pageSize=200").get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
        flash = [n for n in names if "flash" in n and not re.search(r"lite|image|tts|audio|live|thinking|exp", n)]
        stable = [n for n in flash if "preview" not in n and re.search(r"\d", n)] or flash
        if not stable:
            raise ScreenStopped("no Gemini Flash model available to this key; set GEMINI_MODEL in .env")
        # newest version number first, e.g. gemini-3.6-flash over gemini-2.5-flash
        return max(stable, key=lambda n: [int(x) for x in re.findall(r"\d+", n)])

    def __call__(self, prompt: str, ids: list[str]) -> str:
        payload = {"contents": [{"parts": [{"text": prompt}]}],
                   "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
        for attempt in range(4):
            try:
                data = self._request(f"{API}/models/{self.model}:generateContent", payload)
                time.sleep(self.pause)
                parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                return "".join(p.get("text", "") for p in parts)
            except RateLimited as e:
                if "PerDay" in str(e) or attempt == 3:
                    raise ScreenStopped(f"rate limit: {e}") from e
                time.sleep(30 * (attempt + 1))
        raise ScreenStopped("rate limit")


class RateLimited(Exception):
    pass


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({**r, "matched_terms": "|".join(r["matched_terms"])})


def main():
    load_env()
    with open(HERE / "candidates.csv", newline="") as f:
        candidates = [{**r, "tier": int(r["tier"]), "matched_terms": r["matched_terms"].split("|")} for r in csv.DictReader(f)]

    key, model, stopped = os.environ.get("GEMINI_API_KEY", "").strip(), None, None
    cache = HERE / "screen_cache.jsonl"
    if not key or key.startswith("PASTE_"):
        stopped = "GEMINI_API_KEY not set in labeling/.env"
        results = _read_cache(cache)
    else:
        try:
            client = GeminiClient(key, os.environ.get("GEMINI_MODEL"), float(os.environ.get("GEMINI_PAUSE_SECONDS", "7")))
            model = client.model
            print(f"Screening {len(candidates)} posts with {model}...", flush=True)
            results = screen(candidates, client, cache, int(os.environ.get("GEMINI_BATCH_SIZE", "50")))
        except ScreenStopped as e:
            stopped = str(e)
            results = _read_cache(cache)
    if stopped:
        print(f"Gemini unavailable ({stopped}). Building the queue with what is cached.")

    queue = order_queue(candidates, results)
    write_csv(HERE / "queue.csv", queue, ["queue_rank", "queue_group", "id", "created_at", "era", "tier",
                                          "matched_terms", "gemini_relevant", "double_label", "url", "text"])
    rejected = [c for c in candidates if results.get(c["id"]) is False]
    write_csv(HERE / "gemini_rejected.csv", rejected, ["id", "created_at", "era", "tier", "matched_terms", "url", "text"])

    screened = sum(1 for c in candidates if c["id"] in results)
    by_tier = {t: (sum(c["tier"] == t for c in candidates), sum(q["tier"] == t for q in queue)) for t in (1, 2, 3)}
    (HERE / "RUN.md").write_text(
        "# Gemini relevance screen\n\n"
        f"- Last run: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
        f"- Model: {model or 'none this run'}\n"
        f"- Prompt hash: {PROMPT_HASH}\n"
        f"- Candidates: {len(candidates)} (keyword tiers 1-3, endorsements removed)\n"
        f"- Screened: {screened}; yes {sum(v is True for v in results.values())}, no {len(rejected)}; "
        f"unscreened posts stay in the queue\n"
        + "".join(f"- Tier {t}: {n} candidates -> {k} in queue\n" for t, (n, k) in by_tier.items())
        + f"- Queue: {len(queue)} posts, newest first; second term {sum(q['era'] == 'second_term' for q in queue)}, "
        f"earlier {sum(q['era'] == 'earlier' for q in queue)}; double-labeled {sum(q['double_label'] for q in queue)}\n"
        + (f"- Stopped early: {stopped}\n" if stopped else "")
        + "\nGemini decides only which posts humans see, never a label. Its knowledge cutoff postdates the posts; "
        "that cannot leak into training targets because humans make every label.\n"
    )
    print((HERE / "RUN.md").read_text())


if __name__ == "__main__":
    main()
