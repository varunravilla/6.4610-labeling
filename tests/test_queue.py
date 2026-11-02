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
    row = (result.candidates or result.excluded)[0]
    return row.get("matched_terms", [])


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


def test_partner_plus_money_counts_as_tier_three_and_stays_out_of_the_queue():
    result = find_candidates(
        [post("1", "Japan just agreed to hand the United States of America 550 Billion, the most ever!")], [], LEXICON
    )
    assert result.candidates == []
    assert (result.excluded[0]["matched_terms"], result.excluded[0]["reason"]) == (["partner+money"], "tier3_only")


def test_post_with_no_keyword_is_excluded_not_lost():
    result = find_candidates([post("1", "Congratulations to the great people of Ohio on a wonderful election night!")], [], LEXICON)
    assert result.candidates == []
    assert [(r["id"], r["reason"]) for r in result.excluded] == [("1", "no_keyword")]


def cand(id, tier=1, era="second_term", n_terms=1, created_at="2025-03-01T00:00:00.000Z"):
    return {"id": id, "tier": tier, "era": era, "matched_terms": [f"t{i}" for i in range(n_terms)],
            "created_at": created_at, "text": "", "url": ""}


def test_queue_is_newest_first_with_era_groups():
    rows = order_queue([
        cand("2023", era="earlier", created_at="2023-05-01T00:00:00.000Z"),
        cand("2026", tier=2, created_at="2026-10-01T00:00:00.000Z"),
        cand("2025", created_at="2025-02-01T00:00:00.000Z"),
    ])
    assert ids(rows) == ["2026", "2025", "2023"]
    assert [r["queue_group"] for r in rows] == [1, 1, 2]
    assert [r["queue_rank"] for r in rows] == [1, 2, 3]


def test_double_label_sample_is_twenty_percent_per_stratum_and_reproducible():
    cands = [cand(f"new-t1-{i}") for i in range(50)] + [cand(f"old-t2-{i}", tier=2, era="earlier") for i in range(30)]
    first = order_queue(cands)
    second = order_queue(list(reversed(cands)))

    doubled = {r["id"] for r in first if r["double_label"]}
    assert sum(i.startswith("new-t1") for i in doubled) == 10
    assert sum(i.startswith("old-t2") for i in doubled) == 6
    assert doubled == {r["id"] for r in second if r["double_label"]}


def test_endorsements_and_weak_tier_three_posts_stay_out_of_the_queue():
    result = find_candidates(
        [
            post("endorse", "Congressman Smith has my Complete and Total Endorsement! He will Grow our Economy, Cut Taxes "
                            "and Regulations, and Secure our Border."),
            post("weak", "Great crowd of workers and their cars at the rally in Michigan tonight. Thank you all!"),
            post("econ", "Inflation is way down and the Stock Market just hit another all time high. Thank you!"),
        ],
        [],
        LEXICON,
    )
    assert ids(result.candidates) == ["econ"]
    assert {r["id"]: r["reason"] for r in result.excluded} == {"endorse": "endorsement", "weak": "tier3_only"}


def test_garbled_csv_text_is_repaired():
    garbled = "the healthcare of foreign countries\u00e2\u0080\u0094and we will put a Tariff on drugs from abroad"
    result = find_candidates([], [csv_row("1", garbled)], LEXICON)
    assert "countries\u2014and" in result.candidates[0]["text"]


def test_tier_three_can_be_kept_for_screening():
    result = find_candidates(
        [post("weak", "Great crowd of workers and their cars at the rally in Michigan tonight. Thank you all!")],
        [], LEXICON, tiers={1, 2, 3},
    )
    assert ids(result.candidates) == ["weak"]


def test_gemini_no_leaves_the_queue_but_an_unscreened_post_stays():
    rows = order_queue(
        [cand("yes", created_at="2026-01-01T00:00:00.000Z"), cand("no"), cand("unscreened", created_at="2024-01-01T00:00:00.000Z", era="earlier")],
        screen={"yes": True, "no": False},
    )
    assert ids(rows) == ["yes", "unscreened"]
    assert [r["gemini_relevant"] for r in rows] == [True, None]
    assert [r["queue_rank"] for r in rows] == [1, 2]
