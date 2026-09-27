# Girls Gone Canon, by the numbers

A self-updating dashboard for the [Girls Gone Canon](https://girlsgonecanon.podbean.com) podcast, built from the show's public RSS feed.

It answers the questions a chapter-by-chapter podcast eventually gets asked:

- How far into A Song of Ice and Fire is the read, by book and by POV, and when does it wrap up at the current pace?
- How many episodes, how many hours, how long do they run, and which day do they land on?
- Who has been on the show the most?
- Where is that one episode about Theon again? (Every episode, searchable and sortable.)

No build step, no framework, no accounts. Python for the data, one HTML file for the page.

## Get it running in five minutes

1. Clone (or fork) this repository.
2. Run the updater once to pull the real feed:

   ```
   python3 update.py
   ```

   It needs Python 3.10 or newer and nothing else. It writes `docs/data.js`.
3. Open `docs/index.html` in a browser. That's the dashboard.

To put it online, turn on GitHub Pages for the repository (Settings, Pages, source: the `main` branch, folder `/docs`). The included GitHub Action then refreshes the data every day and Pages redeploys on its own.

The copy committed here ships with a generated sample feed so the layout is visible before the first run. The page says so at the top; the banner goes away after `update.py` runs against the live feed.

## How it works

- `update.py` downloads the RSS feed, normalizes every title, and classifies each episode:
  - **Series**: ASOIAF read-through, House of the Dragon, A Knight of the Seven Kingdoms, His Dark Materials, Fire & Blood, Game of Thrones, Extras, or Other. Rules are the `SERIES_RULES` list near the top of the script.
  - **Chapter**: for read-through episodes it looks for a book code (AGOT, ACOK, ASOS, AFFC, ADWD), a POV name, and a Roman numeral, or one of the titled AFFC and ADWD chapters ("The Prophet", "Reek II", "The Queen's Hand"). Early episodes without a book code get one inferred from the POV's reading order.
  - **Guests**: anything after "featuring", "feat.", "ft." or "w/" in the title, plus the show notes: sentences like "Aziz of History of Westeros joins us" or "special guest Pat" yield the name and, when present, the affiliation.
  - **Show notes and links**: the notes text is kept (trimmed to 1,500 characters) for search and the expandable row in the episode table. Links that show up in most episodes (the hosts' Patreon and socials) are treated as boilerplate; the rest are episode-specific and usually point at the guest.
  - **Transcripts**: if the feed carries Podcasting 2.0 `<podcast:transcript>` tags, each episode records the transcript URL and the page links it. `python3 update.py --download-transcripts` saves the files under `data/transcripts/` (add `--transcript-limit N` to fetch a few at a time). Nothing publishes the transcript text itself; that stays a decision for the hosts.
- `data/chapters.json` is the chapter reference: how many chapters each POV has in each book (344 in total) and the mapping for titled chapters. Edit it if a count looks off or you want to treat an alias differently.
- `docs/` is the static site. `app.js` renders every chart as inline SVG and every table from `data.js`, with light and dark themes and a searchable episode list.
- `.github/workflows/update.yml` runs the updater daily at 12:00 UTC and commits `docs/data.js` when anything changed.

## Reading the numbers

- A chapter counts once, no matter how many episodes it took. Coverage caps at the chapter count in `chapters.json`.
- The finish projection uses chapter episodes from the last 12 months. It is a straight line, not a prophecy.
- The classifier only sees titles. An episode titled creatively lands in "Other" until a rule catches it. Run `python3 update.py` locally; it prints any read-through episode it could not match to a chapter.
- Runtime comes from the feed's duration field. Episodes without one are skipped in the runtime chart but still counted everywhere else.
- Guest detection reads titles and show notes with pattern matching, not magic. `update.py` prints how many guests came from the notes alone; spot-check a few after the first real run and add phrasing to `NOTES_GUEST_RES` if the show has a house style it misses.

## Run locally

```
python3 update.py                          # fetch the live feed and rebuild docs/data.js
python3 update.py --feed-file saved.xml    # or parse a feed you saved earlier
python3 update.py --download-transcripts   # also save feed-linked transcripts to data/transcripts/
python3 -m http.server 8080 -d docs        # optional; file:// works too
```

Not affiliated with the podcast, its hosts, or the publishers of anything it covers. Episode data belongs to Girls Gone Canon.
