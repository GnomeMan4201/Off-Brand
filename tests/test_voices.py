import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from voices import RECENT_WINDOW, assign_batch, load_roster, pick, validate  # noqa: E402


def test_roster_is_well_formed():
    roster = load_roster()
    ids = [v["id"] for v in roster["voices"]]
    assert len(ids) == len(set(ids))
    for v in roster["voices"]:
        assert v["edges"] and all(str(e) in roster["edges"] for e in v["edges"])


def test_no_repeat_within_window_over_long_run():
    history = []
    for i in range(200):
        a = pick(history, seed=f"c{i}")
        assert a["voice"] not in {v for v, _ in history[:RECENT_WINDOW]}
        if history and history[0][1] == 3:
            assert a["edge"] != 3
        history.insert(0, (a["voice"], a["edge"]))


def test_every_voice_gets_airtime():
    history = []
    for i in range(120):
        a = pick(history, seed=f"x{i}")
        history.insert(0, (a["voice"], a["edge"]))
    used = {v for v, _ in history}
    assert used == {v["id"] for v in load_roster()["voices"]}


def test_pick_is_deterministic_per_candidate():
    assert pick([], seed="same") == pick([], seed="same")


def test_batch_varies_voices():
    out = assign_batch([], ["a", "b", "c"])
    assert len({a["voice"] for a in out.values()}) == 3


def test_validate():
    assert validate("critic", "3") == ("critic", "The Critic", 3)
    assert validate("recall", "3") is None  # recall notices don't roast
    assert validate("nope", "1") is None
    assert validate(None, None) is None
