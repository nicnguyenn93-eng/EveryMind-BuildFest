if (new URLSearchParams(location.search).has('dataset')) document.getElementById('dash-root').style.visibility = 'hidden';
/* ---------- shared helpers ---------- */
window.EX = (() => {
  const ALL = '(all)';
  const num = (v) => (v === '' || v === null || v === undefined || v === 'NaN' ? null : Number(v));
  const FMT = {
    int: (v) => v == null ? '—' : d3.format(',')(v), pct0: (v) => v == null ? '—' : Math.round(v) + '%', d1: d3.format('.1f'), d2: d3.format('.2f'),
    s2: d3.format('+.2f'), nps: (v) => (v > 0 ? '+' : v < 0 ? '−' : '') + d3.format('.0f')(Math.abs(v)),
  };
  const METRICS = {
    nps: { label: 'Satisfaction (NPS)', short: 'NPS', fmt: FMT.nps, domain: [-40, 100], diverging: true,
           note: '% rating the training 9–10 for "would recommend", minus % rating it 0–6' },
    gain_index: { label: 'Knowledge gained', short: 'Knowledge gained', fmt: FMT.s2, domain: [0, 2],
           note: 'Average change from before to after, across the three knowledge questions (1–5 scale)' },
    pct_know_when: { label: 'Know when to use 988', short: 'Know when', fmt: FMT.pct0, domain: [70, 100],
           note: '% who agree after the training that they know when to use 988' },
    call_mean: { label: 'Would call 988', short: 'Would call', fmt: FMT.d2, domain: [5, 10],
           note: 'Average answer to "How likely are you to call 988?" (0–10)' },
    engaged_mean: { label: 'Presenter engagement', short: 'Engagement', fmt: FMT.d2, domain: [3.5, 5],
           note: 'Average answer to "The presenter engaged the participants" (1–5)' },
  };
  const ROLES = ['Student', 'School staff', 'Caregiver/parent', 'Community member', 'Multiple roles', 'Unspecified role'];
  const rows = () => { const d = dash.data('cube'); return d.status === 'ok' ? d.data : null; };
  const look = (rs, county, role, dim, val) =>
    rs.find((r) => r.county === county && r.role === role && r.split_dim === dim && r.split_val === val);
  const css = (el, n) => getComputedStyle(el).getPropertyValue(n).trim();
  const colorFor = (el, m, v) => {
    const cfg = METRICS[m], [lo, hi] = cfg.domain;
    const teal = css(el, '--em-teal'), amber = css(el, '--em-amber'), pale = css(el, '--em-teal-soft');
    if (cfg.diverging) {
      return v < 0 ? d3.interpolateRgb(amber, pale)(Math.min(1, (v - lo) / (0 - lo)))
                   : d3.interpolateRgb(pale, teal)(Math.min(1, v / hi));
    }
    return d3.interpolateRgb(pale, teal)(Math.max(0, Math.min(1, (v - lo) / (hi - lo))));
  };
  const svg = (el, w, h) => d3.select(el).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${w} ${h}`).attr('height', h);
  const tip = (box) => {
    let t = box.querySelector('.ex-tip');
    if (!t) { t = document.createElement('div'); t.className = 'ex-tip'; t.hidden = true; box.appendChild(t); }
    return {
      show(ev, title, lines) {
        t.replaceChildren();
        const h = document.createElement('div'); h.className = 't'; h.textContent = title; t.appendChild(h);
        lines.filter(Boolean).forEach((l) => { const d = document.createElement('div'); d.textContent = l; t.appendChild(d); });
        t.hidden = false;
        const b = box.getBoundingClientRect();
        let x = ev.clientX - b.left + 14, y = ev.clientY - b.top + 14;
        if (x + t.offsetWidth > b.width) x = Math.max(0, ev.clientX - b.left - t.offsetWidth - 14);
        if (y + t.offsetHeight > b.height) y = Math.max(0, y - t.offsetHeight - 28);
        t.style.left = x + 'px'; t.style.top = y + 'px';
      },
      hide() { t.hidden = true; },
    };
  };
  const S = window.EXS = window.EXS || { tab: 'map', metric: 'nps', order: 'role', split: 'role',
                                          mcounty: ALL, mrole: ALL, focus: [], pick: [] };
  const state = () => S;
  // every drawing on the page; a view change redraws them all, which is cheap at this size
  const DRAWS = ['maptitle', 'mapnote', 'maplegend', 'map', 'countychips', 'mapdetail',
                 'splittitle', 'splitnote', 'mapsplit',
                 'ringlegend', 'ringcrumbs', 'rings', 'ringdetail'];
  const set = (patch) => { Object.assign(S, patch);
    if (window.EXLIVE && window.EXREADY && 'mcounty' in patch && parent !== window)
      parent.postMessage({type: 'everymind-county', county: S.mcounty, dataset_key: window.EXLIVE, audience: window.EXAUDIENCE}, location.origin); window.EXSYNC && window.EXSYNC(); DRAWS.forEach((n) => dash.draw(n)); };
  const legend = (el, metric) => {
    const cfg = METRICS[metric];
    el.replaceChildren();
    const wrap = document.createElement('span');
    const name = document.createElement('span'); name.textContent = cfg.short + ' ';
    const lo = document.createElement('span'); lo.textContent = cfg.fmt(cfg.domain[0]) + ' ';
    const bar = document.createElement('span'); bar.className = 'ex-scale-bar';
    bar.style.background = `linear-gradient(90deg, ${d3.range(0, 1.001, 0.1).map((t) =>
      colorFor(el, metric, cfg.domain[0] + t * (cfg.domain[1] - cfg.domain[0]))).join(',')})`;
    const hi = document.createElement('span'); hi.textContent = ' ' + cfg.fmt(cfg.domain[1]);
    wrap.append(name, lo, bar, hi);
    const nd = document.createElement('span');
    const sw = document.createElement('i'); sw.style.background = 'var(--em-grid)'; sw.style.border = '1px solid var(--em-line)';
    nd.append(sw, 'no figure');
    el.append(wrap, nd);
  };
  return { ALL, num, FMT, METRICS, ROLES, rows, look, css, colorFor, svg, tip, state, set, legend };
})();

/* ---------- tabs and segmented controls ---------- */
(() => {
  const show = (name) => {
    document.querySelectorAll('.ex-page').forEach((p) => { p.hidden = p.dataset.page !== name; });
    document.querySelectorAll('.ex-tab').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.tab === name)));
  };
  window.EXSYNC = () => {
    const s = EX.state();
    document.querySelectorAll('.ex-seg button').forEach((b) =>
      b.setAttribute('aria-pressed', String(s[b.dataset.param] === b.dataset.value)));
    show(s.tab);
  };
  document.querySelectorAll('.ex-tab').forEach((b) => b.addEventListener('click', () => {
    EX.set({ tab: b.dataset.tab }); dash.setLink(b.dataset.tab);
  }));
  const linked = location.hash.slice(1);
  if (['map', 'rings'].includes(linked)) EX.state().tab = linked;
  document.querySelectorAll('.ex-seg button').forEach((b) => b.addEventListener('click', () => {
    const o = { [b.dataset.param]: b.dataset.value };
    if (b.dataset.param === 'order') { o.focus = []; o.pick = []; }
    EX.set(o);
  }));
  dash.onData(() => window.EXSYNC());
})();

/* ---------- a detail panel, shared by both views ---------- */
function exDetail(el, opts) {
  const { title, row, metric, subtitle, chips } = opts;
  const cfg = EX.METRICS[metric];
  el.replaceChildren();
  const h = document.createElement('div'); h.className = 'ex-title'; h.textContent = title; el.appendChild(h);
  if (subtitle) { const s = document.createElement('p'); s.className = 'cap muted'; s.textContent = subtitle; el.appendChild(s); }
  if (!row) {
    const p = document.createElement('p'); p.className = 'cap muted'; p.textContent = window.EXLIVE ? 'No publishable figures for this group. Protected or unavailable values are unknown.' : 'No survey responses for this group.';
    el.appendChild(p); return;
  }
  const n = EX.num(row.n), v = EX.num(row[metric]);
  const hero = document.createElement('div'); hero.className = 'ex-hero';
  const lab = document.createElement('span'); lab.className = 'lab cap'; lab.textContent = cfg.label;
  const big = document.createElement('span'); big.className = 'big' + (v !== null && metric === 'nps' && v < 0 ? ' warn' : '');
  big.textContent = v === null ? '—' : cfg.fmt(v);
  const sub = document.createElement('span'); sub.className = 'cap muted';
  sub.textContent = v === null
    ? (n == null ? 'withheld or unavailable; not zero' : (n < 10 ? 'fewer than 10 responses, so no figure is shown' : 'not enough answers to this question'))
    : (metric === 'nps' && EX.num(row.ci_low) !== null
        ? `95% range ${EX.FMT.nps(EX.num(row.ci_low))} to ${EX.FMT.nps(EX.num(row.ci_high))}` : cfg.note);
  hero.append(lab, big, sub); el.appendChild(hero);

  const tbl = document.createElement('div'); tbl.className = 'ex-rows';
  const line = (k, val, cls) => {
    const r = document.createElement('div'); r.className = 'ex-row' + (cls ? ' ' + cls : '');
    const a = document.createElement('span'); a.textContent = k;
    const b = document.createElement('span'); b.className = 'v' + (val === '—' ? ' none' : ''); b.textContent = val;
    r.append(a, b); tbl.appendChild(r);
  };
  line('Responses', EX.FMT.int(n));
  line('Training sessions', EX.FMT.int(EX.num(row.sessions)));
  line('Share who were students', EX.FMT.pct0(EX.num(row.student_pct)));
  const headRow = document.createElement('div'); headRow.className = 'ex-row head';
  const hl = document.createElement('span'); hl.textContent = 'Every measure';
  const hr = document.createElement('span'); hr.textContent = '';
  headRow.append(hl, hr); tbl.appendChild(headRow);
  Object.entries(EX.METRICS).forEach(([k, m]) => {
    const mv = EX.num(row[k]);
    line(m.label, mv === null ? '—' : m.fmt(mv));
  });
  line(window.EXLIVE ? 'Recorded likelihood-to-call scores' : 'Asked "would you call 988?"', EX.FMT.int(EX.num(row.n_call)) + ' of ' + EX.FMT.int(n));
  el.appendChild(tbl);

  if (row.reliability === 'small sample') {
    const w = document.createElement('p'); w.className = 'ex-warn';
    w.textContent = `Small sample: ${n} responses. Read these as a hint, not a result.`;
    el.appendChild(w);
  } else if (row.reliability === 'too few') {
    const w = document.createElement('p'); w.className = 'ex-warn';
    w.textContent = `Only ${n} response${n === 1 ? '' : 's'}: too few for any figure.`;
    el.appendChild(w);
  }
  if (chips && chips.length) {
    const lab2 = document.createElement('p'); lab2.className = 'cap muted'; lab2.textContent = chips[0].groupLabel;
    el.appendChild(lab2);
    const box = document.createElement('div'); box.className = 'ex-chips';
    chips.forEach((c) => {
      const b = document.createElement('button'); b.className = 'ex-chip'; b.textContent = c.label;
      b.setAttribute('aria-pressed', String(!!c.active));
      if (c.disabled) b.disabled = true; else b.onclick = c.onClick;
      box.appendChild(b);
    });
    el.appendChild(box);
  }
}

/* ---------- MAP ---------- */
dash.draw('maplegend', (el) => EX.legend(el, EX.state().metric));

dash.draw('maptitle', (el) => {
  const s = EX.state();
  el.textContent = s.mcounty === EX.ALL ? 'Where the training has reached' : s.mcounty + ' County';
});
dash.draw('mapnote', (el) => {
  const s = EX.state();
  el.textContent = s.mcounty === EX.ALL
    ? (window.EXLIVE ? 'Current censored dataset. Click a county to inspect it. Grey means no publishable figure; totals include other surveyed locations. Fine splits omit protected groups.' : 'Four of Maryland\u2019s twenty-four counties have survey responses. Click one to zoom in; the grey ones have not been surveyed.')
    : 'Click ' + s.mcounty + ' again, or use the chips below, to come back out to the whole state.';
});

dash.draw('countychips', (el) => {
  const rs = EX.rows(); if (!rs) { el.replaceChildren(); return; }
  const s = EX.state();
  el.replaceChildren();
  const add = (label, active, onClick) => {
    const b = document.createElement('button'); b.className = 'ex-chip'; b.textContent = label;
    b.setAttribute('aria-pressed', String(active)); b.onclick = onClick; el.appendChild(b);
  };
  add(window.EXLIVE ? '\u2196 All surveyed locations' : '\u2196 All of Maryland', s.mcounty === EX.ALL, () => EX.set({ mcounty: EX.ALL, mrole: EX.ALL }));
  // only counties the map can actually show, so every chip zooms somewhere
  const onMap = new Set((window.MD_GEO ? window.MD_GEO.features : []).map((f) => f.properties.name));
  const off = [];
  rs.filter((r) => r.role === EX.ALL && r.split_dim === 'none' && r.county !== EX.ALL && (!window.EXLIVE || EX.num(r.n) > 0))
    .sort((a, b) => EX.num(b.n) - EX.num(a.n))
    .forEach((r) => {
      if (!onMap.has(r.county)) { off.push(`${r.county} ${EX.FMT.int(EX.num(r.n))}`); return; }
      add(`${r.county} (${EX.FMT.int(EX.num(r.n))})`, s.mcounty === r.county,
        () => EX.set({ mcounty: r.county === s.mcounty ? EX.ALL : r.county, mrole: EX.ALL }));
    });
  if (off.length) {
    const n = document.createElement('span'); n.className = 'cap muted';
    n.textContent = 'Outside Maryland, not on the map: ' + off.join(', ') + '.';
    el.appendChild(n);
  }
});

// remembered so a redraw can animate from where the map was to where it is going
window.EXZOOM = window.EXZOOM || { prev: null };

dash.draw('map', (el) => {
  const rs = EX.rows(); if (!rs) { el.classList.add('dash-skeleton'); return; }
  el.classList.remove('dash-skeleton'); el.replaceChildren();
  if (!window.MD_GEO) {
    const p = document.createElement('p'); p.className = 'cap muted';
    p.textContent = 'The county outlines did not load, so the map cannot be drawn.';
    el.appendChild(p); return;
  }
  const s = EX.state(), cfg = EX.METRICS[s.metric];
  const W = Math.max(300, el.clientWidth), H = Math.max(320, Math.round(W * 0.64));
  const svg = EX.svg(el, W, H), tt = EX.tip(el);
  const proj = d3.geoMercator().fitExtent([[10, 10], [W - 10, H - 10]], window.MD_GEO);
  const path = d3.geoPath(proj);
  const grid = EX.css(el, '--em-grid');
  const rowFor = (name) => EX.look(rs, name, s.mrole, 'none', 'none');
  const hasAny = (name) => { const row = EX.look(rs, name, EX.ALL, 'none', 'none'); return !!row && (!window.EXLIVE || EX.num(row.n) > 0); };

  // where the map should sit: the whole state, or filling the frame with one county
  let target = null, scale = 1;
  if (s.mcounty !== EX.ALL) {
    const f = window.MD_GEO.features.find((x) => x.properties.name === s.mcounty);
    if (f) {
      const b = path.bounds(f), bw = Math.max(1, b[1][0] - b[0][0]), bh = Math.max(1, b[1][1] - b[0][1]);
      scale = Math.min((W * 0.72) / bw, (H * 0.72) / bh, 9);
      const tx = W / 2 - scale * (b[0][0] + bw / 2), ty = H / 2 - scale * (b[0][1] + bh / 2);
      target = `translate(${tx},${ty}) scale(${scale})`;
    }
  }
  const zoom = svg.append('g').attr('class', 'ex-zoom')
    .attr('transform', window.EXZOOM.prev || null);

  zoom.append('g').selectAll('path').data(window.MD_GEO.features).join('path')
    .attr('class', (f) => 'ex-county' + (hasAny(f.properties.name) ? ' live' : '') +
                          (f.properties.name === s.mcounty ? ' sel' : ''))
    .attr('d', path)
    .attr('fill', (f) => { const r = rowFor(f.properties.name); const v = r ? EX.num(r[s.metric]) : null;
                           return v === null ? grid : EX.colorFor(el, s.metric, v); })
    .on('mousemove', (ev, f) => {
      const r = rowFor(f.properties.name), lines = [];
      if (!r) lines.push(window.EXLIVE ? 'No publishable breakdown for this group' : 'No survey responses');
      else {
        const n = EX.num(r.n), v = EX.num(r[s.metric]);
        lines.push(`${EX.FMT.int(n)} response${n === 1 ? '' : 's'}${r.reliability === 'small sample' ? ' (small sample)' : ''}`);
        lines.push(v === null ? (n == null ? 'Withheld or unavailable; not zero' : (n < 10 ? 'Too few to show a figure' : 'No figure for this measure')) : `${cfg.short}: ${cfg.fmt(v)}`);
        lines.push(f.properties.name === s.mcounty ? 'Click to zoom back out' : 'Click to zoom in');
      }
      tt.show(ev, f.properties.name + (f.properties.name.endsWith('City') ? '' : ' County'), lines);
    })
    .on('mouseleave', () => tt.hide())
    .on('click', (ev, f) => {
      if (!hasAny(f.properties.name)) return;
      EX.set({ mcounty: f.properties.name === s.mcounty ? EX.ALL : f.properties.name, mrole: EX.ALL });
    });

  // labels ride inside the zoomed group, counter-scaled so they stay the same size on screen
  const fs = (W < 480 ? 10 : 12) / scale;
  const shown = window.MD_GEO.features.filter((f) =>
    hasAny(f.properties.name) && (s.mcounty === EX.ALL || f.properties.name === s.mcounty));
  const labs = shown.map((f) => {
    const c = path.centroid(f), t = (W < 480 && s.mcounty === EX.ALL) ? f.properties.name.split(' ')[0] : f.properties.name;
    return { x: c[0], y: c[1] + fs / 3, t, w: t.length * fs * 0.55, sel: f.properties.name === s.mcounty };
  }).sort((a, b) => a.y - b.y);
  labs.forEach((l, i) => {
    for (let k = 0; k < i; k++) {
      const o = labs[k];
      while (Math.abs(l.y - o.y) < fs + 3 / scale && Math.abs(l.x - o.x) < (l.w + o.w) / 2 + 4 / scale) l.y = o.y + fs + 3 / scale;
    }
  });
  zoom.append('g').selectAll('text').data(labs).join('text').attr('class', 'strong')
    .attr('x', (d) => d.x).attr('y', (d) => d.y).attr('text-anchor', 'middle')
    .attr('pointer-events', 'none').style('font-size', fs + 'px').attr('font-weight', (d) => (d.sel ? 700 : 600))
    .attr('stroke', EX.css(el, '--em-bg')).attr('stroke-width', 3.5 / scale).attr('stroke-linejoin', 'round')
    .attr('paint-order', 'stroke fill').text((d) => d.t);

  // apply the new position on the next frame so the CSS transition has something to animate from
  const node = zoom.node();
  requestAnimationFrame(() => { if (node.isConnected) node.setAttribute('transform', target || ''); });
  window.EXZOOM.prev = target;
});

dash.draw('mapdetail', (el) => {
  const rs = EX.rows(); if (!rs) { el.classList.add('dash-skeleton'); return; }
  el.classList.remove('dash-skeleton');
  const s = EX.state();
  const row = EX.look(rs, s.mcounty, s.mrole, 'none', 'none');
  const where = s.mcounty === EX.ALL ? (window.EXLIVE ? 'All surveyed locations' : 'All of Maryland') : s.mcounty + ' County';
  const who = s.mrole === EX.ALL ? '' : (s.mrole === 'Student' ? 'students' : s.mrole.toLowerCase());
  const chips = [{ groupLabel: s.mcounty === EX.ALL ? 'Narrow to a role' : 'Narrow to a role within ' + s.mcounty,
                   label: 'Everyone', active: s.mrole === EX.ALL, onClick: () => EX.set({ mrole: EX.ALL }) }];
  EX.ROLES.forEach((role) => {
    const r = EX.look(rs, s.mcounty, role, 'none', 'none');
    chips.push({ groupLabel: '', label: (role === 'Student' ? 'Students' : role) + (r ? ` (${EX.FMT.int(EX.num(r.n))})` : (window.EXLIVE ? ' (unavailable)' : ' (0)')),
                 active: s.mrole === role, disabled: !r,
                 onClick: () => EX.set({ mrole: role === s.mrole ? EX.ALL : role }) });
  });
  exDetail(el, { title: who ? `${where} · ${who}` : where, row, metric: s.metric, chips,
                 subtitle: s.mcounty === EX.ALL ? 'Click a county on the map to narrow this panel.' : 'Click the county again on the map to clear it.' });
});

/* ---------- RINGS (zoomable sunburst) ---------- */
window.EXRING = (() => {
  const nodeOf = (rs, county, role, dim, val, name) => {
    const row = EX.look(rs, county, role, dim, val);
    return row ? { key: name, name, row, county, role, dim, val } : null;
  };
  const build = (rs, order) => {
    const ALL = EX.ALL;
    const counties = [...new Set(rs.filter((r) => r.split_dim === 'none' && r.role === ALL && r.county !== ALL && (!window.EXLIVE || EX.num(r.n) > 0)).map((r) => r.county))]
      .sort((a, b) => EX.num(EX.look(rs, b, ALL, 'none', 'none').n) - EX.num(EX.look(rs, a, ALL, 'none', 'none').n));
    const roles = EX.ROLES.filter((r) => EX.look(rs, ALL, r, 'none', 'none'));
    const outer = order === 'role' ? roles : counties;
    const inner = order === 'role' ? counties : roles;
    const root = { key: 'root', name: 'All responses', row: EX.look(rs, ALL, ALL, 'none', 'none'), children: [] };
    outer.forEach((o) => {
      const l1 = order === 'role' ? nodeOf(rs, ALL, o, 'none', 'none', o) : nodeOf(rs, o, ALL, 'none', 'none', o);
      if (!l1) return;
      l1.children = [];
      inner.forEach((i) => {
        const county = order === 'role' ? i : o, role = order === 'role' ? o : i;
        const l2 = nodeOf(rs, county, role, 'none', 'none', i);
        if (!l2) return;
        l2.children = rs.filter((r) => r.county === county && r.role === role && r.split_dim === 'session')
          .sort((a, b) => a.split_val.localeCompare(b.split_val))
          .map((r) => ({ key: r.split_val, name: r.split_val.split(' | ')[0], row: r, county, role, dim: 'session', val: r.split_val }));
        l1.children.push(l2);
      });
      root.children.push(l1);
    });
    return root;
  };
  const find = (root, path) => {
    let n = root;
    for (const k of path) { const c = (n.children || []).find((x) => x.key === k); if (!c) return n; n = c; }
    return n;
  };
  return { build, find };
})();

dash.draw('ringlegend', (el) => EX.legend(el, EX.state().metric));

dash.draw('ringcrumbs', (el) => {
  const rs = EX.rows(); if (!rs) return;
  const s = EX.state();
  const tree = EXRING.build(rs, s.order);
  el.replaceChildren();
  const steps = [{ label: 'All responses', path: [] }];
  let cur = tree;
  s.focus.forEach((k) => {
    const c = (cur.children || []).find((x) => x.key === k);
    if (c) { cur = c; steps.push({ label: c.name, path: steps[steps.length - 1].path.concat(k) }); }
  });
  steps.forEach((st, i) => {
    if (i) { const sep = document.createElement('span'); sep.className = 'ex-crumb-sep'; sep.textContent = '›'; el.appendChild(sep); }
    const b = document.createElement('button');
    b.className = 'ex-crumb' + (i === steps.length - 1 ? ' current' : '');
    b.textContent = st.label;
    b.onclick = () => EX.set({ focus: st.path.slice(), pick: st.path.slice() });
    el.appendChild(b);
  });
});

dash.draw('rings', (el) => {
  const rs = EX.rows(); if (!rs) { el.classList.add('dash-skeleton'); return; }
  el.classList.remove('dash-skeleton'); el.replaceChildren();
  const s = EX.state(), cfg = EX.METRICS[s.metric];
  const W = Math.max(300, el.clientWidth), H = Math.max(320, Math.min(560, W));
  const R = Math.min(W, H) / 2 - 4;
  const svg = EX.svg(el, W, H), tt = EX.tip(el);
  const defs = svg.append('defs');
  const pat = defs.append('pattern').attr('id', 'ex-few').attr('width', 6).attr('height', 6)
    .attr('patternUnits', 'userSpaceOnUse').attr('patternTransform', 'rotate(45)');
  pat.append('rect').attr('width', 6).attr('height', 6).attr('fill', EX.css(el, '--em-grid'));
  pat.append('line').attr('x1', 0).attr('y1', 0).attr('x2', 0).attr('y2', 6)
    .attr('stroke', EX.css(el, '--em-line')).attr('stroke-width', 2.5);

  const tree = EXRING.build(rs, s.order);
  const root = d3.hierarchy(tree)
    .eachAfter((d) => { d.value = d.children && d.children.length ? d3.sum(d.children, (c) => c.value) : EX.num(d.data.row.n) || 0; });
  d3.partition().size([2 * Math.PI, root.height + 1])(root);
  let focus = root;
  s.focus.forEach((k) => { const c = (focus.children || []).find((x) => x.data.key === k); if (c) focus = c; });
  const span = (focus.x1 - focus.x0) || 1;
  // show at most two rings below whatever you are inside, and thicken them to fill the circle
  const ringsShown = Math.max(1, Math.min(2, focus.height));
  const step = R / (1 + ringsShown);
  const rel = (d) => ({
    x0: Math.max(0, Math.min(1, (d.x0 - focus.x0) / span)) * 2 * Math.PI,
    x1: Math.max(0, Math.min(1, (d.x1 - focus.x0) / span)) * 2 * Math.PI,
    y0: Math.max(0, d.y0 - focus.depth), y1: Math.max(0, d.y1 - focus.depth),
  });
  const arc = d3.arc().startAngle((d) => d.x0).endAngle((d) => d.x1)
    .padAngle((d) => Math.min((d.x1 - d.x0) / 2, 0.004)).padRadius(R)
    .innerRadius((d) => d.y0 * step).outerRadius((d) => Math.max(d.y0 * step, d.y1 * step - 1.5));
  const g = svg.append('g').attr('transform', `translate(${W / 2},${H / 2})`);
  const items = root.descendants().slice(1)
    .map((d) => ({ d, p: rel(d) }))
    .filter(({ p }) => p.y0 >= 1 && p.y1 <= 1 + ringsShown && p.x1 - p.x0 > 0.0015);
  const picked = s.pick.join('\u0001');
  const pathOf = (d) => d.ancestors().reverse().slice(1).map((a) => a.data.key).join('\u0001');
  const ink = EX.css(el, '--em-ink'), bg = EX.css(el, '--em-bg');

  g.selectAll('path.w').data(items).join('path').attr('class', 'w')
    .attr('d', ({ p }) => arc(p))
    .attr('fill', ({ d }) => { const v = EX.num(d.data.row[s.metric]);
                               return v === null ? 'url(#ex-few)' : EX.colorFor(el, s.metric, v); })
    .attr('stroke', ({ d }) => (pathOf(d) === picked ? ink : bg))
    .attr('stroke-width', ({ d }) => (pathOf(d) === picked ? 2 : 1))
    .attr('cursor', 'pointer')
    .on('mousemove', (ev, { d }) => {
      const n = EX.num(d.data.row.n), v = EX.num(d.data.row[s.metric]);
      tt.show(ev, d.data.name, [
        d.ancestors().reverse().slice(1, -1).map((a) => a.data.name).join(' › ') || null,
        `${EX.FMT.int(n)} response${n === 1 ? '' : 's'}${d.data.row.reliability === 'small sample' ? ' (small sample)' : ''}`,
        v === null ? (n == null ? 'Withheld or unavailable; not zero' : (n < 10 ? 'Too few to show a figure' : 'No figure for this measure')) : `${cfg.short}: ${cfg.fmt(v)}`,
        d.children ? 'Click to go deeper' : null,
      ]);
    })
    .on('mouseleave', () => tt.hide())
    .on('click', (ev, { d }) => {
      const pth = d.ancestors().reverse().slice(1).map((a) => a.data.key);
      EX.set(d.children && d.children.length ? { focus: pth, pick: pth } : { pick: pth });
    });

  // labels where the wedge is big enough to hold one
  // a label only appears where it fits along its own wedge, trimmed to the room available
  const CH = 5.7;
  const fitted = items.map((it) => {
    const { p, d } = it;
    const midR = ((p.y0 + p.y1) / 2) * step;
    const room = (p.x1 - p.x0) * midR - 8;
    const max = Math.floor(room / CH);
    if (max < 4 || (p.y1 - p.y0) * step < 15) return null;
    const t = d.data.name.length <= max ? d.data.name : d.data.name.slice(0, Math.max(3, max - 1)) + '…';
    return { ...it, t };
  }).filter(Boolean);
  g.selectAll('text.w').data(fitted).join('text').attr('class', 'w strong')
    .attr('transform', ({ p }) => {
      const a = ((p.x0 + p.x1) / 2) * 180 / Math.PI - 90, r = ((p.y0 + p.y1) / 2) * step;
      return `rotate(${a}) translate(${r},0) rotate(${a > 90 ? 180 : 0})`;
    })
    .attr('text-anchor', 'middle').attr('dy', '0.32em').attr('pointer-events', 'none')
    .style('font-size', '11px').attr('stroke', bg).attr('stroke-width', 3).attr('stroke-linejoin', 'round')
    .attr('paint-order', 'stroke fill')
    .text(({ t }) => t);

  // the middle: the group you are inside, click to come back out
  const centre = g.append('g').attr('cursor', focus === root ? 'default' : 'pointer')
    .on('click', () => {
      if (focus === root) return;
      const up = s.focus.slice(0, -1);
      EX.set({ focus: up, pick: up });
    });
  centre.append('circle').attr('r', step - 2).attr('fill', EX.css(el, '--em-panel')).attr('stroke', EX.css(el, '--em-line'));
  const cn = EX.num(focus.data.row.n), cv = EX.num(focus.data.row[s.metric]);
  const wrapLines = focus.data.name.length > 14 ? focus.data.name.split(' ') : [focus.data.name];
  centre.selectAll('text.n').data(wrapLines).join('text').attr('class', 'n strong')
    .attr('text-anchor', 'middle').style('font-size', '12px')
    .attr('y', (d, i) => -16 + i * 13 - (wrapLines.length - 1) * 6).text((d) => d);
  centre.append('text').attr('text-anchor', 'middle').attr('y', 8).style('font-size', '16px')
    .attr('class', 'strong').text(cv === null ? '—' : cfg.fmt(cv));
  centre.append('text').attr('text-anchor', 'middle').attr('y', 24).style('font-size', '10px')
    .text(EX.FMT.int(cn) + ' responses');
  if (focus !== root) centre.append('text').attr('text-anchor', 'middle').attr('y', 38).style('font-size', '10px')
    .attr('fill', EX.css(el, '--em-teal-ink')).text('↩ back out');
});

dash.draw('ringdetail', (el) => {
  const rs = EX.rows(); if (!rs) { el.classList.add('dash-skeleton'); return; }
  el.classList.remove('dash-skeleton');
  const s = EX.state();
  const tree = EXRING.build(rs, s.order);
  const node = EXRING.find(tree, s.pick.length ? s.pick : s.focus);
  const trail = [];
  let cur = tree;
  (s.pick.length ? s.pick : s.focus).forEach((k) => {
    const c = (cur.children || []).find((x) => x.key === k); if (c) { cur = c; trail.push(c.name); }
  });
  const kids = (node.children || []).map((c) => ({
    groupLabel: 'Go deeper', label: `${c.name} (${EX.FMT.int(EX.num(c.row.n))})`,
    onClick: () => {
      const p = (s.pick.length ? s.pick : s.focus).concat(c.key);
      EX.set(c.children && c.children.length ? { focus: p, pick: p } : { pick: p });
    },
  })).slice(0, 12);
  exDetail(el, { title: trail.length ? trail[trail.length - 1] : 'All responses',
                 subtitle: trail.length ? trail.slice(0, -1).concat('').join(' › ').replace(/ › $/, '') || 'Everyone, split below' : 'Click a wedge to look at one group.',
                 row: node.row, metric: s.metric, chips: kids });
});

/* ---------- the breakdown under the map ---------- */
function exBars(el, items, metric, onClick, selected) {
  const cfg = EX.METRICS[metric];
  el.replaceChildren();
  if (!items.length) {
    const p = document.createElement('p'); p.className = 'cap muted';
    p.textContent = window.EXLIVE ? 'No publishable breakdown for this selection. Protected groups are omitted.' : 'No responses to break down here.'; el.appendChild(p); return;
  }
  const W = Math.max(300, el.clientWidth), narrow = W < 540;
  const labW = narrow ? 0 : 185, rowH = narrow ? 60 : 46, m = { t: 6, r: 60, b: 26, l: labW + 10 };
  const H = m.t + items.length * rowH + m.b;
  const dom = cfg.domain, x = d3.scaleLinear(dom, [m.l, W - m.r]);
  const svg = EX.svg(el, W, H), tt = EX.tip(el);
  const grid = EX.css(el, '--em-grid'), axis = EX.css(el, '--em-axis'), ink = EX.css(el, '--em-ink');
  const ticks = x.ticks(5);
  svg.append('g').selectAll('line').data(ticks).join('line')
    .attr('x1', (t) => x(t)).attr('x2', (t) => x(t)).attr('y1', m.t).attr('y2', H - m.b)
    .attr('stroke', (t) => (t === 0 && cfg.diverging ? axis : grid));
  svg.append('g').selectAll('text').data(ticks).join('text')
    .attr('x', (t) => x(t)).attr('y', H - 8).attr('text-anchor', 'middle').text((t) => cfg.fmt(t));
  const base = cfg.diverging ? x(0) : x(dom[0]);
  const g = svg.append('g').selectAll('g').data(items).join('g')
    .attr('transform', (d, i) => `translate(0,${m.t + i * rowH + (narrow ? 26 : 6)})`)
    .attr('cursor', (d) => (onClick && d.clickable ? 'pointer' : 'default'));
  g.append('text').attr('class', 'strong').attr('x', narrow ? m.l : 0).attr('y', narrow ? -22 : 13)
    .attr('font-weight', (d) => (d.key === selected ? 700 : 600))
    .text((d) => (narrow || d.label.length < 28 ? d.label : d.label.slice(0, 26) + '…'));
  g.filter((d) => d.value !== null).append('text')
    .attr('x', narrow ? m.l : 0).attr('y', narrow ? -7 : 27).style('font-size', '10px')
    .attr('fill', (d) => (d.small ? 'var(--em-amber)' : 'var(--em-muted)'))
    .text((d) => 'n=' + EX.FMT.int(d.n) + (d.small ? ' · small sample' : ''));
  g.filter((d) => d.value !== null).append('rect')
    .attr('x', (d) => Math.min(base, x(d.value))).attr('width', (d) => Math.max(2, Math.abs(x(d.value) - base)))
    .attr('y', 6).attr('height', 18).attr('rx', 3)
    .attr('fill', (d) => EX.colorFor(el, metric, d.value))
    .attr('stroke', (d) => (d.key === selected ? ink : 'none')).attr('stroke-width', 1.5);
  g.filter((d) => d.value !== null && d.ciLow !== null && d.ciLow !== undefined).append('line')
    .attr('x1', (d) => x(Math.max(dom[0], d.ciLow))).attr('x2', (d) => x(Math.min(dom[1], d.ciHigh)))
    .attr('y1', 15).attr('y2', 15).attr('stroke', ink).attr('stroke-width', 1.2).attr('opacity', .75);
  g.filter((d) => d.value !== null).append('text').attr('class', 'strong')
    .attr('x', (d) => Math.max(x(d.value), base, d.ciHigh != null ? x(Math.min(dom[1], d.ciHigh)) : 0) + 7)
    .attr('y', 20).text((d) => cfg.fmt(d.value));
  g.filter((d) => d.value === null).append('text').attr('x', base + 6).attr('y', 20)
    .attr('fill', 'var(--em-muted)')
    .text((d) => (d.n < 10 ? `${d.n} response${d.n === 1 ? '' : 's'} — too few to show` : 'not enough answers'));
  g.append('rect').attr('x', 0).attr('y', narrow ? -34 : -4).attr('width', W).attr('height', rowH - 4).attr('fill', 'transparent')
    .on('mousemove', (ev, d) => tt.show(ev, d.label, [
      `${EX.FMT.int(d.n)} response${d.n === 1 ? '' : 's'}${d.small ? ' (small sample)' : ''}`,
      d.value === null ? 'No figure shown' : `${cfg.short}: ${cfg.fmt(d.value)}`,
      onClick && d.clickable ? 'Click to narrow to this group' : null]))
    .on('mouseleave', () => tt.hide())
    .on('click', (ev, d) => { if (onClick && d.clickable) onClick(d); });
}

dash.draw('splittitle', (el) => {
  const s = EX.state();
  const where = s.mcounty === EX.ALL ? (window.EXLIVE ? 'All surveyed locations' : 'All of Maryland') : s.mcounty + ' County';
  // when the bars already are the roles, naming the chosen role in the title would read twice
  const who = (s.mrole === EX.ALL || s.split === 'role') ? ''
    : ', ' + (s.mrole === 'Student' ? 'students' : s.mrole.toLowerCase());
  const by = { role: 'by role', session: 'by training session', quarter: 'by quarter', language: 'by language' }[s.split];
  el.textContent = `${where}${who}, ${by}`;
});
dash.draw('splitnote', (el) => {
  const s = EX.state();
  el.textContent = s.mcounty === EX.ALL
    ? 'This is everyone. Click a county on the map to break down just that county.'
    : (s.split === 'role' ? 'Click a role below to narrow further, then split it another way.'
                          : 'Change the split above, or click a role to narrow further.');
});

dash.draw('mapsplit', (el) => {
  const rs = EX.rows(); if (!rs) { el.classList.add('dash-skeleton'); return; }
  el.classList.remove('dash-skeleton');
  const s = EX.state();
  const mk = (key, label, row, clickable) => ({
    key, label, n: EX.num(row.n), value: EX.num(row[s.metric]),
    ciLow: s.metric === 'nps' ? EX.num(row.ci_low) : null,
    ciHigh: s.metric === 'nps' ? EX.num(row.ci_high) : null,
    small: row.reliability === 'small sample', clickable,
  });
  let items = [], onClick = null;
  if (s.split === 'role') {
    items = EX.ROLES.map((role) => {
      const r = EX.look(rs, s.mcounty, role, 'none', 'none');
      return r ? mk(role, role === 'Student' ? 'Students' : role, r, true) : null;
    }).filter(Boolean);
    onClick = (d) => EX.set({ mrole: d.key === s.mrole ? EX.ALL : d.key });
  } else {
    items = rs.filter((r) => r.county === s.mcounty && r.role === s.mrole && r.split_dim === s.split)
      .map((r) => mk(r.split_val, s.split === 'session'
        ? (s.mcounty === EX.ALL ? r.split_val.replace(' | ', ' · ') : r.split_val.split(' | ')[0])
        : r.split_val, r, false));
    if (s.split === 'session') items.sort((a, b) => a.label.localeCompare(b.label));
    else if (s.split === 'quarter') items.sort((a, b) => a.label.slice(-4).localeCompare(b.label.slice(-4)) || a.label.localeCompare(b.label));
    else items.sort((a, b) => b.n - a.n);
  }
  exBars(el, items, s.metric, onClick, s.split === 'role' ? s.mrole : null);
});

/* Live data adapter. The static standalone view remains available without a query. */
(async () => {
  const query = new URLSearchParams(location.search);
  if (!query.has('dataset')) return;
  try {
    const response = await fetch('/api/datasets/' + encodeURIComponent(query.get('dataset'))
      + '/dashboard?audience=' + encodeURIComponent(query.get('audience') || 'All respondents'));
    if (!response.ok) throw new Error('This censored dataset is no longer available. Reload the report.');
    const current = await response.json();
    window.EXLIVE = current.dataset_key;
    window.EXAUDIENCE = current.audience;
    document.querySelector('#top p').textContent = `${current.summaries[EX.ALL].n ?? 'Withheld'} retained responses · ${current.audience}. Current censored dataset. Finer splits and rings show publishable groups only; omitted groups are not zero.`;
    document.querySelectorAll('#map .ex-notes li').forEach((li, i) => {
      const notes = ['Colour shows the selected measure; grey means no publishable figure.',
        'Small groups and complements may be withheld, including their counts. Some finer partitions are omitted entirely. Rings show displayed groups only.',
        'Recorded likelihood-to-call scores exclude blanks; blank responses do not prove whether the item was shown.'];
      if (notes[i]) li.textContent = notes[i];
    });
    document.querySelector('#rings .ex-notes li:nth-child(2)').textContent = 'Wedges show publishable groups only. Omitted protected groups are not zero. Wedge areas describe the displayed subset, which may be smaller than the parent total.';
    EX.METRICS.nps.domain = [-100, 100];
    EX.METRICS.gain_index.domain = [-4, 4];
    EX.METRICS.pct_know_when.domain = [0, 100];
    EX.METRICS.call_mean.domain = [0, 10];
    EX.METRICS.engaged_mean.domain = [1, 5];
    EX.METRICS.pct_know_when.note = 'Paired valid before/after answers: % agreeing after training';
    dash.replace('cube', current.cube);
    EX.set({mcounty: EX.ALL, mrole: EX.ALL, focus: [], pick: []});
    window.EXREADY = true;
    document.getElementById('dash-root').style.visibility = '';
    if (parent !== window) parent.postMessage({type:'everymind-ready', dataset_key:current.dataset_key, audience:current.audience},location.origin);
  } catch (error) {
    document.getElementById('dash-root').style.visibility = '';
    document.getElementById('dash-root').replaceChildren(Object.assign(document.createElement('p'), {
      textContent: 'Could not load the current censored dataset. Reload the report; no prepared data is substituted.'}));
  }
})();
