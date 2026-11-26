"""Build the phone-readable specimen shelf (markdown) inside the PRIVATE shelf repo.

Reads the shelf catalog plus the public reviews.json (for "published" status) and
writes README.md and shelf/*.md into the shelf checkout. Nothing is written to
this public repository. Evidence bullets are factual and attributed; there is no
generated prose.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from archive import MAX_ARCHIVE_BYTES, format_mb, used_bytes
from sanitize import sanitize_text
from shelf import Shelf, assert_separate_checkout, shelf_dir

ROOT = Path(__file__).resolve().parent.parent
MAX_BULLETS = 5


def load(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def valid_inspections(items) -> list[dict]:
    """Screenshot observations count only with an observation, an inspector and a pointer."""
    out = []
    for it in items or []:
        obs = sanitize_text(it.get("observation"), max_len=160)
        who = sanitize_text(it.get("inspector"), max_len=40)
        where = sanitize_text(it.get("pointer"), max_len=80)
        if obs and who and where:
            out.append({"observation": obs, "inspector": who, "pointer": where})
    return out


def evidence_bullets(spec: dict, inspections: list[dict] | None = None) -> list[dict]:
    """3-5 short bullets when evidence supports them; unknowns are left out."""
    bullets = []
    if spec.get("page_title"):
        bullets.append({"text": f"Page title in the scan record: \u201c{spec['page_title']}\u201d",
                        "source": "scan record"})
    cls = spec.get("classification") or {}
    label = [x for x in [cls.get("source")] + list(cls.get("tags") or []) if x]
    if label:
        bullets.append({
            "text": f"Labelled by the source as: {', '.join(label)}. "
                    "This is the source's label, not independently confirmed.",
            "source": "scan record",
        })
    for ins in valid_inspections(inspections):
        bullets.append({"text": ins["observation"],
                        "source": f"screenshot, inspected by {ins['inspector']} ({ins['pointer']})"})
    host = ", ".join(x for x in [
        f"IP {spec['ip']}" if spec.get("ip") else None,
        f"ASN {spec['asn_name']}" if spec.get("asn_name") else None] if x)
    if host:
        bullets.append({"text": f"Hosting recorded in the scan: {host}", "source": "scan record"})
    if spec.get("defanged_url"):
        bullets.append({"text": f"Scanned address: {spec['defanged_url']}", "source": "scan record"})
    return bullets[:MAX_BULLETS]


PAGE_SIZE = 20
STATUS_LABEL = {"unwritten": "Unwritten", "drafted": "Drafted", "published": "Published"}
FILTERS = (("all", "All"), ("unwritten", "Unwritten"), ("drafted", "Drafted"), ("published", "Published"))
MD_SPECIAL = re.compile(r"([\\`*_\[\]()#|~!<>])")


def esc(text) -> str:
    """Scanned text is hostile: neutralise HTML and markdown so it renders as plain text."""
    return MD_SPECIAL.sub(r"\\\1", html.escape(str(text if text is not None else ""), quote=True))


def build(index: dict, reviews: dict, drafts: dict, inspections: dict) -> dict:
    published = {r["id"] for r in reviews.get("items", [])}
    specimens = []
    for s in sorted(index.get("specimens", []), key=lambda x: (x["captured_at"], x["id"]), reverse=True):
        issue = drafts.get(s["id"])
        status = "published" if s["id"] in published else ("drafted" if issue else "unwritten")
        specimens.append({
            "id": s["id"], "scan_id": s["scan_id"], "domain": s.get("defanged_domain"),
            "captured_at": s["captured_at"], "status": status,
            "image": s["image"]["path"], "thumb": (s.get("thumb") or {}).get("path"),
            "bullets": evidence_bullets(s, inspections.get(s["id"])),
            "source_record_url": s["source_record_url"], "draft_issue": issue,
            "repeat_captures": len(s.get("also_captured", [])),
        })
    return {"specimens": specimens,
            "counts": {k: sum(1 for x in specimens if x["status"] == k) for k, _ in FILTERS[1:]}}


def _nav(kind: str, page: int, pages: int, up: str) -> str:
    links = []
    if page > 1:
        links.append(f"[\u2190 Newer]({kind}-{page - 1}.md)")
    links.append(f"[Shelf home]({up})")
    if page < pages:
        links.append(f"[Older \u2192]({kind}-{page + 1}.md)")
    return " \u00b7 ".join(links)


def _cell(s: dict) -> str:
    img = (f'<img src="../{s["thumb"]}" width="150" alt="">' if s.get("thumb")
           else "<sub>no screenshot</sub>")
    return (f'<a href="specimens/{s["scan_id"]}.md">{img}</a><br>'
            f'<sub><b>{esc(s["domain"] or "unknown domain")}</b><br>'
            f'{esc(s["captured_at"][:10])} \u00b7 {STATUS_LABEL[s["status"]]}</sub>')


def render_list_pages(data: dict, kind: str, label: str, space_line: str) -> dict[str, str]:
    items = [s for s in data["specimens"] if kind == "all" or s["status"] == kind]
    pages = max(1, -(-len(items) // PAGE_SIZE))
    out = {}
    for n in range(1, pages + 1):
        chunk = items[(n - 1) * PAGE_SIZE: n * PAGE_SIZE]
        lines = [f"# {label} \u2013 page {n} of {pages}", "", space_line, "",
                 f"{len(items)} specimen(s), newest first. Tap a card for the full screenshot.", "",
                 _nav(kind, n, pages, "../README.md"), ""]
        if not chunk:
            lines.append("Nothing here yet.")
        else:
            lines += ["| | |", "|:-:|:-:|"]
            for i in range(0, len(chunk), 2):
                pair = chunk[i:i + 2]
                cells = [_cell(x) for x in pair] + [""] * (2 - len(pair))
                lines.append("| " + " | ".join(cells) + " |")
        lines += ["", _nav(kind, n, pages, "../README.md")]
        out[f"shelf/{kind}-{n}.md"] = "\n".join(lines) + "\n"
    return out


def render_detail(s: dict, shelf_repo: str, public_repo: str) -> str:
    lines = [f"# {esc(s['domain'] or 'unknown domain')}", "",
             f"Captured {esc(s['captured_at'])} \u00b7 **{STATUS_LABEL[s['status']]}**", ""]
    lines.append(f"![Saved screenshot](../../{s['image']})" if s.get("image") else "No saved screenshot.")
    lines += ["", "### Facts (each from the named source)"]
    lines += [f"- {esc(b['text'])} _({esc(b['source'])})_" for b in s["bullets"]] or \
        ["- Nothing in the record supports a bullet."]
    if s["repeat_captures"]:
        lines.append(f"- {s['repeat_captures']} later capture(s) looked identical and were folded into this one _(scan records)_")
    lines += ["", f"[Source record]({s['source_record_url']})", ""]
    if s["status"] == "published":
        lines.append("Already published to the zine.")
    elif s["draft_issue"]:
        lines.append(f"**[Open draft #{int(s['draft_issue'])}](https://github.com/{shelf_repo}/issues/{int(s['draft_issue'])})**")
    else:
        lines += [f"**[Write this one](https://github.com/{public_repo}/actions/workflows/write-specimen.yml)**"
                  " \u2192 Run workflow \u2192 paste this id:", "", f"`{s['id']}`"]
    lines += ["", "[Back](../unwritten-1.md)"]
    return "\n".join(lines) + "\n"


def render_shelf(data: dict, shelf_repo: str, public_repo: str, used: int,
                 cap: int = MAX_ARCHIVE_BYTES, generated_at: str = "") -> dict[str, str]:
    pct = 100 * used / cap if cap else 0
    space = f"Space used: **{format_mb(used)} of {format_mb(cap)}** ({pct:.0f}%)"
    files: dict[str, str] = {}
    for kind, label in FILTERS:
        files.update(render_list_pages(data, kind, label, space))
    for s in data["specimens"]:
        files[f"shelf/specimens/{s['scan_id']}.md"] = render_detail(s, shelf_repo, public_repo)
    c = data["counts"]
    files["README.md"] = "\n".join([
        "# Off-Brand shelf (private)", "",
        "Unpublished specimens. Nothing here is public.", "", space, "",
        f"- [Unwritten ({c['unwritten']})](shelf/unwritten-1.md)  \u2190 start here",
        f"- [Drafted ({c['drafted']})](shelf/drafted-1.md)",
        f"- [Published ({c['published']})](shelf/published-1.md)",
        f"- [Everything, newest first ({len(data['specimens'])})](shelf/all-1.md)", "",
        f"_Built {generated_at or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}_", ""])
    return files


def write_shelf(base: Path, files: dict[str, str]) -> None:
    """Replace the generated pages (README.md and shelf/) with `files`."""
    gen = base / "shelf"
    if gen.exists():
        shutil.rmtree(gen)
    for rel, text in files.items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--public-repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    ap.add_argument("--shelf-repo", default=os.environ.get("SHELF_REPO", ""))
    ap.add_argument("--reviews", type=Path, default=ROOT / "data" / "reviews.json")
    a = ap.parse_args()
    shelf = Shelf(shelf_dir())
    assert_separate_checkout(shelf.base)
    index = load(shelf.index, {"specimens": []})
    data = build(index, load(a.reviews, {"items": []}), load(shelf.drafts, {}), load(shelf.inspections, {}))
    write_shelf(shelf.base, render_shelf(data, a.shelf_repo, a.public_repo, used_bytes(index)))
    print(f"Built shelf: {len(data['specimens'])} specimen(s) {data['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
