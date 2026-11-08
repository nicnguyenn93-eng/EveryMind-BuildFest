# Frontend — current censored data and Gemini

Netra's layout and controls are preserved. Run the connected page from the repository:

```bash
python -m pip install -r requirements-web.txt
python -m everymind_web
```

Open **http://127.0.0.1:8000**. Choose an existing verified censored dataset or upload
a raw `.xlsx`/`.csv`; Generate the report runs cleaning → censoring locally for
new uploads. All tiles, findings, map/rings and report evidence use that selected
censored export. Opening the page without the API displays startup instructions;
older prepared aggregates are not substituted.

County and audience controls remain inside the report. Gemini has an explicit
aggregate-only button and always uses the selected audience across all surveyed
locations, irrespective of county. No key or respondent/comment rows reach the
frontend. Known non-students is a role classification rather than a measured age.

See [HTTP contract, scope and metric definitions](../docs/local_web_api.md).

## Build and layout

```bash
python frontend/build_site.py --explorer
```

- `src/index_template.html`: Netra's layout/styles and prepared-table renderer, with small live-adapter hooks.
- `connected.js`: upload/selection, current aggregate rendering, explicit report calls and scope/state handling.
- `index.html`: generated page.
- `explorer/src/`: Netra's map and ring renderer, with current-data loading through a dataset handle.
- `explorer/explorer_standalone.html`: generated explorer; current page links include the same dataset and audience.

Historical `gemini_kit/data/` and explorer tables stay available for comparison.
They are still embedded by the existing builder but never drive a connected run.
The bare standalone explorer without a dataset query is a historical prepared view.
No historical findings, correlations or recommendations are carried into a current
run. Current outputs may withhold more fine groups than the prepared tables; the
map/rings explain missing figures.
