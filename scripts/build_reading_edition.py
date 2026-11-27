"""Generate a script-free public reading edition from the staged public JSON.

No network access, no private shelf data, no screenshot copying, no new verdicts.
All record text is escaped; only validated urlscan UUIDs produce evidence links.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

SCAN_ID = re.compile(r"urlscan-([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\Z")
LABELS = {
    "corroborated": "Corroborated",
    "source-confirmed": "Source-confirmed",
    "suspected": "Suspected, not confirmed",
    "unverified": "Unverified",
    "disputed": "Disputed",
}


def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def build(data):
    items = data["items"]
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise ValueError("Invalid public review archive")
    ids = set()
    sections = []
    links = []
    for number, item in enumerate(items, 1):
        scan = SCAN_ID.fullmatch(str(item.get("id", "")))
        # Numbered local anchors work even for an unrecognised source ID.
        anchor = f"review-{number}"
        label = esc(item.get("knockoff_label") or "Untitled review")
        links.append(f'<li><a href="#{anchor}">CH {number:02d} · {label}</a></li>')
        evidence = item.get("evidence")
        level = evidence.get("level") if isinstance(evidence, dict) else None
        rating = LABELS.get(level, "Not yet rated") if isinstance(level, str) else "Not yet rated"
        tells = item.get("tells")
        tells = tells if isinstance(tells, list) else []
        parts = [f'<article id="{anchor}"><h2>CH {number:02d} · {label}</h2>',
                 f'<p class="reading-label">Recorded evidence level: {rating}</p>',
                 f'<p>Scanned address: <code>{esc(item.get("defanged_url") or "Not recorded")}</code></p>',
                 f'<p>Scanned: {esc(item.get("scanned_at") or "Not recorded")} · Source: {esc(item.get("source") or "Not recorded")}</p>',
                 f'<p><strong>Satire:</strong> {esc(item.get("critic_note") or "No caption recorded")}</p>',
                 '<h3>What to notice · original published editorial notes</h3>']
        if tells:
            parts.append("<ul>" + "".join(f"<li>{esc(tell)}</li>" for tell in tells) + "</ul>")
        else:
            parts.append("<p>No editorial observations recorded.</p>")
        if scan and item["id"] not in ids:
            ids.add(item["id"])
            parts.append(f'<p><a href="https://urlscan.io/result/{scan.group(1)}/" rel="noreferrer">Read public scan record</a> · <a href="index.html#{scan.group(0)}">Interactive channel and Evidence Locker</a></p>')
        parts.append("</article>")
        sections.append("\n".join(parts))
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="referrer" content="no-referrer" />
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'none'; style-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none';" />
<title>Off-Brand · Reading edition</title>
<link rel="stylesheet" href="reading.css?v=__BUILD__" />
</head>
<body>
<main>
<nav aria-label="Station navigation"><a href="index.html">Return to the broadcast</a><a href="methodology.html">Station standards and corrections</a></nav>
<p class="reading-label">OFF-BRAND / TEXT SERVICE</p>
<h1>Reading edition</h1>
<p>The internet’s knockoff aisle. Real phishing sites reviewed by me GnomeMan4201</p>
<p>{len(items)} published reviews · Archive updated: {esc(data.get("last_updated") or "Not recorded")}</p>
<p>This script-free edition contains existing published review text, not new investigations. Recorded evidence levels reflect the archived assessment, not a current verification. Historical reviews without structured assessments remain not yet rated. Read the full Evidence Locker in the interactive edition for structured source details.</p>
<nav aria-label="Published review index"><h2>Channel index</h2><ol>{"".join(links)}</ol></nav>
{"".join(sections) if sections else "<p>No published reviews in this archive.</p>"}
<footer><a href="index.html">Return to the broadcast</a></footer>
</main>
</body>
</html>
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reviews", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(build(json.loads(args.reviews.read_text(encoding="utf-8"))), encoding="utf-8")


if __name__ == "__main__":
    main()
