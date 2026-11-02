"""Builds the frozen labeling queue from the Truth Social sources.

find_candidates() applies the hard drops and the keyword lexicon. The queue keeps
tier 1 and tier 2 posts and leaves out endorsements, whose stock "Grow our Economy,
Cut Taxes" wording trips the economic keywords.
order_queue() orders the queue newest first and draws the double-label sample.
Both are pure: no files, no network.
"""
from __future__ import annotations

import html
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

WINDOW_START = "2022-02-14T15:54:32.528Z"
WINDOW_END = "2026-11-01"  # exclusive: posts on or after Nov 1 2026 stay out
SECOND_TERM_START = "2025-01-20"
SEED = 4610
DOUBLE_LABEL_FRACTION = 0.2

# A stem longer than 4 characters matches the stem plus one of these inflection
# endings, so `tariff` matches `tariffs` and `manufactur` matches `manufacturing`,
# but `import` does not match `important` and `invest` does not match `investigation`.
INFLECTIONS = (
    "s|es|e|ed|d|ing|ings|er|ers|or|ors|ory|ion|ions|ation|ations|al|ally|ary|"
    "ity|ities|y|ies|ic|ics|ical|ically|ist|ists|ism|m|t|ts|ize|izes|ized|izing|"
    "ment|ments|ure|ures|ured|uring|ate|ates|ated|ating|le|les|led|ling|ry"
)
PARTNERS = (
    "china chinese canada canadian mexico mexican japan japanese india indian europe "
    "european eu germany german vietnam korea korean taiwan brazil brazilian"
).split()

QUEUE_TIERS = {1, 2}
_ENDORSEMENT = re.compile(r"endorsement", re.I)
_MOJIBAKE = re.compile("[\u00c2-\u00f4][\u0080-\u00bf]{1,3}")
_URL = re.compile(r"https?://\S+")
_LEFT = r"(?<![a-z0-9])"
_RIGHT = r"(?![a-z0-9])"


@dataclass
class CandidateResult:
    candidates: list[dict] = field(default_factory=list)
    excluded: list[dict] = field(default_factory=list)


def load_lexicon(path: Path | str) -> list[tuple[int, str]]:
    lexicon = []
    for line in Path(path).read_text().splitlines():
        if line.strip():
            tier, term = line.split("\t", 1)
            lexicon.append((int(tier), term.strip().lower()))
    return lexicon


def _word_pattern(word: str, last: bool) -> str:
    escaped = re.escape(word)
    if not last:
        return escaped
    if len(word) <= 4:
        return escaped + "(?:s|es)?"
    return escaped + f"(?:{INFLECTIONS})?"


def _term_regex(term: str) -> re.Pattern:
    words = term.split()
    body = r"\s+".join(_word_pattern(w, i == len(words) - 1) for i, w in enumerate(words))
    return re.compile(_LEFT + body + _RIGHT)


_PARTNER_RE = re.compile(_LEFT + "(?:" + "|".join(PARTNERS) + ")" + _RIGHT)
_MONEY_RE = re.compile(r"\$|%|" + _LEFT + r"(?:billion|billions|trillion|trillions|percent)" + _RIGHT)


def _repair(text: str) -> str:
    """Undo UTF-8 text that was decoded as Latin-1 somewhere upstream ("countriesâand")."""
    def fix(m):
        try:
            return m.group(0).encode("latin-1").decode("utf-8")
        except UnicodeDecodeError:
            return m.group(0)
    return html.unescape(_MOJIBAKE.sub(fix, text))


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _is_url_only(text: str) -> bool:
    return len(_URL.sub("", text).strip()) < 40


def _truthy(value) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def _iso(csv_date: str) -> str:
    # CSV dates look like "2025-12-31 21:54:21+00:00"; make them sortable with the JSON's ISO strings.
    return csv_date.replace(" ", "T").replace("+00:00", ".000Z")


def _merge_sources(json_records: list[dict], csv_rows: list[dict]) -> list[dict]:
    flags = {}
    for row in csv_rows:
        if row.get("platform", "Truth Social") != "Truth Social":
            continue
        flags[str(row["id"])] = row

    posts = []
    for rec in json_records:
        pid = str(rec["id"])
        csv = flags.pop(pid, None)
        posts.append({
            "id": pid,
            "created_at": rec["created_at"],
            "text": _repair(rec.get("content") or ""),
            "url": rec.get("url") or "",
            "repost": (rec.get("content") or "").startswith("RT @") or (csv is not None and _truthy(csv.get("repost_flag"))),
            "deleted": csv is not None and _truthy(csv.get("deleted_flag")),
        })
    for pid, row in flags.items():  # CSV-only Truth Social posts
        posts.append({
            "id": pid,
            "created_at": _iso(row["date"]),
            "text": _repair(row.get("text") or ""),
            "url": row.get("post_url") or "",
            "repost": _truthy(row.get("repost_flag")) or (row.get("text") or "").startswith("RT @"),
            "deleted": _truthy(row.get("deleted_flag")),
        })
    return posts


def find_candidates(json_records: list[dict], csv_rows: list[dict], lexicon: list[tuple[int, str]],
                    tiers: set[int] = QUEUE_TIERS) -> CandidateResult:
    compiled = [(tier, term, _term_regex(term)) for tier, term in lexicon]
    posts = sorted(_merge_sources(json_records, csv_rows), key=lambda p: (p["created_at"], p["id"]))

    result = CandidateResult()
    seen_texts = set()
    for p in posts:
        if not (WINDOW_START <= p["created_at"] < WINDOW_END):
            continue
        if p["repost"] or p["deleted"] or not p["text"].strip() or _is_url_only(p["text"]):
            continue
        norm = _normalize(p["text"])
        if norm in seen_texts:
            continue
        seen_texts.add(norm)

        matches = [(tier, term) for tier, term, rx in compiled if rx.search(norm)]
        row = {
            "id": p["id"],
            "created_at": p["created_at"],
            "text": p["text"],
            "url": p["url"],
            "era": "second_term" if p["created_at"] >= SECOND_TERM_START else "earlier",
        }
        if matches:
            row["tier"] = min(t for t, _ in matches)
            row["matched_terms"] = sorted({term for _, term in matches})
        elif _PARTNER_RE.search(norm) and _MONEY_RE.search(norm):
            row["tier"] = 3
            row["matched_terms"] = ["partner+money"]

        if "tier" not in row:
            result.excluded.append({**row, "reason": "no_keyword"})
        elif _ENDORSEMENT.search(norm):
            result.excluded.append({**row, "reason": "endorsement"})
        elif row["tier"] not in tiers:
            result.excluded.append({**row, "reason": "tier3_only"})
        else:
            result.candidates.append(row)
    return result


def order_queue(candidates: list[dict], screen: dict[str, bool] | None = None) -> list[dict]:
    """Newest post first. queue_group is 1 for the second term, 2 for earlier posts.

    With a Gemini screen, posts it marked not relevant are left out. A post with no
    answer stays in, so the queue still builds if the key fails partway."""
    screen = screen or {}
    rows = [{**c, "gemini_relevant": screen.get(c["id"]), "queue_group": 1 if c["era"] == "second_term" else 2}
            for c in candidates if screen.get(c["id"]) is not False]
    rows.sort(key=lambda r: (r["created_at"], r["id"]), reverse=True)
    for rank, r in enumerate(rows, start=1):
        r["queue_rank"] = rank

    strata: dict[tuple[int, int], list[str]] = {}
    for r in rows:
        strata.setdefault((r["queue_group"], r["tier"]), []).append(r["id"])
    doubled = set()
    for (group, tier), members in strata.items():
        rng = random.Random(f"{SEED}:{group}:{tier}")
        doubled.update(rng.sample(sorted(members), round(len(members) * DOUBLE_LABEL_FRACTION)))
    for r in rows:
        r["double_label"] = r["id"] in doubled
    return rows
