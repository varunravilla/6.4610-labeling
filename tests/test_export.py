import csv

from psycopg.types.json import Jsonb

from export import cohen_kappa, export
from test_db_api import CORE, PASS, api, queue_row  # noqa: F401  (api is a fixture)


def read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_gold_uses_single_labels_agreements_and_resolutions_and_reports_open_conflicts(api, admin, tmp_path):
    a = api([queue_row(1), queue_row(2, double=True), queue_row(3, double=True), queue_row(4, double=True)])
    steel_up = {**{k: "neutral" for k in CORE}, "steel_aluminum": "positive"}
    a.submit("Kevin", "p1", impacts=steel_up)
    a.submit("Kevin", "p2"); a.submit("Wyatt", "p2")                       # agree
    a.submit("Kevin", "p3"); a.submit("Wyatt", "p3", impacts=steel_up)     # resolved below
    a.submit("Kevin", "p4"); a.submit("Wyatt", "p4", relevant=False)       # open conflict
    a.call("submit_gold", "Varun", PASS, "p3", True, Jsonb(steel_up), Jsonb([]), "")

    export(admin, tmp_path)

    gold = read(tmp_path / "gold.csv")
    assert {r["post_id"] for r in gold} == {"p1", "p2", "p3"}
    assert len(gold) == 30  # 3 posts x 10 core industries
    p3_steel = next(r for r in gold if r["post_id"] == "p3" and r["industry"] == "steel_aluminum")
    assert (p3_steel["impact"], p3_steel["resolved"]) == ("positive", "True")

    long = read(tmp_path / "labels_long.csv")
    assert len(long) == 7 * 10
    wide = read(tmp_path / "labels_wide.csv")
    assert len(wide) == 7 and wide[0]["steel_aluminum"] in {"positive", "neutral"}
    assert "p4" in (tmp_path / "collect_report.txt").read_text()


def test_cohen_kappa_matches_worked_example():
    # Two raters, 50 items: 20 yes/yes, 5 yes/no, 10 no/yes, 15 no/no -> kappa 0.4
    a = ["y"] * 25 + ["n"] * 25
    b = ["y"] * 20 + ["n"] * 5 + ["y"] * 10 + ["n"] * 15
    assert round(cohen_kappa(a, b), 3) == 0.4
