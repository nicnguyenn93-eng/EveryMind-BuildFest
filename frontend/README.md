# Frontend — 988 training findings

One page that answers "what did the trainings change, and what should change next",
with the interactive county map underneath it.

## Open it

`index.html` — double-click. No server, no network, no build step needed to view it.
The page embeds `explorer/explorer_standalone.html` in a frame; both are self-contained,
so the whole thing also works from a file:// path or any static host.

## What's on the page

The page opens on a setup screen; the report is built only after it is filled in.

| Step | What it asks for |
|---|---|
| 1 | The survey export (`.xlsx` or `.csv`). It is read **in the browser** — row count, column count, and a check against the 20 columns in `../export_columns.json`, plus a local SHA-256. Nothing is uploaded. A link beside it continues with the prepared dataset instead. |
| 2 | The audience: all respondents, students, or adults. |
| 3 | The jurisdiction. Combinations with fewer than 10 responses are disabled, so no figure can be built from a group that small. |

The `.xlsx` reader is about 40 lines on top of the browser's own `DecompressionStream`;
a workbook is a zip, and only the first row of the first sheet is needed.

Then the report itself:

| Section | What it is |
|---|---|
| At a glance | Six tiles for the chosen group: responses, sessions, knowledge, NPS, call-item coverage. |
| Key insights | Six findings, each with its own small chart. Each card carries a scope chip, because some measures exist only statewide or only for all respondents — the chip says which. |
| Key recommendations | Seven actions, each with the evidence it rests on, an owner, and the measure that would show whether it worked; the ones bearing on the current selection are marked. |
| Interactive map | The 988 Survey Explorer, embedded, opened on the same county and role as the report when the browser allows the two pages to talk (it does over http; a `file://` page may not). |
| Method and limits | What the numbers are, what they are not, and the cleaning decisions behind them. |

## Where the numbers come from

Every figure is read at build time — nothing on the page is typed in by hand.

| Source | Used for |
|---|---|
| `../gemini_kit/data/*.csv` | headline, knowledge, satisfaction, drivers, themes, intent gap, engagement, coverage, trend, quality, language, robustness |
| `explorer/data/md_coverage.csv` | which Maryland jurisdictions have responses |
| `explorer/data/cube.csv` | the county × role figures the audience and jurisdiction filters read |
| `../export_columns.json` | the columns step 1 checks an uploaded export against |
| `explorer/data/cube.csv` | everything inside the embedded explorer |

`build_site.py` reads those tables, inlines them as JSON plus the Poppins font into
`src/index_template.html`, and writes `index.html`. The prose in the template refers to
the data by lookup (`NPS('Adults').nps`, `THEME(...)`), so when the tables are
regenerated the sentences update with the charts.

## Rebuild

```bash
python frontend/build_site.py              # index.html from the current analysis tables
python frontend/build_site.py --explorer   # also rebuilds the embedded explorer page
```

To regenerate the analysis tables themselves, see `gemini_kit/README.md`; to regenerate
the explorer's `cube.csv`, see `explorer/README.md`.

## Layout

```
frontend/
  index.html              built page — the thing you open
  build_site.py           reads the analysis tables, writes index.html
  src/index_template.html markup, styling, and the insight/recommendation text
  explorer/               the 988 Survey Explorer, unchanged, with its own pipeline
```

## Privacy

Only aggregates are inlined. No group under 10 responses is given a figure, on this page
or in the explorer, and `cube.csv` carries no figure for those groups either.
