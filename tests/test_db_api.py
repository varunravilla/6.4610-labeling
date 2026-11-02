import psycopg
import pytest
from psycopg.types.json import Jsonb

from load_supabase import load_posts, set_passcode

NAMES = ["Wyatt", "Matthew", "Varun", "Kevin"]
PASS = "tariff-team"
CORE = ["steel_aluminum", "autos", "semiconductors", "agriculture", "energy", "pharmaceuticals",
        "technology", "financials", "consumer_retail", "broad_economy"]


def queue_row(rank, double=False, group=1):
    return {"id": f"p{rank}", "created_at": "2025-03-01T00:00:00.000Z", "text": f"post {rank}", "url": "",
            "era": "second_term", "tier": 1, "matched_terms": ["tariff"], "gemini_relevant": True,
            "queue_group": group, "queue_rank": rank, "double_label": double}


@pytest.fixture
def api(admin, connect):
    def setup(rows):
        load_posts(admin, rows, NAMES)
        set_passcode(admin, PASS)
        return Api(connect())
    return setup


class Api:
    def __init__(self, conn):
        self.conn = conn

    def call(self, fn, *args):
        placeholders = ", ".join(["%s"] * len(args))
        return self.conn.execute(f"select {fn}({placeholders})", args).fetchone()[0]

    def next_post(self, who, passcode=PASS):
        return self.call("next_post", who, passcode)

    def submit(self, who, post_id, relevant=True, impacts=None, extras=None, passcode=PASS):
        impacts = impacts or {k: "neutral" for k in CORE}
        return self.call("submit_label", who, passcode, post_id, relevant, Jsonb(impacts), Jsonb(extras or []))


def test_wrong_passcode_is_rejected_and_right_one_gets_first_post_in_queue_order(api):
    a = api([queue_row(2), queue_row(1)])
    with pytest.raises(psycopg.errors.RaiseException, match="bad_passcode"):
        a.next_post("Kevin", passcode="guess")
    assert a.next_post("Kevin")["id"] == "p1"


def test_single_post_is_done_after_one_label_but_double_post_goes_to_a_second_person(api):
    a = api([queue_row(1), queue_row(2, double=True), queue_row(3)])
    a.submit("Kevin", "p1")
    a.submit("Kevin", "p2")
    assert a.next_post("Kevin")["id"] == "p3"
    assert a.next_post("Wyatt")["id"] == "p2"
    a.submit("Wyatt", "p2")
    with pytest.raises(psycopg.errors.RaiseException, match="post_full"):
        a.submit("Varun", "p2")


def test_resubmitting_replaces_my_label_instead_of_adding_one(api):
    a = api([queue_row(1)])
    a.submit("Kevin", "p1", relevant=False)
    result = a.submit("Kevin", "p1", relevant=True, impacts={**{k: "neutral" for k in CORE}, "autos": "negative"})
    assert result["edited"] is True
    prev = a.call("previous_label", "Kevin", PASS, None)
    assert prev["impacts"]["autos"] == "negative"
    assert a.next_post("Wyatt") is None


def test_two_people_asking_at_once_get_different_posts_and_reload_returns_the_same_post(api):
    a = api([queue_row(1), queue_row(2)])
    assert a.next_post("Kevin")["id"] == "p1"
    assert a.next_post("Wyatt")["id"] == "p2"
    assert a.next_post("Kevin")["id"] == "p1"


def test_abandoned_claim_expires_and_frees_the_post(api, admin):
    a = api([queue_row(1), queue_row(2)])
    a.next_post("Kevin")
    admin.execute("update claims set expires_at = now() - interval '1 second'")  # ten minutes pass
    assert a.next_post("Wyatt")["id"] == "p1"


def test_skipped_post_comes_back_only_after_other_work(api):
    a = api([queue_row(1), queue_row(2)])
    a.call("skip_post", "Kevin", PASS, "p1")
    assert a.next_post("Kevin")["id"] == "p2"
    a.submit("Kevin", "p2")
    assert a.next_post("Kevin")["id"] == "p1"
    assert a.next_post("Wyatt") is None


def test_incomplete_or_inconsistent_labels_are_rejected(api):
    a = api([queue_row(1)])
    missing_one = {k: "neutral" for k in CORE[:-1]}
    for kwargs in [
        {"impacts": missing_one},
        {"impacts": {**{k: "neutral" for k in CORE}, "autos": "great"}},
        {"relevant": False, "impacts": {**{k: "neutral" for k in CORE}, "autos": "negative"}},
        {"extras": [{"industry": "other", "impact": "positive"}]},
    ]:
        with pytest.raises(psycopg.errors.RaiseException, match="invalid_label"):
            a.submit("Kevin", "p1", **kwargs)
    a.submit("Kevin", "p1", extras=[{"industry": "other", "other_name": "film", "impact": "negative"}])


def test_public_site_cannot_touch_tables_directly(api):
    a = api([queue_row(1)])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        a.conn.execute("select * from settings")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        a.conn.execute("insert into labels (post_id, annotator, relevant, impacts) values ('p1','Kevin',false,'{}')")


def test_conflicts_go_only_to_someone_who_labeled_neither_copy(api):
    a = api([queue_row(1, double=True), queue_row(2, double=True)])
    neg = {**{k: "neutral" for k in CORE}, "steel_aluminum": "positive", "autos": "negative"}
    a.submit("Kevin", "p1", impacts=neg)
    a.submit("Wyatt", "p1")
    a.submit("Kevin", "p2", extras=[{"industry": "defense", "impact": "positive"}, {"industry": "shipping", "impact": "neutral"}])
    a.submit("Wyatt", "p2", extras=[{"industry": "shipping", "impact": "neutral"}, {"industry": "defense", "impact": "positive"}])

    assert a.call("next_conflict", "Kevin", PASS) is None
    conflict = a.call("next_conflict", "Varun", PASS)
    assert conflict["post"]["id"] == "p1"  # p2 agrees: extras match regardless of order
    assert [l["annotator"] for l in conflict["labels"]] == ["Kevin", "Wyatt"]

    with pytest.raises(psycopg.errors.RaiseException, match="not_independent"):
        a.call("submit_gold", "Kevin", PASS, "p1", True, Jsonb(neg), Jsonb([]), "")
    a.call("submit_gold", "Varun", PASS, "p1", True, Jsonb(neg), Jsonb([]), "steel protected, autos pay more")
    assert a.call("next_conflict", "Matthew", PASS) is None


def test_progress_counts_done_posts_per_group_and_labels_per_person(api):
    a = api([queue_row(1), queue_row(2, double=True), queue_row(3, group=2)])
    a.submit("Kevin", "p1")
    a.submit("Kevin", "p2")
    p = a.call("progress", "Matthew", PASS)
    assert p["groups"] == [{"queue_group": 1, "total": 2, "done": 1}, {"queue_group": 2, "total": 1, "done": 0}]
    assert p["annotators"] == {"Kevin": 2, "Matthew": 0, "Varun": 0, "Wyatt": 0}


def test_reset_backs_up_labels_then_allows_a_fresh_queue(api, admin, tmp_path):
    from load_supabase import reset_labels
    a = api([queue_row(1), queue_row(2)])
    a.submit("Kevin", "p1")
    backup = reset_labels(admin, tmp_path)
    assert '"post_id": "p1"' in backup.read_text()
    load_posts(admin, [queue_row(5)], NAMES)
    assert a.next_post("Kevin")["id"] == "p5"
