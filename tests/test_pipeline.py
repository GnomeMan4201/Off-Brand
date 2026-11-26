import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import draft as draft_mod  # noqa: E402
import publish_from_issue as pub  # noqa: E402
from ingest import infer_tells, record_brand, select_candidates  # noqa: E402
from voices import pick  # noqa: E402

FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "candidate.json").read_text())


# ---------- intake ----------

def cand(i, brand=None, shot=True):
    return {"id": f"urlscan-{i}", "scan_uuid": f"uuid-{i}" if shot else None, "record_brand": brand}


def test_select_respects_limit_and_known_ids():
    cs = [cand(i) for i in range(20)]
    out = select_candidates(cs, {"urlscan-0", "urlscan-1"}, 5, [], has_screenshot=lambda u: True)
    assert [c["id"] for c in out] == [f"urlscan-{i}" for i in range(2, 7)]


def test_select_requires_screenshot():
    cs = [cand(1, shot=False), cand(2), cand(3, shot=False), cand(4)]
    out = select_candidates(cs, set(), 10, [], has_screenshot=lambda u: u is not None)
    assert [c["id"] for c in out] == ["urlscan-2", "urlscan-4"]


def test_brand_variety_only_when_record_names_brand():
    cs = [cand(1, "Ledger"), cand(2, "Ledger"), cand(3, "Ledger"), cand(4), cand(5), cand(6, "Allegro")]
    out = select_candidates(cs, set(), 10, [], has_screenshot=lambda u: True)
    assert [c["id"] for c in out] == ["urlscan-1", "urlscan-2", "urlscan-4", "urlscan-5", "urlscan-6"]


def test_brand_variety_uses_history():
    out = select_candidates([cand(1, "Ledger"), cand(2, "PayPal")], set(), 10, ["ledger", "ledger"],
                            has_screenshot=lambda u: True)
    assert [c["id"] for c in out] == ["urlscan-2"]


def test_record_brand_never_guessed():
    assert record_brand({"page": {"domain": "paypal-login.top"}}) is None
    assert record_brand({"brand": [{"name": "PayPal"}]}) == "PayPal"
    assert record_brand({"verdicts": {"urlscan": {"brands": [{"key": "ledger"}]}}}) == "ledger"


def test_tells_are_literal():
    tells = infer_tells("https://a.b.c.top/login", "a.b.c.top")
    assert any("4 levels deep (3 dots)" in t and "not which brand" in t for t in tells)
    assert not any("stuffed" in t.lower() for t in tells)


# ---------- drafting ----------

A = pick([], seed="test")


def test_draft_literal_fields_and_placeholders():
    body, secs = draft_mod.draft(FIXTURE, A, chat=lambda s, u: ("A cardboard box with a logo taped on.", 1.5))
    assert body.startswith(draft_mod.DRAFT_HEADER)
    review = pub.extract_review(body)
    assert review["brand"] == draft_mod.PLACEHOLDER          # record names no brand
    assert review["critic_note"] == "A cardboard box with a logo taped on."
    assert review["tells"].split(" | ") == FIXTURE["auto_tells"]
    assert review["voice"] == A["voice"]
    assert set(pub.unresolved_fields(review)) >= {"brand", "aisle", "verdict", "rating"}


def test_draft_model_failure_leaves_placeholder():
    body, _ = draft_mod.draft(FIXTURE, A, chat=lambda s, u: (None, 0.0))
    assert pub.extract_review(body)["critic_note"] == draft_mod.PLACEHOLDER


@pytest.mark.parametrize("bad", ["see https://x.top", "visit www.evil.top", "a | b", "```", ""])
def test_unsafe_model_output_rejected(bad):
    assert draft_mod.clean_note(bad) is None


def test_prompt_only_contains_record_evidence():
    prompt = draft_mod.build_user_prompt(FIXTURE, A)
    assert "Brand: not identified in the scan record" in prompt
    assert FIXTURE["defanged_url"] in prompt


# ---------- approval ----------

LABEL = "2026-11-26T12:00:00Z"
EVENTS = [{"event": "labeled", "label": {"name": "triage"}, "created_at": "2026-11-26T10:00:00Z"},
          {"event": "labeled", "label": {"name": "approved"}, "created_at": LABEL}]
GOOD = ("brand: Allegro\naisle: Marketplace & Retail\nknockoff_label: Great Value Allegro\n"
        "verdict: Dollar-Store Knockoff\nrating: 2/10\ntells: One | Two\ncritic_note: Funny and true.\n"
        "voice: critic\nedge: 2")


def comment(body, created, updated=None, assoc="OWNER", login="GnomeMan4201", cid=1):
    return {"id": cid, "body": body, "created_at": created, "updated_at": updated or created,
            "author_association": assoc, "user": {"login": login}, "html_url": f"https://x/{cid}"}


def block(fields):
    return f"{draft_mod.DRAFT_HEADER}\n\n```review\n{fields}\n```"


def test_publishes_reviewed_text_not_later_comment():
    cs = [comment(block(GOOD), "2026-11-26T11:00:00Z", cid=1),
          comment(block(GOOD.replace("Funny and true.", "LATER")), "2026-11-26T12:05:00Z", cid=2)]
    c, review = pub.select_review(cs, LABEL)
    assert c["id"] == 1 and review["critic_note"] == "Funny and true."


def test_edit_after_label_blocks():
    cs = [comment(block(GOOD), "2026-11-26T11:00:00Z", updated="2026-11-26T12:01:00Z")]
    with pytest.raises(pub.PublishError, match="edited after"):
        pub.select_review(cs, LABEL)


def test_untrusted_commenter_ignored():
    cs = [comment(block(GOOD), "2026-11-26T11:00:00Z", assoc="NONE", login="random")]
    with pytest.raises(pub.PublishError, match="trusted"):
        pub.select_review(cs, LABEL)


def test_bot_draft_counts_as_trusted():
    cs = [comment(block(GOOD), "2026-11-26T11:00:00Z", assoc="NONE", login="github-actions[bot]")]
    assert pub.select_review(cs, LABEL)[1]["brand"] == "Allegro"


def test_placeholders_block_publication():
    review = pub.extract_review(block(GOOD.replace("Allegro\n", f"{draft_mod.PLACEHOLDER}\n", 1)))
    with pytest.raises(pub.PublishError, match="brand"):
        pub.build_entry({"id": "urlscan-x", "source": "urlscan.io",
                         "public_record_url": "https://urlscan.io/result/abc/", "defanged_url": "https://a.top/"},
                        review)


def test_old_template_placeholder_blocks():
    assert "brand" in pub.unresolved_fields({**pub.parse_kv_block(GOOD), "brand": "<Target Brand>"})


def test_end_to_end_publish():
    issue = {"user": {"login": "github-actions[bot]"},
             "body": "id: urlscan-01a172c4-cf90-7236-8c9f-5e6c71047710\nsource: urlscan.io\n"
                     "public_record_url: https://urlscan.io/result/01a172c4-cf90-7236-8c9f-5e6c71047710/\n"
                     "defanged_url: hxxps://a[.]top/login\n"}
    entry, c = pub.publish(issue, [comment(block(GOOD), "2026-11-26T11:00:00Z")], EVENTS)
    assert entry["impersonated_brand"] == "Allegro" and entry["voice"] == "critic"
    assert entry["tells"] == ["One", "Two"]


def test_issue_not_from_bot_rejected():
    with pytest.raises(pub.PublishError, match="intake bot"):
        pub.publish({"user": {"login": "someone"}, "body": ""}, [], EVENTS)


def test_read_jsonl_handles_any_formatting(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_text('{"a": 1}\n{\n  "b": 2\n}\n[{"c": 3}]')
    assert pub.read_jsonl(str(p)) == [{"a": 1}, {"b": 2}, {"c": 3}]


# ---------- automatic rule check on model notes ----------

@pytest.mark.parametrize("note,why", [
    ("Random Polish-sounding words on a cheap .top.", "nationality"),
    ("Clearly aiming for your bank details.", "claim not in evidence ('bank')"),
    ("Allegro Lokalnie in a cheap .top costume.", "names a brand"),
    ("This is likely a scam on .top.", "speculation"),
    ("A free hosting deal on .top.", "claim not in evidence ('free hosting')"),
])
def test_rule_check_rejects(note, why):
    assert any(why in p for p in draft_mod.note_problems(note, FIXTURE))


def test_rule_check_allows_evidence_based_joke():
    note = "Somebody built a storefront on the cheapest lot in town: a .top ending, three labels deep."
    assert draft_mod.note_problems(note, FIXTURE) == []


def test_brand_allowed_when_record_names_it():
    c = {**FIXTURE, "record_brand": "Allegro"}
    assert draft_mod.note_problems("Allegro in a cardboard costume on a .top lot.", c) == []


def test_retry_until_a_note_passes():
    outputs = iter([("Probably a Polish scam.", 1.0), ("A cardboard costume on a .top lot.", 2.0)])
    body, secs = draft_mod.draft(FIXTURE, A, chat=lambda s, u: next(outputs))
    assert pub.extract_review(body)["critic_note"] == "A cardboard costume on a .top lot."
    assert secs == 3.0 and "rejected 1 attempt" in body


def test_all_attempts_fail_leaves_placeholder():
    body, _ = draft_mod.draft(FIXTURE, A, chat=lambda s, u: ("Likely your bank.", 1.0))
    assert pub.extract_review(body)["critic_note"] == draft_mod.PLACEHOLDER
    assert "No attempt passed" in body


def test_rule_check_catches_benchmark_failures():
    # real outputs from the qwen2.5:7b benchmark run on the PR
    assert any("victim" in p for p in draft_mod.note_problems(
        "With your star sign pointing to .top, the scammer must think you're a gullible fool.", FIXTURE))
    assert any("non-Latin" in p for p in draft_mod.note_problems(
        "With its .top domain, this site's aiming for星际探索, but landed in the bargain bin.", FIXTURE))
    assert draft_mod.note_problems("Three labels deep — a cheap .top lot.", FIXTURE) == []
