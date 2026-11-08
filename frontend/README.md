# Frontend

A five-step page over the local API (`python -m everymind_web`, then http://127.0.0.1:8000). It embeds no survey figures.

| Step | What it does |
|---|---|
| 1 Upload | Choose a raw `.xlsx`/`.csv` export, or an existing censored dataset. |
| 2 Check | Rows, columns and the 20 expected headers (read in the browser); or the chosen dataset's facts. Next sends an upload to the server to be cleaned and censored. |
| 3 Findings | A pie of all responses that splits by audience, county, language or quarter (hover for n, NPS, gain); headline tiles and knowledge cards for the chosen audience and county. |
| 4 Actions | Draft a report with Gemini or the offline template; step through evidence and take actions forward. The county map and method notes sit in a collapsed section. |
| 5 Summary | One combined report (statistics, findings, chosen actions, limits) with Save as PDF (print dialog), Download .md, Copy and Email. |

## Files

| File | Role |
|---|---|
| `src/index_template.html` | Page markup, styles and step logic. |
| `src/analysis.html` | The Actions card deck (`renderDeck`, `setReport`). |
| `connected.js` | `window.Live`: calls `/api/*` (status, datasets, uploads, jobs, dashboard, reports) and the explorer sync. |
| `build_site.py` | Inlines fonts, the deck and `export_columns.json` into `index.html`. |
| `explorer/` | The county map and rings; takes `?dataset=&audience=` from the page. |

```bash
python frontend/build_site.py              # rebuild index.html
python frontend/build_site.py --explorer   # also rebuild the explorer page
```

Not shown, because the live adapter does not compute them: correlations, trends over time, NPS intervals, respondent-flow diagrams, cleaning-flag counts.

The action deck accepts Gemini recommendations and the backend's flat offline
template fields. Cited censored comments come from the report response; the
dashboard exposes aggregates only. Reports and exports label their scope as all
surveyed locations for the selected audience. Late requests cannot overwrite a
different selection. Pie angles use the full denominator, with a pooled withheld
remainder and accessible hover labels for narrow slices.

Regression checks: `node --test frontend/checks/stepper.test.cjs` (Node.js 18+).
