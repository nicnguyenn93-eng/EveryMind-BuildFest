"""Build the EveryMind 988 findings site into one self-contained page.

    python frontend/build_site.py              # writes frontend/index.html
    python frontend/build_site.py --explorer   # also rebuilds frontend/explorer/explorer_standalone.html

Every number on the page comes from the analysis tables in `gemini_kit/data/`
(plus the explorer's own `md_coverage.csv` and `cube.csv`, which carry the per-county
and per-role figures the report filters on); they are read here and inlined into the
output, so the page needs no server and no network. `export_columns.json` goes in too,
so the setup screen can check an uploaded export against the columns the pipeline wants.
The interactive county map is the separate 988 Survey Explorer page, embedded in
a frame from `frontend/explorer/`.
"""
import csv, json, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
TABLES = REPO / 'gemini_kit' / 'data'
EXPLORER = HERE / 'explorer'

NUMERIC = set()  # values are kept as read; the page formats them


def read_csv(path: Path):
    """A CSV as a list of dicts, with numbers converted where they are numbers."""
    with path.open(newline='', encoding='utf-8-sig') as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for row in rows:
        clean = {}
        for key, val in row.items():
            if val is None or val == '':
                clean[key] = None
                continue
            try:
                num = float(val)
            except ValueError:
                clean[key] = val
            else:
                clean[key] = int(num) if num == int(num) and '.' not in val else num
        out.append(clean)
    return out


def table(name: str, root: Path = TABLES):
    path = root / f'{name}.csv'
    if not path.exists():
        raise SystemExit(f'missing analysis table: {path}\n'
                         'Run the gemini_kit payload build first (see gemini_kit/README.md).')
    rows = read_csv(path)
    desc = (root / f'{name}.desc')
    return {'rows': rows, 'desc': desc.read_text(encoding='utf-8').strip() if desc.exists() else ''}


DATA = {name: table(name) for name in (
    'headline', 'knowledge', 'knowledge_by_audience', 'satisfaction', 'drivers',
    'themes', 'improve_box', 'intent_gap', 'engagement', 'coverage', 'trend',
    'quality', 'language', 'robustness',
)}
DATA['md_coverage'] = table('md_coverage', EXPLORER / 'data')
# the explorer's cube carries county x role figures, which the report filters on
DATA['cube'] = table('cube', EXPLORER / 'data')

# the raw export columns the cleaning pipeline expects, for checking an uploaded file
EXPECTED = json.loads((REPO / 'export_columns.json').read_text(encoding='utf-8'))

template = (HERE / 'src' / 'index_template.html').read_text(encoding='utf-8')
fonts = (EXPLORER / 'src' / 'fonts.css').read_text(encoding='utf-8')

page = (template
        .replace('/*__FONTS__*/', fonts)
        .replace('/*__DATA__*/', json.dumps(DATA, ensure_ascii=False, separators=(',', ':')))
        .replace('/*__EXPECTED__*/', json.dumps(EXPECTED, ensure_ascii=False)))

out = HERE / 'index.html'
out.write_text(page, encoding='utf-8')
print(out, round(len(page.encode()) / 1024), 'KB')

if '--explorer' in sys.argv:
    subprocess.run([sys.executable, 'build_plain.py', 'explorer_standalone.html', '--local'],
                   cwd=EXPLORER, check=True)
