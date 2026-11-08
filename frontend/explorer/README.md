# 988 Survey Explorer — source

An interactive page for exploring EveryMind's post-training 988 survey responses:
a Maryland map you click into, and a zoomable sunburst that splits every response
by role, county and training session.

## Open it

`explorer_standalone.html` — double-click. One file, works offline, no server.
It is also what `../index.html` embeds in its "county by county" section.

`python build_plain.py explorer_page.html` writes the same page without the `<html>`
wrapper, for hosts that supply their own.

## Rebuild the page

```
python build_plain.py explorer_page.html
python build_plain.py explorer_standalone.html --local
```

Everything is written into the one output file: fonts, county outlines, d3 and the data.

## What's where

| Path | What it is |
|---|---|
| `src/part_head.html` | All the styling. Colours and font match everymind.org (Poppins, teal + green). |
| `src/part_body.html` | The page markup: header, tabs, controls, empty containers. |
| `src/part_js.js` | Every chart: the map, the drill-down bars, the sunburst, the detail panels. |
| `src/fonts.css` | Poppins, embedded, so the page needs no internet. |
| `src/md_geo.js` | Maryland's 24 county outlines as GeoJSON (13 KB). |
| `src/d3.min.js` | d3 v7.9.0, used for projections, scales and shapes. |
| `data/cube.csv` | What the page reads: one row per group at every depth. |
| `data/md_coverage.csv` | Responses and sessions per Maryland jurisdiction. |

## How the page is wired

There is no framework. `part_js.js` defines a tiny renderer: each piece of the page is a
container marked `data-draw="name"`, and a function registered under that name fills it.
The current selection lives in one object (`window.EXS`); changing it redraws every piece.

That is the whole interaction model. Clicking a county sets `mcounty`, which redraws the
map (zooming it), the detail panel, the breakdown bars and the title together.

## The rules the page follows

Group sizes are small once you drill down, so the page is deliberate about this:

- **30 or more responses** — the figure is shown normally.
- **10 to 29** — shown with an amber "small sample" marker.
- **Under 10** — the count is shown but no figure. `cube.csv` has no figure for these
  groups either, so none can be read out of the data file.
- Satisfaction bars carry a 95% interval; the other measures do not yet.

## Regenerating the data

```
python pipeline/clean_survey.py  <raw_export.xlsx> out pipeline/translations_es_en.json
python pipeline/robustness.py    out/everymind_survey_clean.csv out/robustness.csv
python pipeline/build_datasets.py out/everymind_survey_clean.csv data
python build_plain.py explorer_standalone.html --local
```

`clean_survey.py` standardizes counties and roles, recovers training dates, recodes
non-standard scale labels, flags questionable responses (nothing is deleted) and
applies the Spanish translations. `build_datasets.py` writes `cube.csv` and the other
summary tables. All three run unchanged on a new export with the same questions.

To rebuild the map outlines, see `pipeline/make_md_geo.py`.

## Known limitation

Responses cluster inside training sessions (intraclass correlation about 0.20), so the
95% intervals in `cube.csv` — which resample individuals — are roughly 2.3x too narrow.
Resampling whole sessions instead is the correct method and is not yet implemented.
