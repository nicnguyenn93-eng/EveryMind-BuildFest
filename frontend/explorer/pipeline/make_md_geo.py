"""Build src/md_geo.js: Maryland's 24 county outlines, simplified and embedded as plain GeoJSON.

    npm pack us-atlas@3.0.1 && tar xzf us-atlas-3.0.1.tgz
    python make_md_geo.py package/counties-10m.json ../src/md_geo.js

Source: US Census TIGER boundaries, via the us-atlas package (TopoJSON).
This script decodes the TopoJSON, keeps only Maryland (FIPS 24xxx), simplifies each
outline and rounds coordinates to 3 decimals, giving roughly 13 KB instead of 840 KB.
"""
import json, sys

src, out = sys.argv[1], sys.argv[2]
d = json.load(open(src))
tr = d['transform']; sx, sy = tr['scale']; dx, dy = tr['translate']
arcs_raw = d['arcs']

def decode(i):
    a = arcs_raw[i] if i >= 0 else arcs_raw[~i]
    x = y = 0; pts = []
    for p in a:
        x += p[0]; y += p[1]
        pts.append([x * sx + dx, y * sy + dy])
    return pts if i >= 0 else pts[::-1]

def ring(idx):
    pts = []
    for i in idx:
        seg = decode(i)
        pts.extend(seg if not pts else seg[1:])
    return pts

def simplify(pts, tol):
    """Douglas-Peucker: drop points that sit close to the line between their neighbours."""
    if len(pts) < 3: return pts
    def dp(p):
        if len(p) < 3: return p
        a, b = p[0], p[-1]
        ddx, ddy = b[0] - a[0], b[1] - a[1]
        d2 = ddx * ddx + ddy * ddy
        mi, md = 0, -1
        for i in range(1, len(p) - 1):
            if d2 == 0:
                dist = (p[i][0] - a[0]) ** 2 + (p[i][1] - a[1]) ** 2
            else:
                t = max(0, min(1, ((p[i][0] - a[0]) * ddx + (p[i][1] - a[1]) * ddy) / d2))
                dist = (p[i][0] - (a[0] + t * ddx)) ** 2 + (p[i][1] - (a[1] + t * ddy)) ** 2
            if dist > md: mi, md = i, dist
        return dp(p[:mi + 1])[:-1] + dp(p[mi:]) if md > tol * tol else [a, b]
    return dp(pts)

feats = []
for g in d['objects']['counties']['geometries']:
    if not g['id'].startswith('24'):          # 24 = Maryland
        continue
    polys = [g['arcs']] if g['type'] == 'Polygon' else g['arcs']
    coords = []
    for poly in polys:
        rings = [[[round(c[0], 3), round(c[1], 3)] for c in simplify(ring(r), 0.004)] for r in poly]
        rings = [r for r in rings if len(r) >= 4]
        if rings: coords.append(rings)
    if not coords: continue
    name = 'Baltimore City' if g['id'] == '24510' else g['properties']['name']
    feats.append({'type': 'Feature', 'id': g['id'],
                  'properties': {'name': name, 'state': 'MD'},
                  'geometry': {'type': 'MultiPolygon', 'coordinates': coords}})

text = 'window.MD_GEO=' + json.dumps({'type': 'FeatureCollection', 'features': feats}, separators=(',', ':')) + ';'
open(out, 'w').write(text)
print(out, len(feats), 'jurisdictions,', round(len(text) / 1024, 1), 'KB')
