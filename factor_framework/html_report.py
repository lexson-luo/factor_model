"""HTML rendering of the Markdown reports.

Each ``output/*.md`` report gets a self-contained ``.html`` sibling: charts are
embedded (the file can be mailed on its own), numeric table columns are
right-aligned on tabular figures, wide tables scroll inside their own frame with
a sticky header and first column, and a sidebar lists the sections.

Only the Markdown subset the report writers emit is supported: ATX headings,
blockquotes, bullet lists, pipe tables, images, footnotes, paragraphs and the
inline forms **bold**, *italic*, `code`, [link](url).
"""
from __future__ import annotations

import base64
import html
import re
from pathlib import Path

REPORTS = [
    ("management_summary", "Management summary"),
    ("risk_report", "Risk & Middle Office"),
    ("pm_report", "PM report"),
    ("validation_report", "Validation"),
    ("calibration_report", "Calibration"),
]

_NUM = re.compile(r"^[+\-−]?(\$)?\d[\d,]*(\.\d+)?(%|m|k|bn|x|bp|d)?$|^[+\-−]?\.\d+$")
_RANGE = re.compile(r"^\[\s*[+\-−]?[\d.]+,\s*[+\-−]?[\d.]+\s*\]$")
_EMPTY = {"", "–", "-", "—", "nan", "NaN", "None", "n/a"}


def _slug(text: str, seen: dict) -> str:
    s = re.sub(r"[^\w\s-]", "", re.sub(r"<[^>]+>", "", text)).strip().lower()
    s = re.sub(r"[\s_]+", "-", s) or "section"
    n = seen.get(s, 0)
    seen[s] = n + 1
    return s if n == 0 else f"{s}-{n}"


def _inline(text: str, notes: dict) -> str:
    """Escape, then apply inline Markdown.  Code spans are protected first."""
    codes: list[str] = []

    def keep(m):
        codes.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    t = re.sub(r"`([^`]+)`", keep, text)
    t = html.escape(t, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", t)
    t = re.sub(r"\[\^([\w-]+)\]", lambda m: _note_ref(m.group(1), notes), t)
    t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', t)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], t)


def _note_ref(key: str, notes: dict) -> str:
    n = notes.setdefault(key, len(notes) + 1)
    return f'<sup class="fn"><a href="#fn-{key}">{n}</a></sup>'


def _cells(row: str) -> list[str]:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip() for c in row.split("|")]


def _is_num(c: str) -> bool:
    c = c.replace(" ", "")
    return bool(_NUM.match(c) or _RANGE.match(c))


def _cell_class(c: str) -> str:
    cls = []
    raw = c.replace(" ", "")
    if _NUM.match(raw) and raw[0] in "-−":
        cls.append("neg")
    if c.startswith("BREACH"):
        cls.append("st-breach")
    elif c.startswith("WARN"):
        cls.append("st-warn")
    elif c == "OK":
        cls.append("st-ok")
    return " ".join(cls)


def _table(lines: list[str], notes: dict) -> str:
    head = _cells(lines[0])
    body = [_cells(r) for r in lines[2:]]
    ncol = len(head)
    body = [(r + [""] * ncol)[:ncol] for r in body]
    numeric = []
    for j in range(ncol):
        vals = [r[j] for r in body if r[j] not in _EMPTY]
        numeric.append(bool(vals) and all(_is_num(v) for v in vals))
    out = ['<div class="table-wrap"><table>', "<thead><tr>"]
    for j, h in enumerate(head):
        out.append(f'<th class="{"num" if numeric[j] else "txt"}">{_inline(h, notes)}</th>')
    out.append("</tr></thead><tbody>")
    for r in body:
        out.append("<tr>")
        for j, c in enumerate(r):
            cls = ["num" if numeric[j] else "txt"]
            extra = _cell_class(c)
            if extra:
                cls.append(extra)
            if c in _EMPTY and c:
                cls.append("empty")
            out.append(f'<td class="{" ".join(cls)}">{_inline(c, notes)}</td>')
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def _image(alt: str, src: str, base: Path, embed: bool) -> str:
    path = base / src
    url = src
    if embed and path.exists():
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml"}.get(
            path.suffix.lower(), "application/octet-stream")
        url = f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"
    a = html.escape(alt)
    return (f'<figure><a href="{html.escape(src)}" target="_blank" rel="noopener">'
            f'<img src="{url}" alt="{a}" loading="lazy"></a></figure>')


def md_to_html(md: str, base: Path, embed: bool = True) -> tuple[str, str, list[tuple[int, str, str]]]:
    """Return (title, body html, toc entries [(level, id, text)])."""
    lines = md.replace("\r\n", "\n").split("\n")
    notes: dict[str, int] = {}
    note_text: dict[str, str] = {}
    seen: dict[str, int] = {}
    toc: list[tuple[int, str, str]] = []
    title = ""
    out: list[str] = []
    para: list[str] = []
    i = 0

    def flush():
        if para:
            out.append(f"<p>{_inline(' '.join(para), notes)}</p>")
            para.clear()

    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s:
            flush(); i += 1; continue
        m = re.match(r"^\[\^([\w-]+)\]:\s*(.*)$", s)
        if m:
            flush(); note_text[m.group(1)] = m.group(2); i += 1; continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            flush()
            lvl, txt = len(m.group(1)), m.group(2).strip()
            inner = _inline(txt, notes)
            if lvl == 1 and not title:
                title = html.unescape(re.sub(r"<[^>]+>", "", inner))
                out.append(f'<h1 id="top">{inner}</h1>')
            else:
                hid = _slug(inner, seen)
                if lvl <= 3:
                    toc.append((lvl, hid, html.unescape(re.sub(r"<[^>]+>", "", inner))))
                out.append(f'<h{lvl} id="{hid}"><a class="anchor" href="#{hid}">#</a>{inner}</h{lvl}>')
            i += 1; continue
        m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", s)
        if m:
            flush(); out.append(_image(m.group(1), m.group(2), base, embed)); i += 1; continue
        if s.startswith("|") and i + 1 < len(lines) and re.match(r"^\|?\s*:?-{2,}", lines[i + 1].strip()):
            flush()
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i]); i += 1
            out.append(_table(block, notes)); continue
        if s.startswith(">"):
            flush()
            block = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                block.append(lines[i].strip()[1:].strip()); i += 1
            out.append(f'<blockquote>{_inline(" ".join(block), notes)}</blockquote>'); continue
        if re.match(r"^[-*+]\s+", s) or re.match(r"^\d+[.)]\s+", s):
            flush()
            ordered = bool(re.match(r"^\d", s))
            tag = "ol" if ordered else "ul"
            items: list[str] = []
            pat = r"^\d+[.)]\s+" if ordered else r"^[-*+]\s+"
            while i < len(lines) and lines[i].strip():
                t = lines[i].strip()
                if re.match(pat, t):
                    items.append(re.sub(pat, "", t))
                elif items and lines[i].startswith((" ", "\t")):
                    items[-1] += " " + t
                else:
                    break
                i += 1
            out.append(f"<{tag}>" + "".join(f"<li>{_inline(x, notes)}</li>" for x in items) + f"</{tag}>")
            continue
        para.append(s); i += 1
    flush()
    if note_text:
        out.append('<section class="footnotes"><ol>')
        for key in sorted(note_text, key=lambda k: notes.get(k, 1e9)):
            out.append(f'<li id="fn-{key}">{_inline(note_text[key], {})}</li>')
        out.append("</ol></section>")
    return title, "\n".join(out), toc


CSS = """
:root{--bg:#fcfcfb;--surface:#ffffff;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--line:#e1e0d9;
--line2:#c3c2b7;--head:#f4f3ef;--zebra:#f9f9f7;--hover:#eef4fc;--accent:#2a78d6;--neg:#c23a3a;
--warn-bg:#fff4d6;--warn:#8a5a00;--breach-bg:#fde4e2;--breach:#a32020;--ok:#1a7f55;--code:#f1f0ec}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#141413;--surface:#1c1c1b;--ink:#ecebe6;
--ink2:#b8b6ae;--muted:#8a887f;--line:#2f2f2c;--line2:#45443f;--head:#242422;--zebra:#191918;--hover:#1e2a3a;
--accent:#6da7ec;--neg:#f08080;--warn-bg:#3a2f12;--warn:#f0c060;--breach-bg:#3d1b1b;--breach:#ff9a9a;--ok:#5fd0a0;--code:#262624}}
:root[data-theme="dark"]{--bg:#141413;--surface:#1c1c1b;--ink:#ecebe6;--ink2:#b8b6ae;--muted:#8a887f;--line:#2f2f2c;
--line2:#45443f;--head:#242422;--zebra:#191918;--hover:#1e2a3a;--accent:#6da7ec;--neg:#f08080;--warn-bg:#3a2f12;
--warn:#f0c060;--breach-bg:#3d1b1b;--breach:#ff9a9a;--ok:#5fd0a0;--code:#262624}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:64px}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",
Roboto,"Helvetica Neue",Arial,sans-serif;-webkit-font-smoothing:antialiased}
header.top{position:sticky;top:0;z-index:20;background:var(--surface);border-bottom:1px solid var(--line);
display:flex;align-items:center;gap:4px;padding:0 16px;height:48px;overflow-x:auto;white-space:nowrap}
header.top .brand{font-weight:650;margin-right:12px;color:var(--ink)}
header.top a{color:var(--ink2);text-decoration:none;padding:6px 10px;border-radius:6px;font-size:13px}
header.top a:hover{background:var(--head);color:var(--ink)}
header.top a.active{background:var(--head);color:var(--ink);font-weight:600}
header.top button{margin-left:auto;background:none;border:1px solid var(--line2);color:var(--ink2);
border-radius:6px;padding:4px 10px;font:inherit;font-size:12px;cursor:pointer}
.layout{display:grid;grid-template-columns:240px minmax(0,1fr);gap:32px;max-width:1440px;margin:0 auto;padding:0 24px}
nav.toc{position:sticky;top:64px;align-self:start;max-height:calc(100vh - 80px);overflow-y:auto;padding:24px 0;font-size:13px}
nav.toc .label{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:8px}
nav.toc a{display:block;color:var(--ink2);text-decoration:none;padding:3px 8px;border-left:2px solid transparent;line-height:1.35}
nav.toc a.l3{padding-left:20px;font-size:12px;color:var(--muted)}
nav.toc a:hover{color:var(--ink)}
nav.toc a.on{border-left-color:var(--accent);color:var(--ink)}
main{padding:24px 0 80px;min-width:0}
h1{font-size:26px;line-height:1.25;margin:8px 0 16px;letter-spacing:-.01em}
h2{font-size:20px;margin:40px 0 12px;padding-top:12px;border-top:1px solid var(--line)}
h3{font-size:16px;margin:28px 0 10px}
h4,h5,h6{font-size:14px;margin:20px 0 8px}
h2 .anchor,h3 .anchor,h4 .anchor{color:var(--muted);text-decoration:none;margin-left:-18px;width:18px;
display:inline-block;opacity:0;font-weight:400}
h2:hover .anchor,h3:hover .anchor,h4:hover .anchor{opacity:1}
p,ul,ol{max-width:980px}
ul,ol{padding-left:22px}
li{margin:4px 0}
a{color:var(--accent)}
code{font:12.5px/1.4 ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace;background:var(--code);
padding:1px 5px;border-radius:4px}
blockquote{margin:0 0 20px;padding:12px 16px;background:var(--head);border-left:3px solid var(--accent);
border-radius:0 6px 6px 0;max-width:980px}
.table-wrap{overflow:auto;max-height:640px;width:fit-content;max-width:100%;margin:12px 0 20px;border:1px solid var(--line);border-radius:8px;
background:var(--surface)}
table{border-collapse:separate;border-spacing:0;font-size:12.5px}
th,td{padding:6px 12px;border-bottom:1px solid var(--line);white-space:nowrap;vertical-align:top}
td.txt{white-space:normal;min-width:80px;max-width:420px}
td.txt:first-child{white-space:nowrap;max-width:none}
thead th{position:sticky;top:0;z-index:2;background:var(--head);color:var(--ink2);font-weight:600;
border-bottom:1px solid var(--line2);text-align:left}
th.num,td.num{text-align:right;font-variant-numeric:tabular-nums;font-feature-settings:"tnum"}
th:first-child,td:first-child{position:sticky;left:0;z-index:1;background:var(--surface);border-right:1px solid var(--line)}
thead th:first-child{z-index:3;background:var(--head)}
tbody tr:nth-child(even) td{background:var(--zebra)}
tbody tr:hover td{background:var(--hover)}
tbody tr:last-child td{border-bottom:0}
td.neg{color:var(--neg)}
td.empty{color:var(--muted)}
td.st-breach{color:var(--breach);font-weight:600}
td.st-warn{color:var(--warn);font-weight:600}
td.st-ok{color:var(--ok)}
figure{margin:16px 0 24px;background:#fcfcfb;border:1px solid var(--line);border-radius:8px;padding:12px;
max-width:1100px}
figure img{display:block;width:100%;height:auto}
sup.fn a{text-decoration:none;font-weight:600}
section.footnotes{margin-top:48px;padding-top:12px;border-top:1px solid var(--line);font-size:13px;color:var(--ink2)}
footer{color:var(--muted);font-size:12px;margin-top:48px}
@media (max-width:900px){.layout{grid-template-columns:minmax(0,1fr);padding:0 16px}nav.toc{display:none}
h1{font-size:22px;overflow-wrap:anywhere}li,p{overflow-wrap:anywhere}.table-wrap{max-height:none}}
@media print{header.top,nav.toc{display:none}.layout{display:block}.table-wrap{max-height:none;overflow:visible}
thead th,th:first-child,td:first-child{position:static}h2{break-after:avoid}figure,tr{break-inside:avoid}}
"""

JS = """
(function(){
  var root=document.documentElement, key='report-theme';
  try{var t=localStorage.getItem(key); if(t) root.setAttribute('data-theme',t);}catch(e){}
  var btn=document.getElementById('theme');
  if(btn) btn.onclick=function(){
    var dark=root.getAttribute('data-theme')==='dark'||(!root.getAttribute('data-theme')&&matchMedia('(prefers-color-scheme: dark)').matches);
    var n=dark?'light':'dark'; root.setAttribute('data-theme',n); try{localStorage.setItem(key,n);}catch(e){}
  };
  var links=[].slice.call(document.querySelectorAll('nav.toc a'));
  if(!('IntersectionObserver' in window)||!links.length) return;
  var map={}; links.forEach(function(a){map[a.getAttribute('href').slice(1)]=a;});
  var obs=new IntersectionObserver(function(es){es.forEach(function(e){
    if(e.isIntersecting){links.forEach(function(a){a.classList.remove('on');});
      var a=map[e.target.id]; if(a) a.classList.add('on');}});},{rootMargin:'-60px 0px -70% 0px'});
  Object.keys(map).forEach(function(id){var el=document.getElementById(id); if(el) obs.observe(el);});
})();
"""


def render_report(md_path: Path, embed: bool = True) -> Path:
    """Write ``<name>.html`` next to ``md_path`` and return its path."""
    md_path = Path(md_path)
    title, body, toc = md_to_html(md_path.read_text(encoding="utf-8"), md_path.parent, embed)
    present = {p.stem for p in md_path.parent.glob("*.md")}
    active = ' class="active"'
    nav = "".join(
        f'<a href="{stem}.html"{active if stem == md_path.stem else ""}>{label}</a>'
        for stem, label in REPORTS if stem in present or stem == md_path.stem)
    toc_html = "".join(f'<a class="l{lvl}" href="#{hid}">{html.escape(txt)}</a>' for lvl, hid, txt in toc)
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title or md_path.stem)}</title><style>{CSS}</style></head>
<body><header class="top"><span class="brand">Factor framework</span>{nav}<button id="theme" type="button">Theme</button></header>
<div class="layout"><nav class="toc"><div class="label">On this page</div>{toc_html}</nav>
<main>{body}<footer>Generated from {html.escape(md_path.name)}. Full tables in <code>tables/*.csv</code>.</footer></main></div>
<script>{JS}</script></body></html>
"""
    out = md_path.with_suffix(".html")
    out.write_text(doc, encoding="utf-8", newline="\n")
    return out


def render_all(out_dir: Path, embed: bool = True) -> list[Path]:
    return [render_report(p, embed) for p in sorted(Path(out_dir).glob("*.md"))]


if __name__ == "__main__":
    import sys
    for p in render_all(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("output")):
        print(f"-> {p}")
