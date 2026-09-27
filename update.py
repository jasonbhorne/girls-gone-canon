#!/usr/bin/env python3
"""Girls Gone Canon dashboard updater.

Reads the podcast RSS feed, classifies every episode, matches ASOIAF chapter
episodes against the chapter reference in data/chapters.json, and writes
docs/data.js (a JS file so index.html works from file:// as well as a server).

Standard library only. Run:

    python3 update.py                    # fetch the live feed
    python3 update.py --feed-file x.xml  # parse a saved feed instead
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

FEED_URL = "https://feed.podbean.com/girlsgonecanon/feed.xml"
ROOT = Path(__file__).resolve().parent
CHAPTERS = ROOT / "data" / "chapters.json"
OUT = ROOT / "docs" / "data.js"

ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"

# Series buckets. Order matters: the first matching rule wins.
SERIES_RULES = [
    ("A Knight of the Seven Kingdoms", r"knight of the seven kingdoms|akotsk|\bdunk\b|hedge knight|sworn sword|mystery knight"),
    ("House of the Dragon", r"house of the dragon|\bhotd\b"),
    ("His Dark Materials", r"his dark materials|\bhdm\b|book of dust|la belle sauvage|secret commonwealth|golden compass|northern lights|subtle knife|amber spyglass"),
    ("Fire & Blood", r"fire\s*(&|and)\s*blood|\bf&b\b|the world of ice|dunk and egg|rogue prince|princess and the queen"),
    ("Game of Thrones", r"game of thrones|\bgot\b\s*s\d|\bgot\b.*episode|\bgot\b.*season"),
    ("Extras", r"q\s*&\s*a|q&a|mailbag|bonus|announcement|trailer|anniversary|live show|livestream|patreon|introduc|welcome|holiday|year in review|listener"),
]

ROMAN = r"(?:X{0,2}(?:IX|IV|V?I{0,3}))"
ROMAN_VAL = {"I": 1, "V": 5, "X": 10}


def roman_to_int(s: str) -> int:
    total, prev = 0, 0
    for ch in reversed(s.upper()):
        v = ROMAN_VAL[ch]
        total = total - v if v < prev else total + v
        prev = max(prev, v)
    return total


def norm_title(t: str) -> str:
    t = t.replace("—", " - ").replace("–", " - ").replace("’", "'")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def parse_duration(s: str | None) -> int | None:
    if not s:
        return None
    s = s.strip()
    if s.isdigit():
        return int(s)
    parts = s.split(":")
    try:
        parts = [int(float(p)) for p in parts]
    except ValueError:
        return None
    secs = 0
    for p in parts:
        secs = secs * 60 + p
    return secs


class ChapterRef:
    def __init__(self, path: Path):
        d = json.loads(path.read_text())
        self.books = d["books"]
        self.book_keys = [b["key"] for b in self.books]
        self.counts = d["counts"]
        self.named = {k.lower(): v for k, v in d["named"].items()}
        self.aliases = d["pov_aliases"]
        self.povs = sorted({p for c in self.counts.values() for p in c})
        names = list(self.aliases) + self.povs
        names.sort(key=len, reverse=True)
        self.pov_re = re.compile(
            r"\b(" + "|".join(re.escape(n) for n in names) + r")\b\s*(" + ROMAN + r")\b(?![a-z])",
            re.IGNORECASE,
        )
        self.book_re = re.compile(
            r"\b(" + "|".join(re.escape(a) for b in self.books for a in b["aliases"]) + r")\b",
            re.IGNORECASE,
        )
        self.alias_to_key = {a.lower(): b["key"] for b in self.books for a in b["aliases"]}

    def canon_pov(self, name: str) -> str:
        for k, v in self.aliases.items():
            if k.lower() == name.lower():
                return v
        for p in self.povs:
            if p.lower() == name.lower():
                return p
        return name

    def find_book(self, title: str) -> str | None:
        m = self.book_re.search(title)
        return self.alias_to_key[m.group(1).lower()] if m else None

    def find_named(self, title: str):
        low = title.lower()
        for name, (book, pov, ordinal) in self.named.items():
            if re.search(r"\b" + re.escape(name) + r"\b", low):
                return book, pov, ordinal
        return None

    def find_pov(self, title: str):
        """Return (pov, ordinal) for the first 'Name I' style token, else None."""
        for m in self.pov_re.finditer(title):
            name, numeral = m.group(1), m.group(2)
            if not numeral:
                # Prologue / Epilogue have no numeral.
                if self.canon_pov(name) in ("Prologue", "Epilogue"):
                    return self.canon_pov(name), 1
                continue
            return self.canon_pov(name), roman_to_int(numeral)
        return None

    def books_for(self, pov: str) -> list[str]:
        return [b for b in self.book_keys if pov in self.counts[b]]


GUEST_RE = re.compile(
    r"(?:\bfeaturing\b|\bfeat\.?\b|\bft\.?\b|\bwith special guests?\b|\bw/\b)\s*:?\s*(.+?)\s*(?:$|\s-\s|\|)",
    re.IGNORECASE,
)


def parse_guests(title: str) -> list[str]:
    m = GUEST_RE.search(title)
    if not m:
        return []
    raw = m.group(1)
    raw = re.sub(r"\s*\([^)]*\)", "", raw)  # drop "(of Some Channel)"
    raw = raw.strip(" ()")                    # a guest inside "(Ft. ...)" leaves a stray paren
    raw = raw.split("/")[0]
    parts = re.split(r"\s*(?:,|&|\band\b)\s*", raw)
    out = []
    for p in parts:
        p = p.strip(" .!-")
        if p and len(p) < 60:
            out.append(p)
    return out


def classify(title: str, ref: ChapterRef) -> dict:
    """Return series/book/pov/chapter info for a normalized title."""
    info = {"series": "Other", "book": None, "pov": None, "ordinal": None, "episode_num": None}
    m = re.search(r"\bASOIAF\s*(?:Episode|Ep\.?)\s*(\d+)", title, re.IGNORECASE)
    if m:
        info["episode_num"] = int(m.group(1))

    named = ref.find_named(title)
    book = ref.find_book(title)
    # "Theon ACOK VI" puts the book between the name and the numeral; drop it first.
    pov = ref.find_pov(ref.book_re.sub(" ", title) if book else title)
    show_like = re.search(r"\bS\d+\s*E\d+\b|\bSeason\s+\d+|\bEpisode\s+\d+\s*[-:\"]", title, re.IGNORECASE)

    for name, pat in SERIES_RULES:
        if re.search(pat, title, re.IGNORECASE):
            # A chapter episode with a book code always belongs to the read-through,
            # even if a guest's show name matches a rule above.
            if m or (book and (pov or named)):
                break
            info["series"] = name
            return info

    if named:
        info.update(series="ASOIAF", book=named[0], pov=named[1], ordinal=named[2])
        return info
    if pov and (book or m or not show_like):
        info.update(series="ASOIAF", book=book, pov=pov[0], ordinal=pov[1])
        return info
    if m:
        info["series"] = "ASOIAF"
    return info


def infer_books(episodes: list[dict], ref: ChapterRef) -> None:
    """Fill in a missing book for chapter episodes by walking each POV in air order.

    The podcast reads POV by POV, so for a given POV the numerals climb within a
    book and reset to I when the next book starts.
    """
    by_pov: dict[str, list[dict]] = {}
    for e in episodes:
        if e["series"] == "ASOIAF" and e["pov"] and e["ordinal"]:
            by_pov.setdefault(e["pov"], []).append(e)
    for pov, eps in by_pov.items():
        eps.sort(key=lambda e: (e["date"], e.get("episode_num") or 0))
        last_book, last_ord = None, None
        for e in eps:
            if e["book"]:
                last_book, last_ord = e["book"], e["ordinal"]
                continue
            cands = ref.books_for(pov)
            chosen = None
            if last_book and last_book in cands:
                if e["ordinal"] == last_ord + 1 and e["ordinal"] <= ref.counts[last_book].get(pov, 0):
                    chosen = last_book
                elif e["ordinal"] == 1:
                    nxt = [b for b in cands if ref.book_keys.index(b) > ref.book_keys.index(last_book)]
                    chosen = nxt[0] if nxt else None
            if not chosen:
                fits = [b for b in cands if e["ordinal"] <= ref.counts[b].get(pov, 0)]
                chosen = fits[0] if fits else (cands[0] if cands else None)
            e["book"] = chosen
            e["book_inferred"] = True
            last_book, last_ord = chosen, e["ordinal"]


def parse_feed(xml_bytes: bytes, ref: ChapterRef) -> dict:
    root = ET.fromstring(xml_bytes)
    ch = root.find("channel")
    if ch is None:
        raise SystemExit("Not an RSS feed: no <channel>")

    def text(el, tag, default=""):
        n = el.find(tag)
        return (n.text or "").strip() if n is not None and n.text else default

    img = ch.find(ITUNES + "image")
    image = img.get("href") if img is not None else text(ch, "image/url")
    meta = {
        "title": text(ch, "title"),
        "description": re.sub(r"<[^>]+>", "", text(ch, "description"))[:600],
        "author": text(ch, ITUNES + "author"),
        "link": text(ch, "link"),
        "image": image,
        "feed": FEED_URL,
    }

    episodes = []
    for it in ch.findall("item"):
        raw_title = text(it, "title")
        title = norm_title(raw_title)
        pub = text(it, "pubDate")
        try:
            dt = parsedate_to_datetime(pub).astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        enc = it.find("enclosure")
        e = {
            "title": title,
            "date": dt.strftime("%Y-%m-%d"),
            "weekday": dt.weekday(),  # 0 = Monday
            "duration": parse_duration(text(it, ITUNES + "duration")),
            "url": text(it, "link") or (enc.get("url") if enc is not None else ""),
            "guests": parse_guests(title),
            "explicit": text(it, ITUNES + "explicit").lower() in ("yes", "true"),
        }
        e.update(classify(title, ref))
        episodes.append(e)

    episodes.sort(key=lambda e: e["date"])
    infer_books(episodes, ref)

    # Chapter coverage: one entry per distinct (book, pov, ordinal).
    covered: dict[str, dict[str, set]] = {b: {} for b in ref.book_keys}
    for e in episodes:
        if e["series"] == "ASOIAF" and e["book"] and e["pov"] and e["ordinal"]:
            total = ref.counts.get(e["book"], {}).get(e["pov"])
            if total and e["ordinal"] <= total:
                covered[e["book"]].setdefault(e["pov"], set()).add(e["ordinal"])
                e["chapter_key"] = f'{e["book"]} {e["pov"]} {e["ordinal"]}'
    coverage = {
        b: {pov: sorted(s) for pov, s in povs.items()} for b, povs in covered.items()
    }

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "feed",
        "podcast": meta,
        "books": ref.books,
        "chapter_counts": ref.counts,
        "coverage": coverage,
        "episodes": episodes,
    }


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "girls-gone-canon-dashboard/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--feed-file", help="parse a saved RSS file instead of fetching")
    ap.add_argument("--feed-url", default=FEED_URL)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--source-label", default=None, help="override the data source label (e.g. 'sample')")
    args = ap.parse_args()

    ref = ChapterRef(CHAPTERS)
    if args.feed_file:
        xml_bytes = Path(args.feed_file).read_bytes()
    else:
        print(f"Fetching {args.feed_url}")
        xml_bytes = fetch(args.feed_url)

    data = parse_feed(xml_bytes, ref)
    if args.source_label:
        data["source"] = args.source_label

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("window.GGC_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")

    eps = data["episodes"]
    n_ch = sum(len(v) for b in data["coverage"].values() for v in b.values())
    by_series: dict[str, int] = {}
    for e in eps:
        by_series[e["series"]] = by_series.get(e["series"], 0) + 1
    print(f"Wrote {out} : {len(eps)} episodes, {n_ch}/344 chapters covered")
    for k, v in sorted(by_series.items(), key=lambda kv: -kv[1]):
        print(f"  {k:32s} {v}")
    unmatched = [e["title"] for e in eps if e["series"] == "ASOIAF" and not e.get("chapter_key")]
    if unmatched:
        print(f"  ASOIAF episodes without a chapter match: {len(unmatched)}")
        for t in unmatched[:15]:
            print("   -", t)
    return 0


if __name__ == "__main__":
    sys.exit(main())
