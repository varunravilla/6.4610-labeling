import json

from gemini_screen import ScreenStopped
from llm_label import CORE, label_posts

NEUTRAL = {k: "neutral" for k in CORE}


def posts(n):
    return [{"id": str(i), "created_at": "2025-04-02T18:00:00.000Z", "text": f"post {i}"} for i in range(n)]


class FakeGemini:
    def __init__(self, answer=None, fail_after=None):
        self.calls, self.fail_after = 0, fail_after
        self.answer = answer or (lambda pid: {"relevant": True, "impacts": {**NEUTRAL, "steel_aluminum": "positive"}, "extras": []})

    def __call__(self, prompt, ids):
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise ScreenStopped("quota")
        return json.dumps([{"id": pid, **self.answer(pid)} for pid in ids])


def test_labels_every_post_with_the_full_form(tmp_path):
    fake = FakeGemini()
    labels = label_posts(posts(30), fake, tmp_path / "cache.jsonl", batch_size=25)
    assert fake.calls == 2 and len(labels) == 30
    assert labels["7"]["impacts"]["steel_aluminum"] == "positive"
    assert set(labels["7"]["impacts"]) == set(CORE)


def test_invalid_answers_are_left_unlabeled_rather_than_stored(tmp_path):
    def answer(pid):
        bad = {
            "0": {"relevant": True, "impacts": {k: "neutral" for k in CORE[:-1]}, "extras": []},           # missing industry
            "1": {"relevant": True, "impacts": {**NEUTRAL, "autos": "great"}, "extras": []},               # bad value
            "2": {"relevant": False, "impacts": {**NEUTRAL, "autos": "negative"}, "extras": []},           # irrelevant but non-neutral
            "3": {"relevant": True, "impacts": NEUTRAL, "extras": [{"industry": "other", "impact": "positive"}]},  # other without name
        }
        return bad.get(pid, {"relevant": False, "impacts": NEUTRAL, "extras": []})

    labels = label_posts(posts(6), FakeGemini(answer), tmp_path / "cache.jsonl", batch_size=25)
    assert sorted(labels) == ["4", "5"]


def test_stopped_api_resumes_from_cache(tmp_path):
    cache = tmp_path / "cache.jsonl"
    assert len(label_posts(posts(60), FakeGemini(fail_after=1), cache, batch_size=25)) == 25
    resumed = FakeGemini()
    assert len(label_posts(posts(60), resumed, cache, batch_size=25)) == 60
    assert resumed.calls == 2
