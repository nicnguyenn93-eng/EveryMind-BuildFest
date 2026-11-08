"""Build the EveryMind 988 frontend into one page.

    python frontend/build_site.py              # writes frontend/index.html
    python frontend/build_site.py --explorer   # also rebuilds frontend/explorer/explorer_standalone.html

The page embeds no survey figures. It talks to the local server (`python -m everymind_web`),
which serves live, censored data; see docs/local_web_api.md. Only the fonts, the report-card
deck (src/analysis.html) and the list of export columns it checks an upload against are inlined.
"""
import json, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
EXPLORER = HERE / 'explorer'

EXPECTED = json.loads((REPO / 'export_columns.json').read_text(encoding='utf-8'))
template = (HERE / 'src' / 'index_template.html').read_text(encoding='utf-8')
fonts = (EXPLORER / 'src' / 'fonts.css').read_text(encoding='utf-8')

page = (template
        .replace('/*__FONTS__*/', fonts)
        .replace('<!--__ANALYSIS__-->', (HERE / 'src' / 'analysis.html').read_text(encoding='utf-8'))
        .replace('/*__EXPECTED__*/', json.dumps(EXPECTED, ensure_ascii=False)))

out = HERE / 'index.html'
out.write_text(page, encoding='utf-8')
print(out, round(len(page.encode()) / 1024), 'KB')

if '--explorer' in sys.argv:
    subprocess.run([sys.executable, 'build_plain.py', 'explorer_standalone.html', '--local'],
                   cwd=EXPLORER, check=True)
