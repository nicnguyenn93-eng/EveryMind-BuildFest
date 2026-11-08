"""Build the 988 Survey Explorer into one self-contained HTML page.

    python build_plain.py explorer_page.html             # the page as published (an Artifact body)
    python build_plain.py explorer_standalone.html --local   # a full document you can double-click

Everything the page needs - fonts, county outlines, the chart library and the data -
is written into the single output file, so it works offline with no server.
"""
import csv, json, sys
from pathlib import Path

H = Path(__file__).parent
out = Path(sys.argv[1])
local = '--local' in sys.argv

rows = list(csv.DictReader(open(H / 'data' / 'cube.csv', newline='', encoding='utf-8')))
DATA = {'cube': {'columns': list(rows[0].keys()), 'rows': rows}}

RENDER = """
/* The page's own tiny renderer: `dash.draw(name, fn)` registers a piece of the page,
   and `dash.draw(name)` re-runs it. Nothing here talks to a server. */
window.dash = (() => {
  const DATA = %DATA%;
  const draws = {}, listeners = [];
  const visible = (el) => !el.closest('[hidden]');
  const one = (n) => document.querySelectorAll('[data-draw="' + n + '"]').forEach((el) => {
    if (visible(el)) { try { draws[n](el); } catch (e) { console.error(n, e); } }
  });
  let queued = false;
  const all = () => { if (queued) return; queued = true; requestAnimationFrame(() => {
    queued = false; listeners.forEach((f) => f()); Object.keys(draws).forEach(one); }); };
  let w = window.innerWidth;
  window.addEventListener('resize', () => { if (window.innerWidth !== w) { w = window.innerWidth; all(); } });
  return {
    colors: [],
    data: (id) => (DATA[id] ? { status: 'ok', data: DATA[id].rows, columns: DATA[id].columns, meta: [] }
                             : { status: 'missing', data: [], columns: [], meta: [] }),
    calc() {}, loader() {}, refresh: all,
    draw(n, fn) { if (fn === undefined) { one(n); return; } draws[n] = fn; all(); },
    onData(fn) { listeners.push(fn); all(); },
    setLink(n) { try { history.replaceState(null, '', '#' + n); } catch (e) {} },
  };
})();
""".replace('%DATA%', json.dumps(DATA, ensure_ascii=False))

BASE = """
/* spacing and type scale the page relies on */
#dash-root { color-scheme: light;
  --cds-gap-xs:.25rem; --cds-gap-sm:.5rem; --cds-gap-md:.875rem; --cds-gap-lg:1.25rem; --cds-gap-xl:2rem;
  --cds-pad-xs:.3rem; --cds-pad-sm:.5rem; --cds-pad-md:.875rem; --cds-pad-lg:1.25rem; --cds-radius:10px;
  --cds-font-size-caption:.8rem; --cds-font-size-body:.95rem; --cds-font-size-heading:1.05rem;
  --cds-font-size-title:1.6rem; --cds-dur-slow:.3s; }
body { margin: 0; background: #ffffff; font-size: 15px; }
.dash-skeleton { min-height: 1em; }
.ex { padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
"""

head = (H / 'src' / 'part_head.html').read_text(encoding='utf-8')
head = head.replace('<meta name="dash-one-writer">\n', '')          # left over from an earlier host
head = head.replace('<link rel="stylesheet" href="fonts.css">\n', '')  # the font is inlined below instead
# the gutter is set once in BASE, so drop the shorthand that would override it
head = head.replace('padding: var(--cds-pad-lg) max(16px, var(--cds-pad-lg)); }', 'padding-block: var(--cds-pad-lg); }')
style_open = head.index('<style>') + len('<style>')
head = head[:style_open] + (H / 'src' / 'fonts.css').read_text(encoding='utf-8') + BASE + head[style_open:]

body = (H / 'src' / 'part_body.html').read_text(encoding='utf-8')
d3 = (H / 'src' / 'd3.min.js').read_text(encoding='utf-8')
geo = (H / 'src' / 'md_geo.js').read_text(encoding='utf-8')
code = (H / 'src' / 'part_js.js').read_text(encoding='utf-8')

page = (
    '<title>988 Survey Explorer</title>\n'
    '<meta name="claude:viewport-fit-sides" content="cover">\n'
    + head
    + f'<script>{d3}</script>\n<script>{geo}</script>\n<script>{RENDER}</script>\n'
    + '<div id="dash-root">\n' + body + '\n</div>\n'
    + f'<script>{code}</script>\n'
)
if local:
    page = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            + page.replace('<div id="dash-root">', '</head><body><div id="dash-root">')
            + '</body></html>')
out.write_text(page, encoding='utf-8')
print(out, round(len(page.encode()) / 1024), 'KB')
