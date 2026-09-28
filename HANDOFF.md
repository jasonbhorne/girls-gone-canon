# Handoff: Girls Gone Canon dashboard

Written 2026-09-28 from the cloud session. Everything below is committed on branch `claude/girls-gone-canon-dashboard-uc6t2j` in `jasonbhorne/abs-tracker`, under the `girls-gone-canon/` folder. Delete this file once the work moves to its own repo.

## Pick up the session or just the code

Option A, continue the Claude Code conversation with full context (needs a clean local clone of abs-tracker and the same claude.ai login):

```
cd abs-tracker
claude --teleport session_01PaGVPDVDUNnVhbqBgS7nnA
```

Option B, just the code:

```
git clone -b claude/girls-gone-canon-dashboard-uc6t2j https://github.com/jasonbhorne/abs-tracker.git
cd abs-tracker/girls-gone-canon
```

## What this is

A gift dashboard for the Girls Gone Canon podcast (Eliana and Chloe, ASOIAF and adjacent shows). Static site plus one Python script, no dependencies beyond Python 3.10.

- `update.py` pulls the RSS feed, classifies each episode by series, matches read-through episodes to one of 344 ASOIAF chapters, parses guests from titles and show notes, filters host boilerplate links, and records Podcasting 2.0 transcript tags. Writes `docs/data.js`.
- `data/chapters.json` is the chapter reference (POV counts per book, titled AFFC and ADWD chapters).
- `docs/` is the page: read-through progress by book and POV with a finish projection, episodes per year, runtime per quarter, release day, guests, longest episodes, and a searchable episode table with expandable show notes. Light and dark themes. Works from file://.
- `.github/workflows/update.yml` refreshes the data daily and commits it.
- `README.md` is written for the recipients.

## What is still sample data

The cloud container's network policy blocks feed.podbean.com, so the committed `docs/data.js` came from a generated stand-in feed (370 fake episodes shaped like the real titles). The page shows a "Sample data" banner until the real feed is parsed. The parser was tested against real title formats pulled from search results, but never against the full feed.

## First run on the Mac

```
python3 update.py --download-transcripts
open docs/index.html
```

Read the summary the script prints. Three things matter:

1. `transcript links on N`. If N is above zero the feed carries transcripts and they were saved to `data/transcripts/` (gitignored). That makes the mentions index a free next step. If zero, transcripts would have to be generated; see Next steps.
2. `ASOIAF episodes without a chapter match`. Any real title the parser could not read. Paste these into the session and the rules get fixed. Likely culprits: titles with a book name spelled out, chapters split into parts with odd wording, or crossover episodes.
3. The guests table on the page. Check a handful against the show notes. Missed phrasings go in `NOTES_GUEST_RES` in `update.py`; a bad boilerplate filter shows up as a host link listed as a guest link.

Then commit the real `docs/data.js` so the branch stops carrying sample data:

```
git add docs/data.js
git commit -m "Real feed data"
git push
```

## Move it to its own repo

Create an empty public repo `jasonbhorne/girls-gone-canon` on GitHub (the cloud session's integration was not allowed to). Then, from the abs-tracker checkout:

```
git checkout claude/girls-gone-canon-dashboard-uc6t2j
git subtree split --prefix=girls-gone-canon -b ggc-standalone
git push git@github.com:jasonbhorne/girls-gone-canon.git ggc-standalone:main
git branch -D ggc-standalone
```

Then in the new repo: Settings, Pages, source Deploy from a branch, `main`, folder `/docs`. The Action's first run can be triggered from the Actions tab. The README footer already links to `github.com/jasonbhorne/girls-gone-canon`.

After that, this folder can be removed from abs-tracker and the branch closed.

## Next steps, in order

1. Real feed run and parser fixes (above).
2. Standalone repo and Pages (above).
3. Decide on transcripts if the feed has none. Roughly 700 hours of audio for the backfill. Cloud speech-to-text is on the order of a few hundred dollars one-time; local whisper.cpp on Apple Silicon is free but takes days. Only then build the mentions index (character and house mentions per episode, full-text search). Keep raw transcripts out of the public site either way; that call belongs to the hosts.
4. Optional polish once real data is in: cover art from the feed will replace the hidden placeholder automatically; check the finish projection reads sensibly against their actual pace.

## Session notes

- Palette and chart specs follow the dataviz method; series colors were validated for colorblind separation in both themes. Series-to-color mapping is fixed in `GROUPS` in `docs/app.js`, do not reorder.
- Chapter counts: AGOT 73, ACOK 70, ASOS 82, AFFC 46, ADWD 73. Prologues and epilogues count as their own POV.
- The podcast reads POV by POV, not in book order. Book inference for early titles without a code relies on that.
- Guest detection is pattern matching on titles and notes. Expect a few misses on the first real run.
