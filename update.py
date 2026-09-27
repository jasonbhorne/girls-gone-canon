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
import html
import json
import re
import sys
import urllib.request
from collections import Counter
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

FEED_URL = "https://feed.podbean.com/girlsgonecanon/feed.xml"
ROOT = Path(__file__).resolve().parent
CHAPTERS = ROOT / "data" / "chapters.json"
OUT = ROOT / "docs" / "data.js"

ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"
# Podcasting 2.0 namespace, in the spellings seen in the wild.
PODCAST_NS = (
    "{https://podcastindex.org/namespace/1.0}",
    "{http://podcastindex.org/namespace/1.0}",
    "{https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/1.0.md}",
)
TRANSCRIPTS_DIR = ROOT / "data" / "transcripts"
NOTES_MAX = 1500

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



def html_to_text(raw: str) -> str:
    """Flatten show-notes HTML to readable text, keeping line breaks."""
    if not raw:
        return ""
    t = re.sub(r"(?i)<\s*br\s*/?>", "\n", raw)
    t = re.sub(r"(?i)</\s*(p|div|li|h\d|tr)\s*>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


LINK_RE = re.compile(r"""<a\b[^>]*href\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""", re.IGNORECASE | re.DOTALL)
BARE_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")


def extract_links(raw_html: str, plain: str) -> list[dict]:
    """Every link in the notes as {url, label}. Anchor text first, then bare URLs."""
    out, seen = [], set()

    def add(url, label):
        url = html.unescape(url.strip()).rstrip(".,;")
        key = url.lower().rstrip("/")
        if not url.startswith("http") or key in seen:
            return
        seen.add(key)
        label = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", label or ""))).strip()
        if not label or label.startswith("http"):
            label = urlsplit(url).netloc.replace("www.", "")
        out.append({"url": url, "label": label[:80]})

    for m in LINK_RE.finditer(raw_html or ""):
        add(m.group(1), m.group(2))
    for m in BARE_URL_RE.finditer(plain or ""):
        add(m.group(0), "")
    return out


# Sentences in the notes that introduce a guest.
NOTES_GUEST_RES = [
    re.compile(r"(?i:special guests?|our guest|guest host)[,:]?\s+(?P<g>[A-Z][\w'@-]*(?:\s+(?:of|the|and|&|[A-Z][\w'@-]*)){0,7})", re.UNICODE),
    re.compile(r"(?i:joined by|welcome(?:s|d)?(?: back)?|sit(?:s|ting)? down with|chat(?:s|ting)? with|talk(?:s|ing)? with)\s+(?P<g>[A-Z][\w'@-]*(?:\s+(?:of|the|and|&|[A-Z][\w'@-]*)){0,7})"),
    re.compile(r"(?P<g>[A-Z][\w'@-]*(?:\s+(?:of|the|and|&|[A-Z][\w'@-]*)){0,7})\s+(?i:joins|is joining|returns to|is back on|comes back to|rejoins)\b"),
]
NOT_GUESTS = {"eliana", "chloe", "girls gone canon", "the girls", "we", "the", "this", "asoiaf", "patreon", "twitter", "george", "grrm"}


def split_person_affiliation(name: str) -> tuple[str, str | None]:
    """'Aziz of History of Westeros' -> ('Aziz', 'History of Westeros')."""
    m = re.match(r"^(.+?)\s+(?:of|from|aka)\s+(.+)$", name.strip(), re.IGNORECASE)
    if m and not m.group(1).lower().endswith(("history", "world", "tower")):
        return m.group(1).strip(), m.group(2).strip()
    return name.strip(), None


def guests_from_notes(plain: str) -> list[tuple[str, str | None]]:
    found = []
    for rx in NOTES_GUEST_RES:
        for m in rx.finditer(plain or ""):
            g = m.group("g").strip(" ,.!")
            g = re.sub(r"\s+(?:and|&|the|of)$", "", g)
            people, affil = split_person_affiliation(g)
            # "Aziz and Ashaya of History of Westeros" is two guests sharing one affiliation.
            for person in re.split(r"\s+(?:and|&)\s+", people):
                person = person.strip(" ,.!")
                if person.lower() in NOT_GUESTS or len(person) < 2 or len(person) > 40:
                    continue
                if affil and affil.lower() == person.lower():
                    affil = None
                if not any(person.lower() == f[0].lower() for f in found):
                    found.append((person, affil))
    return found


def merge_guests(title_guests: list[str], notes_guests: list[tuple[str, str | None]]) -> list[dict]:
    """Union of title and notes guests, keyed case-insensitively, keeping any affiliation."""
    out: list[dict] = []

    def put(name, affil, source):
        person, a2 = split_person_affiliation(name)
        affil = affil or a2
        if affil and affil.lower() == person.lower():
            affil = None
        for g in out:
            if g["name"].lower() == person.lower() or person.lower() in g["name"].lower() or g["name"].lower() in person.lower():
                if affil and not g.get("affiliation"):
                    g["affiliation"] = affil
                if source not in g["sources"]:
                    g["sources"].append(source)
                return
        out.append({"name": person, "affiliation": affil, "sources": [source]})

    for g in title_guests:
        put(g, None, "title")
    for person, affil in notes_guests:
        put(person, affil, "notes")
    return out


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
        raw_notes = text(it, CONTENT + "encoded") or text(it, "description") or text(it, ITUNES + "summary")
        notes = html_to_text(raw_notes)
        links = extract_links(raw_notes, notes)
        transcripts = []
        for ns in PODCAST_NS:
            for tnode in it.findall(ns + "transcript"):
                if tnode.get("url"):
                    transcripts.append({"url": tnode.get("url"), "type": tnode.get("type", ""), "language": tnode.get("language", "")})
        e = {
            "title": title,
            "date": dt.strftime("%Y-%m-%d"),
            "weekday": dt.weekday(),  # 0 = Monday
            "duration": parse_duration(text(it, ITUNES + "duration")),
            "url": text(it, "link") or (enc.get("url") if enc is not None else ""),
            "audio": enc.get("url") if enc is not None else "",
            "guests": [],
            "guest_details": merge_guests(parse_guests(title), guests_from_notes(notes)),
            "notes": notes[:NOTES_MAX] + ("…" if len(notes) > NOTES_MAX else ""),
            "links": links,
            "transcripts": transcripts,
            "explicit": text(it, ITUNES + "explicit").lower() in ("yes", "true"),
        }
        e["guests"] = [g["name"] for g in e["guest_details"]]
        e.update(classify(title, ref))
        episodes.append(e)

    # Links that appear in a large share of episodes are the hosts' own boilerplate
    # (Patreon, socials, merch). Everything else is episode-specific: usually the guest.
    link_freq = Counter(l["url"].lower().rstrip("/") for e in episodes for l in e["links"])
    boiler_cut = max(5, len(episodes) * 0.15)
    boilerplate = {u for u, n in link_freq.items() if n >= boiler_cut}
    for e in episodes:
        e["episode_links"] = [l for l in e["links"] if l["url"].lower().rstrip("/") not in boilerplate]
        del e["links"]

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

    meta["boilerplate_links"] = sorted(boilerplate)
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "feed",
        "podcast": meta,
        "books": ref.books,
        "chapter_counts": ref.counts,
        "coverage": coverage,
        "episodes": episodes,
    }


def slugify(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")[:70]


def download_transcripts(data: dict, limit: int | None = None) -> int:
    """Save feed-linked transcripts under data/transcripts/. Skips files already present."""
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    ext_for = {"text/vtt": "vtt", "application/x-subrip": "srt", "application/srt": "srt",
               "text/plain": "txt", "application/json": "json", "text/html": "html"}
    n = 0
    for e in reversed(data["episodes"]):  # newest first
        for t in e["transcripts"]:
            ext = ext_for.get(t["type"].split(";")[0].strip().lower()) or (urlsplit(t["url"]).path.rsplit(".", 1)[-1][:5] or "txt")
            path = TRANSCRIPTS_DIR / f'{e["date"]}-{slugify(e["title"])}.{ext}'
            t["file"] = str(path.relative_to(ROOT))
            if path.exists():
                continue
            if limit is not None and n >= limit:
                continue
            try:
                path.write_bytes(fetch(t["url"]))
                n += 1
                print(f"  transcript saved: {path.name}")
            except Exception as exc:  # network hiccups should not kill the run
                print(f"  transcript failed: {t['url']} ({exc})")
    return n


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
    ap.add_argument("--download-transcripts", action="store_true", help="save any transcripts the feed links to under data/transcripts/")
    ap.add_argument("--transcript-limit", type=int, default=None, help="max new transcript files to download this run")
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
    if args.download_transcripts:
        got = download_transcripts(data, args.transcript_limit)
        print(f"Downloaded {got} new transcript file(s) to {TRANSCRIPTS_DIR}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("window.GGC_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")

    eps = data["episodes"]
    n_ch = sum(len(v) for b in data["coverage"].values() for v in b.values())
    by_series: dict[str, int] = {}
    for e in eps:
        by_series[e["series"]] = by_series.get(e["series"], 0) + 1
    n_tr = sum(1 for e in eps if e["transcripts"])
    n_notes = sum(1 for e in eps if e["notes"])
    n_guest = sum(1 for e in eps if e["guests"])
    n_notes_only = sum(1 for e in eps if any("notes" in g["sources"] and "title" not in g["sources"] for g in e["guest_details"]))
    print(f"Wrote {out} : {len(eps)} episodes, {n_ch}/344 chapters covered")
    print(f"  show notes on {n_notes} episodes; guests on {n_guest} ({n_notes_only} found only in the notes); "
          f"transcript links on {n_tr}; {len(data['podcast']['boilerplate_links'])} boilerplate links filtered")
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
