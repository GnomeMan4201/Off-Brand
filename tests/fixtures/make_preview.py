"""Build a clearly labelled FIXTURE archive site for local/mobile preview.

    python3 tests/fixtures/make_preview.py --out /tmp/preview
    python3 -m http.server -d /tmp/preview 8000   # then open /archive/ on a phone-sized viewport

All data is made up (example.invalid domains, solid-colour images). Nothing is real.
"""

import argparse
import shutil
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import archive  # noqa: E402
import build_archive  # noqa: E402


def png(w, h, rgb):
    row = b"\x00" + bytes(rgb) * w
    raw = zlib.compress(row * h)
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) \
        + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    out = ap.parse_args().out
    if out.exists():
        shutil.rmtree(out)
    root = out / "_root"
    index = {"version": 1, "fixture": True, "specimens": []}
    colours = [(230, 57, 38), (255, 230, 0), (11, 110, 105), (120, 120, 200), (200, 120, 120), (90, 90, 90)]
    for n in range(1, 7):
        spec = {
            "id": f"urlscan-00000000-0000-4000-8000-{n:012d}", "scan_id": f"00000000-0000-4000-8000-{n:012d}",
            "source_record_url": f"https://urlscan.io/result/00000000-0000-4000-8000-{n:012d}/report/",
            "captured_at": f"2026-11-{26 - n:02d}T0{n}:15:00Z",
            "defanged_url": f"hxxps://fixture-{n}[.]example[.]invalid/login",
            "defanged_domain": f"fixture-{n}[.]example[.]invalid",
            "page_title": f"FIXTURE page title {n}" if n % 2 else None,
            "ip": "203.0.113.7" if n < 4 else None, "asn_name": None,
            "classification": {"basis": "source_label", "source": "openphish", "tags": ["phishing"],
                               "independently_confirmed": False},
        }
        archive.add_specimen(index, spec, png(120, 160, colours[n - 1]), "png",
                             root / "archive" / "shots", "2026-11-26T00:00:00Z")
    index["specimens"].pop(4)  # keep five; sixth card shows the missing-image state below
    index["specimens"][4]["image"]["path"] = "archive/shots/" + "0" * 64 + ".png"  # file absent
    ids = [s["id"] for s in index["specimens"]]
    shutil.copytree(ROOT / "site" / "archive", out / "archive", dirs_exist_ok=True)
    inspections = {ids[0]: [{"observation": "FIXTURE: example inspector note", "inspector": "fixture-inspector",
                             "pointer": "top-left of image"}]}
    build_archive.build(index, {"items": [{"id": ids[3]}]}, {ids[1]: 12}, inspections,
                        "example/fixture-repo", out / "archive", root=root)
    html = out / "archive" / "index.html"
    html.write_text(html.read_text().replace("__BUILD__", "fixture"))
    print(f"Fixture preview built in {out}; open /archive/")


if __name__ == "__main__":
    main()
