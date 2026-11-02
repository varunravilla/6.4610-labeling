import json

from gemini_screen import ScreenStopped, screen


def cands(n):
    return [{"id": str(i), "created_at": "2025-03-01T00:00:00.000Z", "text": f"post {i}"} for i in range(n)]


class FakeGemini:
    """Answers every post in the prompt; can be told to fail after some calls."""

    def __init__(self, fail_after=None, answer=lambda pid: True, garble=()):
        self.calls, self.fail_after, self.answer, self.garble = 0, fail_after, answer, set(garble)

    def __call__(self, prompt, ids):
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise ScreenStopped("quota exhausted")
        if self.calls in self.garble:
            return "sorry, I can't help with that"
        return json.dumps({pid: "yes" if self.answer(pid) else "no" for pid in ids})


def test_screens_in_batches_and_records_answers(tmp_path):
    fake = FakeGemini(answer=lambda pid: int(pid) % 2 == 0)
    results = screen(cands(60), fake, tmp_path / "cache.jsonl", batch_size=25)
    assert fake.calls == 3
    assert results["0"] is True and results["1"] is False and len(results) == 60


def test_stopped_api_keeps_partial_results_and_resumes_from_cache(tmp_path):
    cache = tmp_path / "cache.jsonl"
    partial = screen(cands(60), FakeGemini(fail_after=1), cache, batch_size=25)
    assert len(partial) == 25

    resumed_fake = FakeGemini()
    full = screen(cands(60), resumed_fake, cache, batch_size=25)
    assert resumed_fake.calls == 2
    assert len(full) == 60


def test_unparseable_answer_leaves_posts_unscreened_rather_than_failing(tmp_path):
    results = screen(cands(50), FakeGemini(garble={1}), tmp_path / "cache.jsonl", batch_size=25)
    assert len(results) == 25
    assert "0" not in results and "49" in results


def test_overloaded_model_falls_back_to_the_next_one(tmp_path):
    from gemini_screen import FallbackClient
    down, up = FakeGemini(fail_after=0), FakeGemini()
    client = FallbackClient([("model-a", down), ("model-b", up)])
    results = screen(cands(60), client, tmp_path / "cache.jsonl", batch_size=25)
    assert len(results) == 60
    assert client.used == {"model-b"}


def test_all_models_down_stops_with_partial_results(tmp_path):
    from gemini_screen import FallbackClient
    client = FallbackClient([("a", FakeGemini(fail_after=1)), ("b", FakeGemini(fail_after=0))])
    assert len(screen(cands(60), client, tmp_path / "cache.jsonl", batch_size=25)) == 25
