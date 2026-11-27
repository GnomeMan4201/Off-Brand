"""Build a clearly labelled FIXTURE shelf and an HTML approximation for phone-size preview.

    pip install pillow markdown
    python3 tests/fixtures/make_preview.py --out /tmp/preview
    python3 -m http.server -d /tmp/preview 8000   # open /README.html at ~390px width

All data is made up (example.invalid domains, drawn images). The HTML is only an
approximation of how GitHub renders the generated markdown in the private shelf repo.
"""

import argparse
import io
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import archive  # noqa: E402
import build_archive  # noqa: E402
from shelf import Shelf  # noqa: E402

BANNER = ('<div style="background:#ffe600;border:2px solid #000;padding:6px;font:700 13px sans-serif">'
          "FIXTURE DATA &mdash; made-up domains and drawn images. Not real specimens. "
          "Approximation of GitHub's markdown rendering.</div>")
CSS = ("body{font:16px -apple-system,Helvetica,sans-serif;max-width:390px;margin:0 auto;padding:8px;color:#1f2328}"
       "table{border-collapse:collapse;width:100%}td,th{border:1px solid #d0d7de;padding:6px;text-align:center;"
       "vertical-align:top;width:50%}img{max-width:100%}code{background:#eee;padding:2px 4px}")


def drawn_png(n):
    from PIL import Image, ImageDraw
    palette = [(230, 57, 38), (255, 230, 0), (11, 110, 105), (120, 120, 200), (200, 120, 120)]
    im = Image.new("RGB", (800, 1200), (245, 245, 245))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 800, 140), fill=palette[n % 5])
    d.rectangle((200, 300, 600, 360), outline=(80, 80, 80), width=4)
    d.rectangle((200, 400, 600, 460), outline=(80, 80, 80), width=4)
    d.rectangle((300, 520, 500, 580), fill=palette[(n + 2) % 5])
    d.text((20, 40), f"FIXTURE {n}", fill=(255, 255, 255))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def to_html(md_text):
    import markdown
    body = markdown.markdown(md_text, extensions=["tables"])
    body = re.sub(r'href="([^"]+?)\.md"', r'href="\1.html"', body)
    return f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><style>{CSS}</style>{BANNER}{body}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    out = ap.parse_args().out
    if out.exists():
        shutil.rmtree(out)
    shelf = Shelf(out)
    index = {"version": 1, "specimens": []}
    for n in range(1, 7):
        spec = {
            "id": f"urlscan-00000000-0000-4000-8000-{n:012d}", "scan_id": f"00000000-0000-4000-8000-{n:012d}",
            "source_record_url": f"https://urlscan.io/result/00000000-0000-4000-8000-{n:012d}/",
            "captured_at": f"2026-11-{26 - n:02d}T0{n}:15:00Z",
            "defanged_url": f"hxxps://fixture-{n}[.]example[.]invalid/login",
            "defanged_domain": f"fixture-{n}[.]example[.]invalid",
            "page_title": f"FIXTURE page title {n}" if n % 2 else None,
            "ip": "203.0.113.7" if n < 4 else None, "asn_name": None,
            "classification": {"basis": "source_label", "source": "openphish", "tags": ["phishing"],
                               "independently_confirmed": False},
        }
        archive.add_specimen(index, spec, drawn_png(n), "png", shelf, "2026-11-26T00:00:00Z")
    ids = [s["id"] for s in index["specimens"]]
    inspections = {ids[0]: [{"observation": "FIXTURE: example inspector note", "inspector": "fixture-inspector",
                             "pointer": "top-left of image"}]}
    data = build_archive.build(index, {"items": [{"id": ids[3]}]}, {ids[1]: 12}, inspections)
    files = build_archive.render_shelf(data, "example/private-shelf", "example/off-brand",
                                       archive.used_bytes(index), generated_at="FIXTURE")
    build_archive.write_shelf(out, files)
    for rel in files:
        target = out / Path(rel).with_suffix(".html")
        target.write_text(to_html(files[rel]), encoding="utf-8")
    print(f"Fixture preview built in {out}; open /README.html")


if __name__ == "__main__":
    main()
