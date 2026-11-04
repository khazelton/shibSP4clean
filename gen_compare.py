#!/usr/bin/env python3
"""Generate a reviewer page comparing every tracked file in shibSP4clean with its
counterpart in shibSp4PoC, as one self-contained HTML page.

  ./gen_compare.py [OUT_HTML [POC_ROOT]]

Defaults: OUT_HTML = compare.html, POC_ROOT = ../shibSp4PoC (next to this repo).
Clean side = the repo this script lives in. Edit NOTES when a file's reason for
differing changes; a newly differing file without a NOTES entry stops the run."""
import datetime, difflib, hashlib, html, subprocess, sys
from pathlib import Path

CLEAN = Path(__file__).resolve().parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("compare.html")
POC = Path(sys.argv[2]) if len(sys.argv) > 2 else CLEAN.parent / "shibSp4PoC"
CTX = 3

def git(root, *a):
    return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True, check=True).stdout.strip()

def counterpart(rel):
    return ".gitignore" if rel == ".gitignore" else f"deploy/{rel}"

# Why each differing file differs (reviewer-facing). Keyed by clean path.
NOTES = {
    "agent/conf/shibboleth-sp/agent.ini": ("config", 1,
        "Agent logs in to the hub as <code>sa3-sp4-agent</code> instead of <code>sa1-sp4-agent</code>. "
        "sa1 lives in LDAP, which the clean stack doesn't have; sa3 lives in the htpasswd file."),
    "hub/agents/agents.csv": ("config", 2,
        "Agent's allowed source address moves from <code>172.30.0.20/32</code> to <code>172.31.0.20/32</code>, "
        "matching the clean stack's subnet so both networks can exist side by side."),
    "hub/agents/generated/agents-generated.xml": ("config", 3,
        "Generated from <code>agents.csv</code> by <code>gen-agents-xml.py</code>; carries the same address change. "
        "Not edited by hand."),
    "compose.yaml": ("rewrite", 4,
        "Rewritten for the smaller stack: the <code>ldap</code> and <code>app</code> services are removed, the hub "
        "drops its LDAP variables and keeps only <code>AGENT_HTPASSWD</code>, and containers, images, network and "
        "subnet are renamed (<code>sp4clean-*</code>, <code>sp4</code>, <code>172.31.0.0/24</code>). Hub and agent "
        "volumes, ports and healthcheck are unchanged."),
    "README.md": ("housekeeping", 5,
        "Different documents. The clean README describes this stack and how it differs from the PoC; the PoC's "
        "<code>deploy/README.md</code> is the full runbook. Shown for completeness, no line-by-line review needed."),
    ".gitignore": ("housekeeping", 6,
        "Each repo's own ignore list. The PoC's lives at its repo root and prefixes paths with <code>deploy/</code>; "
        "the clean one ignores the same secrets (<code>.env</code>, <code>agent.pwd</code>, <code>*.htpasswd</code>) "
        "plus <code>*.ldif</code>. Shown for completeness."),
}
KIND_LABEL = {"config": "Config change", "rewrite": "Rewritten", "housekeeping": "Repo housekeeping"}

def esc(s): return html.escape(s, quote=False)

def intraline(a, b):
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    oa, ob = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        x, y = esc(a[i1:i2]), esc(b[j1:j2])
        if op == "equal":
            oa.append(x); ob.append(y)
        else:
            if x: oa.append(f"<mark>{x}</mark>")
            if y: ob.append(f"<mark>{y}</mark>")
    return "".join(oa), "".join(ob)

def build_rows(old, new):
    """Return list of row dicts: kind in eq/del/add/chg, with left/right numbers and html."""
    rows = []
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                rows.append(dict(k="eq", ln=i1+k+1, rn=j1+k+1, l=esc(old[i1+k]), r=esc(new[j1+k])))
        elif op == "delete":
            for k in range(i1, i2): rows.append(dict(k="del", ln=k+1, rn=None, l=esc(old[k]), r=None))
        elif op == "insert":
            for k in range(j1, j2): rows.append(dict(k="add", ln=None, rn=k+1, l=None, r=esc(new[k])))
        else:
            n = max(i2 - i1, j2 - j1)
            for k in range(n):
                a = old[i1+k] if i1+k < i2 else None
                b = new[j1+k] if j1+k < j2 else None
                # pair lines only when they are recognisably the same line
                if a is not None and b is not None and difflib.SequenceMatcher(None, a, b).ratio() > 0.5:
                    la, lb = intraline(a, b)
                    rows.append(dict(k="chg", ln=i1+k+1, rn=j1+k+1, l=la, r=lb))
                else:
                    if a is not None: rows.append(dict(k="del", ln=i1+k+1, rn=None, l=esc(a), r=None))
                    if b is not None: rows.append(dict(k="add", ln=None, rn=j1+k+1, l=None, r=esc(b)))
    return rows

def segments(rows):
    """Split rows into shown/folded segments, folding long equal runs."""
    out, i, n = [], 0, len(rows)
    while i < n:
        if rows[i]["k"] != "eq":
            j = i
            while j < n and rows[j]["k"] != "eq": j += 1
            out.append(("show", rows[i:j])); i = j; continue
        j = i
        while j < n and rows[j]["k"] == "eq": j += 1
        run = rows[i:j]
        head = CTX if i > 0 else 0
        tail = CTX if j < n else 0
        if len(run) > head + tail + 2:
            if head: out.append(("show", run[:head]))
            out.append(("fold", run[head:len(run)-tail]))
            if tail: out.append(("show", run[len(run)-tail:]))
        else:
            out.append(("show", run))
        i = j
    return out

def num(x): return "" if x is None else str(x)

def split_row(r):
    k = r["k"]
    lc = {"eq": "", "del": "del", "add": "empty", "chg": "del"}[k]
    rc = {"eq": "", "del": "empty", "add": "add", "chg": "add"}[k]
    l = "" if r["l"] is None else r["l"]
    rr = "" if r["r"] is None else r["r"]
    return (f'<tr class="{k}"><td class="n">{num(r["ln"])}</td><td class="c {lc}">{l}</td>'
            f'<td class="n">{num(r["rn"])}</td><td class="c {rc}">{rr}</td></tr>')

def unified_rows(r):
    k = r["k"]
    if k == "eq":
        return [f'<tr><td class="n">{num(r["ln"])}</td><td class="n">{num(r["rn"])}</td><td class="s"></td><td class="c">{r["l"]}</td></tr>']
    out = []
    if r["l"] is not None:
        out.append(f'<tr><td class="n">{num(r["ln"])}</td><td class="n"></td><td class="s del">−</td><td class="c del">{r["l"]}</td></tr>')
    if r["r"] is not None:
        out.append(f'<tr><td class="n"></td><td class="n">{num(r["rn"])}</td><td class="s add">+</td><td class="c add">{r["r"]}</td></tr>')
    return out

def render_diff(fid, rows):
    sbs, uni = [], []
    for idx, (kind, seg) in enumerate(segments(rows)):
        if kind == "fold":
            label = f'{len(seg)} unchanged line{"s" if len(seg) != 1 else ""} (PoC {seg[0]["ln"]}–{seg[-1]["ln"]})'
            sbs.append(f'<tbody class="foldbar"><tr><td colspan="4"><button type="button" class="fold" aria-expanded="false">Show {label}</button></td></tr></tbody>')
            sbs.append('<tbody class="folded" hidden>' + "".join(split_row(r) for r in seg) + "</tbody>")
            uni.append(f'<tbody class="foldbar"><tr><td colspan="4"><button type="button" class="fold" aria-expanded="false">Show {label}</button></td></tr></tbody>')
            uni.append('<tbody class="folded" hidden>' + "".join(x for r in seg for x in unified_rows(r)) + "</tbody>")
        else:
            sbs.append("<tbody>" + "".join(split_row(r) for r in seg) + "</tbody>")
            uni.append("<tbody>" + "".join(x for r in seg for x in unified_rows(r)) + "</tbody>")
    colg_s = '<colgroup><col class="cn"><col><col class="cn"><col></colgroup>'
    colg_u = '<colgroup><col class="cn"><col class="cn"><col class="cs"><col></colgroup>'
    head_s = '<thead><tr><th colspan="2">shibSp4PoC</th><th colspan="2">shibSP4clean</th></tr></thead>'
    return (f'<div class="scroller view-split"><table class="diff split">{colg_s}{head_s}{"".join(sbs)}</table></div>'
            f'<div class="scroller view-unified"><table class="diff unified">{colg_u}{"".join(uni)}</table></div>')

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

EXCLUDE = {"gen_compare.py"}   # tooling for this page; no PoC counterpart
files = [f for f in git(CLEAN, "ls-files").splitlines() if f not in EXCLUDE]
same, diffs = [], []
for rel in files:
    cp = POC / counterpart(rel)
    if not cp.exists():
        sys.exit(f"{rel} has no counterpart at {cp}; add it to EXCLUDE or map it in counterpart()")
    a, b = cp.read_text(), (CLEAN / rel).read_text()
    if a == b:
        same.append((rel, counterpart(rel), sha(cp)[:12], len(b.splitlines())))
        continue
    old, new = a.splitlines(), b.splitlines()
    rows = build_rows(old, new)
    minus = sum(1 for r in rows if r["k"] in ("del", "chg"))
    plus = sum(1 for r in rows if r["k"] in ("add", "chg"))
    if rel not in NOTES:
        sys.exit(f"{rel} differs from {counterpart(rel)} but has no NOTES entry; add one")
    kind, order, note = NOTES[rel]
    diffs.append(dict(rel=rel, cp=counterpart(rel), rows=rows, minus=minus, plus=plus,
                      kind=kind, order=order, note=note, oldn=len(old), newn=len(new)))
diffs.sort(key=lambda d: d["order"])

clean_head = git(CLEAN, "log", "-1", "--format=%h")
poc_head = git(POC, "log", "-1", "--format=%h")
poc_deploy = git(POC, "log", "-1", "--format=%h %cs", "--", "deploy", ".gitignore")
clean_url = "https://github.com/khazelton/shibSP4clean"

def fid(rel): return "f-" + rel.replace("/", "-").replace(".", "-").strip("-")

def chip(kind): return f'<span class="chip {kind}">{KIND_LABEL[kind]}</span>'

index_rows = []
for rel in files:
    d = next((x for x in diffs if x["rel"] == rel), None)
    if d:
        st = f'<a href="#{fid(rel)}">{chip(d["kind"])}</a>'
        dl = f'<span class="m">−{d["minus"]}</span> <span class="p">+{d["plus"]}</span>'
    else:
        st = '<a href="#identical"><span class="chip same">Identical</span></a>'
        dl = '<span class="dim">0</span>'
    index_rows.append(f'<tr class="{"d" if d else "s"}"><td><code>{esc(rel)}</code></td>'
                      f'<td><code>{esc(counterpart(rel))}</code></td><td>{st}</td><td class="num">{dl}</td></tr>')

sections = []
for d in diffs:
    collapsed = d["kind"] == "housekeeping"
    body = render_diff(fid(d["rel"]), d["rows"])
    sections.append(f'''
<section class="file" id="{fid(d["rel"])}">
  <header class="fh">
    <div class="fh-top">
      <h3><code>{esc(d["rel"])}</code></h3>
      {chip(d["kind"])}
      <span class="delta"><span class="m">−{d["minus"]}</span> <span class="p">+{d["plus"]}</span></span>
      <label class="rv"><input type="checkbox" id="rv-{fid(d["rel"])}" data-key="{esc(d["rel"])}"> Reviewed</label>
    </div>
    <p class="paths">PoC <code>{esc(d["cp"])}</code> ({d["oldn"]} lines) → clean <code>{esc(d["rel"])}</code> ({d["newn"]} lines)</p>
    <p class="why">{d["note"]}</p>
  </header>
  {"<details><summary>Show diff</summary>" + body + "</details>" if collapsed else body}
</section>''')

same_rows = "".join(
    f'<tr><td><code>{esc(r)}</code></td><td><code>{esc(c)}</code></td><td class="num">{n}</td><td><code class="hash">{h}</code></td></tr>'
    for r, c, h, n in same)

n_total, n_same, n_diff = len(files), len(same), len(diffs)
n_cfg = sum(1 for d in diffs if d["kind"] == "config")

page = f'''<title>shibSP4clean File Comparison</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Sans+Condensed:wght@600&display=swap">
<style>
/* Layout: one reading column; summary → reading order → index → diffs → identical files. Diffs scroll sideways in their own box. */
:root {{
  --bg: #f6f7f8; --surface: #ffffff; --fg: #1b2228; --muted: #5b6670; --line: #d9dee3;
  --accent: #1f6f8b; --accent-weak: #e2eff4;
  --del-bg: #fbe9e7; --del-mark: #f4b9b1; --del-fg: #8f2a1d;
  --add-bg: #e6f4ea; --add-mark: #a6dbb4; --add-fg: #1d6b34;
  --fold: #eef1f4; --chip-cfg: #fff1d6; --chip-cfg-fg: #7a4d00; --chip-rw: #e9e4f7; --chip-rw-fg: #4b3a8a;
  --chip-hk: #eceff2; --chip-hk-fg: #4a545d; --chip-same: #e6f4ea; --chip-same-fg: #1d6b34;
  --sans: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --cond: "IBM Plex Sans Condensed", "IBM Plex Sans", system-ui, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #12171b; --surface: #182026; --fg: #e3e8ec; --muted: #97a3ad; --line: #2b353d;
  --accent: #6cc0dc; --accent-weak: #1b3440;
  --del-bg: #3a1f1c; --del-mark: #7a3229; --del-fg: #ffb4a8;
  --add-bg: #17331f; --add-mark: #2d6b3d; --add-fg: #9fe0b0;
  --fold: #1d262d; --chip-cfg: #3d2f12; --chip-cfg-fg: #ffd58a; --chip-rw: #2c2547; --chip-rw-fg: #c9bcff;
  --chip-hk: #263038; --chip-hk-fg: #b4bec7; --chip-same: #17331f; --chip-same-fg: #9fe0b0;
  color-scheme: dark; }} }}
:root[data-theme="dark"] {{
  --bg: #12171b; --surface: #182026; --fg: #e3e8ec; --muted: #97a3ad; --line: #2b353d;
  --accent: #6cc0dc; --accent-weak: #1b3440;
  --del-bg: #3a1f1c; --del-mark: #7a3229; --del-fg: #ffb4a8;
  --add-bg: #17331f; --add-mark: #2d6b3d; --add-fg: #9fe0b0;
  --fold: #1d262d; --chip-cfg: #3d2f12; --chip-cfg-fg: #ffd58a; --chip-rw: #2c2547; --chip-rw-fg: #c9bcff;
  --chip-hk: #263038; --chip-hk-fg: #b4bec7; --chip-same: #17331f; --chip-same-fg: #9fe0b0;
  color-scheme: dark; }}
* {{ box-sizing: border-box; }}
body {{ background: var(--bg); color: var(--fg); font-family: var(--sans); font-size: 15px; line-height: 1.55; }}
.wrap {{ max-width: 1180px; margin: 0 auto; padding-block: 32px 64px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: grid; gap: 40px; }}
.wrap > * {{ min-width: 0; }}
h1, h2 {{ font-family: var(--cond); font-weight: 600; text-wrap: balance; margin: 0; letter-spacing: -0.01em; }}
h1 {{ font-size: 2rem; line-height: 1.15; }}
h2 {{ font-size: 1.3rem; }}
h3 {{ margin: 0; font-size: 1rem; font-weight: 600; overflow-wrap: anywhere; }}
p {{ margin: 0; }}
code {{ font-family: var(--mono); font-size: 0.88em; }}
a {{ color: var(--accent); }}
a:focus-visible, button:focus-visible, input:focus-visible, summary:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
.eyebrow {{ font-size: 0.75rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); font-weight: 600; }}
.intro {{ display: grid; gap: 14px; }}
.lede {{ max-width: 68ch; color: var(--muted); }}
.meta {{ display: flex; flex-wrap: wrap; gap: 8px 24px; font-size: 0.85rem; color: var(--muted); }}
.meta b {{ color: var(--fg); font-weight: 500; }}
.tally {{ display: flex; flex-wrap: wrap; gap: 0; border: 1px solid var(--line); background: var(--surface); border-radius: 6px; }}
.tally div {{ flex: 1 1 140px; padding: 14px 18px; border-right: 1px solid var(--line); display: grid; gap: 2px; }}
.tally div:last-child {{ border-right: 0; }}
.tally strong {{ font-family: var(--cond); font-size: 1.7rem; font-weight: 600; font-variant-numeric: tabular-nums; line-height: 1.1; }}
.tally span {{ font-size: 0.82rem; color: var(--muted); }}
.block {{ display: grid; gap: 14px; }}
.block > p {{ max-width: 72ch; color: var(--muted); }}
ol.order {{ list-style: none; margin: 0; padding: 0; display: grid; gap: 0; border-top: 1px solid var(--line); counter-reset: o; }}
ol.order li {{ counter-increment: o; display: grid; grid-template-columns: 2rem 1fr; column-gap: 8px; row-gap: 4px;
  padding: 12px 0; border-bottom: 1px solid var(--line); align-items: baseline; }}
ol.order li::before {{ content: counter(o); grid-row: span 2; font-family: var(--cond); font-weight: 600; color: var(--muted); font-variant-numeric: tabular-nums; }}
.oline {{ display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px; }}
ol.order p {{ color: var(--muted); max-width: 80ch; font-size: 0.92rem; }}
.chip {{ display: inline-block; font-size: 0.72rem; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase;
  padding: 2px 8px; border-radius: 3px; white-space: nowrap; }}
.chip.config {{ background: var(--chip-cfg); color: var(--chip-cfg-fg); }}
.chip.rewrite {{ background: var(--chip-rw); color: var(--chip-rw-fg); }}
.chip.housekeeping {{ background: var(--chip-hk); color: var(--chip-hk-fg); }}
.chip.same {{ background: var(--chip-same); color: var(--chip-same-fg); }}
a:has(> .chip) {{ text-decoration: none; }}
.delta {{ font-family: var(--mono); font-size: 0.82rem; font-variant-numeric: tabular-nums; white-space: nowrap; }}
.m {{ color: var(--del-fg); }} .p {{ color: var(--add-fg); }} .dim {{ color: var(--muted); }}
.rv {{ font-size: 0.85rem; color: var(--muted); display: inline-flex; gap: 6px; align-items: center; cursor: pointer; white-space: nowrap; }}
.rv input {{ accent-color: var(--accent); width: 16px; height: 16px; margin: 0; }}
.tablebox {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 6px; background: var(--surface); }}
table.idx {{ border-collapse: collapse; width: 100%; font-size: 0.88rem; }}
table.idx th {{ text-align: left; font-size: 0.72rem; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted);
  font-weight: 600; padding: 10px 14px; border-bottom: 1px solid var(--line); white-space: nowrap; }}
table.idx td {{ padding: 7px 14px; border-bottom: 1px solid var(--line); vertical-align: baseline; }}
table.idx tr:last-child td {{ border-bottom: 0; }}
table.idx tr.s td:not(:nth-child(3)) {{ color: var(--muted); }}
table.idx td.num, table.idx th.num {{ text-align: right; white-space: nowrap; }}
code.hash {{ color: var(--muted); }}
.toolbar {{ display: flex; flex-wrap: wrap; gap: 10px 20px; align-items: center; justify-content: space-between;
  position: sticky; top: env(safe-area-inset-top, 0px); z-index: 5; background: var(--bg); padding-block: 10px; border-bottom: 1px solid var(--line); }}
body::before {{ content: ""; position: fixed; inset: 0 0 auto; height: env(safe-area-inset-top, 0px); z-index: 10; background: var(--bg); }}
.seg {{ display: inline-flex; border: 1px solid var(--line); border-radius: 5px; overflow: hidden; }}
.seg button {{ font: inherit; font-size: 0.85rem; padding: 5px 12px; background: var(--surface); color: var(--fg); border: 0; cursor: pointer; }}
.seg button + button {{ border-left: 1px solid var(--line); }}
.seg button[aria-pressed="true"] {{ background: var(--accent); color: var(--surface); }}
.progress {{ font-size: 0.85rem; color: var(--muted); font-variant-numeric: tabular-nums; }}
.files {{ display: grid; gap: 28px; }}
.file {{ display: grid; gap: 12px; scroll-margin-top: 64px; }}
.fh {{ display: grid; gap: 6px; }}
.fh-top {{ display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px; }}
.paths {{ font-size: 0.82rem; color: var(--muted); overflow-wrap: anywhere; }}
.why {{ max-width: 80ch; }}
.file.done .fh h3 {{ color: var(--muted); }}
details > summary {{ cursor: pointer; color: var(--accent); font-size: 0.9rem; padding-block: 4px; }}
details[open] > summary {{ margin-bottom: 10px; }}
.scroller {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 6px; background: var(--surface); }}
table.diff {{ border-collapse: collapse; width: 100%; font-family: var(--mono); font-size: 12.5px; line-height: 1.5; table-layout: fixed; }}
table.split {{ min-width: 900px; }}
table.unified {{ min-width: 560px; }}
col.cn {{ width: 3.4em; }} col.cs {{ width: 1.6em; }}
table.diff thead th {{ font-family: var(--sans); font-size: 0.72rem; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted);
  text-align: left; font-weight: 600; padding: 6px 10px; border-bottom: 1px solid var(--line); }}
table.diff thead th + th {{ border-left: 1px solid var(--line); }}
table.diff td {{ padding: 0 10px; vertical-align: top; white-space: pre-wrap; overflow-wrap: anywhere; }}
table.diff td.n {{ color: var(--muted); text-align: right; padding: 0 6px; user-select: none; font-variant-numeric: tabular-nums; white-space: nowrap; }}
table.split td.n:nth-child(3) {{ border-left: 1px solid var(--line); }}
table.diff td.s {{ padding: 0; text-align: center; user-select: none; }}
td.del {{ background: var(--del-bg); }} td.add {{ background: var(--add-bg); }}
td.s.del {{ color: var(--del-fg); }} td.s.add {{ color: var(--add-fg); }}
td.empty {{ background: repeating-linear-gradient(135deg, transparent 0 6px, var(--fold) 6px 8px); }}
tr.del td.n:first-child, tr.chg td.n:first-child {{ color: var(--del-fg); }}
tr.add td.n:nth-child(3), tr.chg td.n:nth-child(3) {{ color: var(--add-fg); }}
td.del mark {{ background: var(--del-mark); color: inherit; border-radius: 2px; }}
td.add mark {{ background: var(--add-mark); color: inherit; border-radius: 2px; }}
tbody.foldbar td {{ padding: 0; background: var(--fold); border-block: 1px solid var(--line); }}
button.fold {{ font: inherit; font-family: var(--sans); font-size: 0.8rem; color: var(--accent); background: none; border: 0; cursor: pointer; padding: 4px 12px; width: 100%; text-align: left; }}
body.mode-split .view-unified {{ display: none; }}
body.mode-unified .view-split {{ display: none; }}
.ident {{ display: grid; gap: 12px; }}
.foot {{ font-size: 0.85rem; color: var(--muted); display: grid; gap: 6px; max-width: 80ch; }}
@media (max-width: 640px) {{ h1 {{ font-size: 1.6rem; }} .tally div {{ border-right: 0; border-bottom: 1px solid var(--line); }} .tally div:last-child {{ border-bottom: 0; }} }}
@media (prefers-reduced-motion: reduce) {{ * {{ scroll-behavior: auto !important; }} }}
</style>

<div class="wrap">
  <header class="intro">
    <p class="eyebrow">Review packet · SP v4 hub + agent</p>
    <h1>shibSP4clean compared with shibSp4PoC</h1>
    <p class="lede">Every file tracked in <a href="{clean_url}">shibSP4clean</a>, set against the file it was copied from in shibSp4PoC (<code>deploy/</code>, or the repo root for <code>.gitignore</code>). Only clean-repo files are covered. PoC files with no clean counterpart (LDAP, the demo app, extra scripts) are out of scope.</p>
    <div class="meta">
      <span>shibSP4clean <b><code>{clean_head}</code></b></span>
      <span>shibSp4PoC <b><code>{poc_head}</code></b> · <code>deploy/</code> last changed <b><code>{poc_deploy}</code></b></span>
      <span>Generated {datetime.date.today().isoformat()}</span>
    </div>
  </header>

  <div class="tally" role="group" aria-label="Summary">
    <div><strong>{n_total}</strong><span>files compared</span></div>
    <div><strong>{n_same}</strong><span>byte-identical</span></div>
    <div><strong>{n_cfg}</strong><span>one-line config changes</span></div>
    <div><strong>{n_diff - n_cfg}</strong><span>rewritten or repo-specific</span></div>
  </div>

  <section class="block" aria-labelledby="h-order">
    <h2 id="h-order">What to review</h2>
    <p>The {n_diff} files that differ, most important first. Items 1–3 are the substantive change: the agent authenticates via htpasswd instead of LDAP, on a different subnet. Item 4 follows from dropping LDAP and the app. Items 5–6 are each repo's own documentation and ignore list.</p>
    <ol class="order">{"".join(
        f'<li><div class="oline"><a href="#{fid(d["rel"])}"><code>{esc(d["rel"])}</code></a>{chip(d["kind"])}'
        f'<span class="delta"><span class="m">−{d["minus"]}</span> <span class="p">+{d["plus"]}</span></span></div>'
        f'<p>{d["note"]}</p></li>' for d in diffs)}</ol>
  </section>

  <section class="block" aria-labelledby="h-index">
    <h2 id="h-index">All files</h2>
    <div class="tablebox"><table class="idx">
      <thead><tr><th>shibSP4clean</th><th>shibSp4PoC counterpart</th><th>Status</th><th class="num">Lines −/+</th></tr></thead>
      <tbody>{"".join(index_rows)}</tbody>
    </table></div>
  </section>

  <section class="block" aria-labelledby="h-diffs">
    <div class="toolbar">
      <h2 id="h-diffs">Differences</h2>
      <div class="seg" role="group" aria-label="Diff layout">
        <button type="button" id="mode-split" aria-pressed="true">Side by side</button>
        <button type="button" id="mode-unified" aria-pressed="false">Unified</button>
      </div>
      <span class="progress" id="progress" aria-live="polite"></span>
    </div>
    <p>PoC on the left (red), clean on the right (green). Changed characters within a line are highlighted more strongly. Runs of unchanged lines are folded; click a fold to expand it.</p>
    <div class="files">{"".join(sections)}</div>
  </section>

  <section class="block ident" id="identical" aria-labelledby="h-ident">
    <h2 id="h-ident">Identical files</h2>
    <p>These {n_same} files are byte-for-byte the same in both repos. The SHA-256 prefix is the same on both sides, so there is nothing to review.</p>
    <div class="tablebox"><table class="idx">
      <thead><tr><th>shibSP4clean</th><th>shibSp4PoC counterpart</th><th class="num">Lines</th><th>SHA-256</th></tr></thead>
      <tbody>{same_rows}</tbody>
    </table></div>
  </section>

  <footer class="foot">
    <p>Not compared: gitignored local files that exist only on the build machine (<code>.env</code>, <code>agent/conf/shibboleth-sp/agent.pwd</code>, <code>hub/htpasswd/agents.htpasswd</code>, <code>hub/agents/agents.ldif</code>). The secrets differ between the repos by design. Also left out: <code>gen_compare.py</code>, the script that builds this page.</p>
    <p>Verified on hub nightly 0.0.3-35: the clean stack's agent↔hub remoting is OK and a Google login delivers all expected attributes.</p>
  </footer>
</div>

<script>
(function () {{
  var store = {{
    get: function (k) {{ try {{ return localStorage.getItem(k); }} catch (e) {{ return null; }} }},
    set: function (k, v) {{ try {{ localStorage.setItem(k, v); }} catch (e) {{}} }}
  }};
  var body = document.body;
  function setMode(m) {{
    body.classList.remove("mode-split", "mode-unified");
    body.classList.add("mode-" + m);
    document.getElementById("mode-split").setAttribute("aria-pressed", m === "split");
    document.getElementById("mode-unified").setAttribute("aria-pressed", m === "unified");
    store.set("cmp-mode", m);
  }}
  var saved = store.get("cmp-mode");
  setMode(saved || (window.matchMedia("(max-width: 760px)").matches ? "unified" : "split"));
  document.getElementById("mode-split").addEventListener("click", function () {{ setMode("split"); }});
  document.getElementById("mode-unified").addEventListener("click", function () {{ setMode("unified"); }});

  document.addEventListener("click", function (e) {{
    var b = e.target.closest("button.fold");
    if (!b) return;
    var tb = b.closest("tbody").nextElementSibling;
    var open = tb.hidden;
    tb.hidden = !open;
    b.setAttribute("aria-expanded", open);
    b.textContent = open ? b.textContent.replace(/^Show/, "Hide") : b.textContent.replace(/^Hide/, "Show");
  }});

  var boxes = Array.prototype.slice.call(document.querySelectorAll(".rv input"));
  var keys = Array.from(new Set(boxes.map(function (x) {{ return x.dataset.key; }})));
  function refresh() {{
    var done = 0;
    keys.forEach(function (k) {{
      var on = store.get("cmp-rv:" + k) === "1";
      if (on) done++;
      boxes.forEach(function (x) {{ if (x.dataset.key === k) {{ x.checked = on; var s = x.closest(".file"); if (s) s.classList.toggle("done", on); }} }});
    }});
    document.getElementById("progress").textContent = done + " of " + keys.length + " reviewed";
  }}
  var mem = {{}};
  var origGet = store.get;
  store.get = function (k) {{ var v = origGet(k); return v === null && k in mem ? mem[k] : v; }};
  boxes.forEach(function (x) {{
    x.addEventListener("change", function () {{
      var k = "cmp-rv:" + x.dataset.key, v = x.checked ? "1" : "0";
      mem[k] = v; store.set(k, v); refresh();
    }});
  }});
  refresh();
}})();
</script>
'''
OUT.write_text(page)
print(f"{n_total} files: {n_same} identical, {n_diff} differ -> {OUT}")
for d in diffs: print(f"  {d['rel']}: -{d['minus']} +{d['plus']}")
