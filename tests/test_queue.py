from pathlib import Path

from queue_builder import find_candidates, load_lexicon, order_queue

LEXICON = load_lexicon(Path(__file__).parent.parent / "lexicon.txt")


def post(id, text, created_at="2025-03-01T15:00:00.000Z"):
    return {"id": id, "created_at": created_at, "content": text, "url": f"https://truthsocial.com/x/{id}"}


def ids(rows):
    return [r["id"] for r in rows]


def test_trade_post_is_tier_one_and_repost_is_dropped():
    result = find_candidates(
        [
            post("1", "We are putting a 25% Tariff on all steel coming into our Country. Big win!"),
            post("2", "RT @someone We are putting a 25% Tariff on all steel coming into our Country."),
        ],
        [],
        LEXICON,
    )
    assert ids(result.candidates) == ["1"]
    assert result.candidates[0]["tier"] == 1
    assert "tariff" in result.candidates[0]["matched_terms"]


def matched(text):
    result = find_candidates([post("1", text + " " + "x" * 40)], [], LEXICON)
    return result.candidates[0]["matched_terms"] if result.candidates else []


def test_terms_match_on_token_boundaries_not_inside_words():
    assert matched("A portion of everything is important to every investigation") == []
    assert "port" in matched("The port of Baltimore")
    assert "ev" in matched("Biden's EV mandate is dead")


def test_stems_match_inflections():
    assert "manufactur" in matched("Manufacturing is coming back")
    assert "tariff" in matched("Tariffs are working")
    assert "reciproc" in matched("Reciprocal deals")
    assert "trade deal" in matched("Great Trade Deals with Japan")


TARIFF = "China will pay a big Tariff on everything they send us, starting Monday!"


def csv_row(id, text, date="2025-04-02 18:00:00+00:00", platform="Truth Social", repost="False", deleted="False"):
    return {"id": id, "date": date, "platform": platform, "text": text,
            "repost_flag": repost, "deleted_flag": deleted, "post_url": f"https://truthsocial.com/x/{id}"}


def test_junk_posts_are_dropped_before_matching():
    result = find_candidates(
        [
            post("empty", ""),
            post("link", "Tariffs! https://www.example.com/a-very-long-article-path-about-trade"),
            post("dup-late", "  china WILL pay a big tariff on everything they send us, starting Monday! ",
                 created_at="2025-03-02T00:00:00.000Z"),
            post("dup-early", TARIFF, created_at="2025-03-01T00:00:00.000Z"),
            post("too-new", TARIFF + " again", created_at="2026-11-01T00:00:00.000Z"),
            post("flagged", TARIFF + " today"),
        ],
        [csv_row("flagged", TARIFF + " today", deleted="True")],
        LEXICON,
    )
    assert ids(result.candidates) == ["dup-early"]


def test_csv_adds_truth_social_posts_missing_from_json_but_not_twitter_or_reposts():
    result = find_candidates(
        [],
        [
            csv_row("ts", TARIFF),
            csv_row("tw", TARIFF + " now", platform="Twitter"),
            csv_row("rt", TARIFF + " again", repost="True"),
        ],
        LEXICON,
    )
    assert ids(result.candidates) == ["ts"]
    assert result.candidates[0]["created_at"] == "2025-04-02T18:00:00.000Z"


def test_partner_plus_money_enters_at_tier_three():
    result = find_candidates(
        [post("1", "Japan just agreed to hand the United States of America 550 Billion, the most ever!")], [], LEXICON
    )
    assert result.candidates[0]["tier"] == 3
    assert result.candidates[0]["matched_terms"] == ["partner+money"]


def test_post_with_no_keyword_is_excluded_not_lost():
    result = find_candidates([post("1", "Congratulations to the great people of Ohio on a wonderful election night!")], [], LEXICON)
    assert result.candidates == []
    assert ids(result.excluded) == ["1"]


def cand(id, tier=1, era="second_term", n_terms=1, created_at="2025-03-01T00:00:00.000Z"):
    return {"id": id, "tier": tier, "era": era, "matched_terms": [f"t{i}" for i in range(n_terms)],
            "created_at": created_at, "text": "", "url": ""}


def test_queue_order_is_second_term_relevant_then_earlier_relevant_then_not_relevant():
    rows = order_queue(
        [cand("old-yes", era="earlier"), cand("new-no"), cand("new-yes-t2", tier=2), cand("new-yes-t1")],
        {"old-yes": True, "new-no": False, "new-yes-t2": True, "new-yes-t1": True},
    )
    assert ids(rows) == ["new-yes-t1", "new-yes-t2", "old-yes", "new-no"]
    assert [r["queue_group"] for r in rows] == [1, 1, 2, 3]
    assert [r["queue_rank"] for r in rows] == [1, 2, 3, 4]


def test_missing_gemini_answer_counts_as_relevant_so_queue_works_without_the_api():
    rows = order_queue([cand("a", era="earlier"), cand("b")], {})
    assert ids(rows) == ["b", "a"]
    assert [r["gemini_relevant"] for r in rows] == [None, None]
    assert [r["queue_group"] for r in rows] == [1, 2]


def test_double_label_sample_is_twenty_percent_per_stratum_and_reproducible():
    cands = [cand(f"g1t1-{i}") for i in range(50)] + [cand(f"g3t2-{i}", tier=2) for i in range(30)]
    screen = {c["id"]: not c["id"].startswith("g3") for c in cands}
    first = order_queue(cands, screen)
    second = order_queue(list(reversed(cands)), screen)

    doubled = {r["id"] for r in first if r["double_label"]}
    assert sum(i.startswith("g1t1") for i in doubled) == 10
    assert sum(i.startswith("g3t2") for i in doubled) == 6
    assert doubled == {r["id"] for r in second if r["double_label"]}
