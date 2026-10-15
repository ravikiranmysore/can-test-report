"""Write the HTML report and a JUnit XML file."""
from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

CSS = """
body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:2rem auto;max-width:960px;color:#1d2430;padding:0 1rem}
h1{margin-bottom:.2rem} .meta{color:#5b6573;margin-bottom:1.5rem}
.cards{display:flex;gap:1rem;margin-bottom:1.5rem}
.card{flex:1;border:1px solid #d9dee5;border-radius:8px;padding:.8rem 1rem}
.card b{display:block;font-size:1.8rem}
.pass{color:#1a7f37} .fail{color:#c62828}
table{border-collapse:collapse;width:100%} th,td{text-align:left;padding:.55rem .6rem;border-bottom:1px solid #e6e9ee;vertical-align:top}
th{background:#f4f6f9}
.badge{display:inline-block;padding:.1rem .55rem;border-radius:999px;font-weight:600;font-size:.8rem;color:#fff}
.badge.pass{background:#1a7f37;color:#fff} .badge.fail{background:#c62828;color:#fff}
details{margin-top:.4rem} summary{cursor:pointer;color:#34506e}
ul{margin:.3rem 0 0 1rem;padding:0} code{background:#f1f3f6;padding:0 .25rem;border-radius:3px}
svg{display:block;margin-top:.4rem;background:#fafbfc;border:1px solid #e6e9ee;border-radius:4px}
"""


def _plot_svg(plot, width=360, height=70) -> str:
    samples = plot["samples"]
    step = max(1, len(samples) // 400)
    pts = samples[::step]
    t0, t1 = pts[0][0], pts[-1][0] or 1.0
    values = [v for _, v in pts] + [plot["lo"], plot["hi"]]
    vmin, vmax = min(values), max(values)
    span = (vmax - vmin) or 1.0

    def x(t):
        return 4 + (t - t0) / ((t1 - t0) or 1.0) * (width - 8)

    def y(v):
        return height - 4 - (v - vmin) / span * (height - 8)

    line = " ".join(f"{x(t):.1f},{y(v):.1f}" for t, v in pts)
    out = [f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="signal plot">']
    for bound in (plot["lo"], plot["hi"]):
        out.append(f'<line x1="0" x2="{width}" y1="{y(bound):.1f}" y2="{y(bound):.1f}" stroke="#c62828" stroke-dasharray="4 3" stroke-width="1"/>')
    out.append(f'<polyline fill="none" stroke="#2c6fbb" stroke-width="1.5" points="{line}"/>')
    for t in plot["bad"][:50]:
        out.append(f'<circle cx="{x(t):.1f}" cy="{height / 2:.1f}" r="3" fill="#c62828"/>')
    out.append("</svg>")
    return "".join(out)


def write_html(results, log, log_name, path) -> None:
    passed = sum(r.status == "PASS" for r in results)
    failed = len(results) - passed
    rows = []
    for r in results:
        cls = r.status.lower()
        extra = ""
        if r.failures:
            items = "".join(f"<li>{html.escape(f)}</li>" for f in r.failures)
            extra += f"<details open><summary>Failures</summary><ul>{items}</ul></details>"
        if r.plot:
            extra += _plot_svg(r.plot)
        rows.append(
            f"<tr><td><b>{html.escape(r.rule_id)}</b></td>"
            f"<td>{html.escape(r.description)}<br><small><code>{r.rtype}</code></small></td>"
            f'<td><span class="badge {cls}">{r.status}</span></td>'
            f"<td>{html.escape(r.summary)}{extra}</td></tr>"
        )
    verdict = "PASS" if failed == 0 else "FAIL"
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>CAN test report</title><style>{CSS}</style></head><body>
<h1>CAN test report: <span class="{verdict.lower()}">{verdict}</span></h1>
<div class="meta">Log: <code>{html.escape(log_name)}</code> &middot; {log.total_frames} frames over {log.duration:.1f} s
&middot; generated {datetime.now().strftime('%Y-%m-%d %H:%M')}
&middot; unknown IDs: {log.unknown_frames} &middot; undecodable frames: {log.undecodable_frames}</div>
<div class="cards">
<div class="card"><b>{len(results)}</b>Requirements</div>
<div class="card"><b class="pass">{passed}</b>Passed</div>
<div class="card"><b class="fail">{failed}</b>Failed</div></div>
<table><tr><th>ID</th><th>Requirement</th><th>Result</th><th>Evidence</th></tr>
{''.join(rows)}</table></body></html>"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(page, encoding="utf-8")


def write_junit(results, log_name, path) -> None:
    failed = sum(r.status == "FAIL" for r in results)
    suite = ET.Element("testsuite", name="can-requirements", tests=str(len(results)),
                       failures=str(failed), errors="0")
    for r in results:
        case = ET.SubElement(suite, "testcase", classname=log_name, name=f"{r.rule_id} {r.description}")
        if r.status == "FAIL":
            fail = ET.SubElement(case, "failure", message=r.summary)
            fail.text = "\n".join(r.failures)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)
