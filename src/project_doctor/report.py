"""Renderers: terminal, JSON, Markdown, HTML."""
from __future__ import annotations

import html
import json
import os
import sys
from datetime import datetime, timezone

from .model import SEVERITIES, Report

ANSI = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
    "critical": "\033[97;41m", "high": "\033[31m", "medium": "\033[33m",
    "low": "\033[36m", "info": "\033[90m", "good": "\033[32m",
}
BULLET = "\u2022"
LABEL = {"critical": "CRIT", "high": "HIGH", "medium": "MED ", "low": "LOW ", "info": "INFO"}
HEX = {"critical": "#B3202B", "high": "#C4622D", "medium": "#A88300",
       "low": "#4A6FA5", "info": "#6B7280"}


def supports_color(stream=sys.stdout) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return bool(getattr(stream, "isatty", lambda: False)())


def render_terminal(report: Report, color: bool = True, verbose: bool = False) -> str:
    def c(key: str, text: str) -> str:
        return f"{ANSI[key]}{text}{ANSI['reset']}" if color else text

    out: list[str] = []
    counts = report.counts()
    score = report.score()
    out.append("")
    out.append(c("bold", f"  Project Doctor  {report.project}"))
    out.append(c("dim", f"  {report.root}"))
    out.append("")

    bar_key = "good" if score >= 80 else ("medium" if score >= 60 else "high")
    filled = round(score / 5)
    bar = "\u2588" * filled + "\u2591" * (20 - filled)
    out.append(f"  Health {c(bar_key, bar)}  {c('bold', str(score))}/100  grade {report.grade()}")
    out.append("")

    summary = "  " + "   ".join(
        c(s, f"{LABEL[s].strip().lower()} {counts[s]}") for s in SEVERITIES if counts[s]
    )
    out.append(summary.rstrip() if summary.strip() else c("good", "  No issues found."))
    out.append("")

    limit = None if verbose else 6
    for severity, group in report.by_severity():
        shown = group if limit is None else group[:limit]
        out.append(c(severity, f"  {severity.upper()}  ({len(group)})"))
        for f in shown:
            loc = f.location()
            head = f"    {c(severity, BULLET)} {f.title}"
            if loc:
                head += c("dim", f"  [{loc}]")
            out.append(head)
            if f.detail:
                out.append(c("dim", f"      {f.detail}"))
            if f.fix:
                out.append(f"      {c('good', 'fix:')} {f.fix}")
        if limit is not None and len(group) > limit:
            out.append(c("dim", f"    ... {len(group) - limit} more (use --verbose)"))
        out.append("")

    if report.stats:
        bits = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in report.stats.items())
        out.append(c("dim", f"  {bits}"))
    for note in report.errors:
        out.append(c("dim", f"  note: {note}"))
    out.append(c("dim", f"  scanned in {report.duration:.2f}s"))
    out.append("")
    return "\n".join(out)


def render_json(report: Report) -> str:
    return json.dumps(report.to_dict(), indent=2)


def render_markdown(report: Report) -> str:
    counts = report.counts()
    lines = [
        f"# Project Doctor report: {report.project}",
        "",
        f"**Health score: {report.score()}/100 (grade {report.grade()})**",
        "",
        "| Severity | Count |",
        "| --- | --- |",
    ]
    for s in SEVERITIES:
        lines.append(f"| {s} | {counts[s]} |")
    lines.append("")
    for severity, group in report.by_severity():
        lines.append(f"## {severity.capitalize()} ({len(group)})")
        lines.append("")
        for f in group:
            loc = f" — `{f.location()}`" if f.location() else ""
            lines.append(f"- **{f.title}**{loc}")
            if f.detail:
                lines.append(f"  - {f.detail}")
            if f.fix:
                lines.append(f"  - _Fix:_ {f.fix}")
        lines.append("")
    lines.append(f"_Scanned in {report.duration:.2f}s by project-doctor._")
    return "\n".join(lines)


CSS = """
:root{
  --paper:#FBFBFC; --ink:#15181C; --muted:#5C636D; --rule:#E3E5E9;
  --crit:#B3202B; --high:#C4622D; --med:#A88300; --low:#4A6FA5; --info:#6B7280;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);
  font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:40px 24px 80px;display:grid;
  grid-template-columns:260px 1fr;gap:48px;align-items:start}
header{grid-column:1/-1;border-bottom:2px solid var(--ink);padding-bottom:16px;margin-bottom:8px}
h1{font-family:var(--mono);font-size:20px;font-weight:600;margin:0 0 4px;letter-spacing:-.02em}
.path{font-family:var(--mono);font-size:12.5px;color:var(--muted);word-break:break-all}
aside{position:sticky;top:40px}
.score{font-family:var(--mono);font-size:64px;line-height:1;font-weight:600;letter-spacing:-.04em}
.score span{font-size:20px;color:var(--muted);font-weight:400}
.grade{font-family:var(--mono);font-size:13px;color:var(--muted);margin-top:6px}
.dist{display:flex;height:8px;margin:20px 0 14px;overflow:hidden;background:var(--rule)}
.dist i{display:block}
.tally{list-style:none;padding:0;margin:0;font-family:var(--mono);font-size:13px}
.tally li{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--rule)}
.tally b{font-weight:600}
.meta{margin-top:22px;font-size:12.5px;color:var(--muted);font-family:var(--mono);line-height:1.9}
section h2{font-family:var(--mono);font-size:13px;font-weight:600;margin:34px 0 10px;
  padding-bottom:6px;border-bottom:1px solid var(--rule)}
section:first-of-type h2{margin-top:0}
.f{padding:14px 0 14px 16px;border-left:3px solid var(--rule);border-bottom:1px solid var(--rule)}
.f h3{font-size:15px;font-weight:600;margin:0 0 4px}
.f .loc{font-family:var(--mono);font-size:12px;color:var(--muted);margin-bottom:6px;word-break:break-all}
.f p{margin:0 0 6px;color:var(--muted);font-size:14px;max-width:68ch}
.f .fix{color:var(--ink);font-size:14px;max-width:68ch}
.f .fix b{font-weight:600}
.f code{font-family:var(--mono);font-size:12.5px;background:#F0F1F3;padding:1px 4px}
.clean{padding:40px 0;font-family:var(--mono)}
footer{grid-column:1/-1;margin-top:48px;padding-top:14px;border-top:1px solid var(--rule);
  font-family:var(--mono);font-size:12px;color:var(--muted)}
@media (max-width:820px){.wrap{grid-template-columns:1fr;gap:28px}aside{position:static}}
@media (prefers-color-scheme:dark){
  :root{--paper:#111317;--ink:#E9EAEC;--muted:#969CA6;--rule:#282C33;
        --crit:#E4646E;--high:#E08A4E;--med:#D4AE2A;--low:#7FA3D6;--info:#8B929C}
  .f code{background:#1C1F25}
}
"""


def render_html(report: Report) -> str:
    counts = report.counts()
    score = report.score()
    total = sum(counts.values()) or 1
    e = html.escape

    dist = "".join(
        f'<i style="width:{counts[s] / total * 100:.2f}%;background:{HEX[s]}"></i>'
        for s in SEVERITIES if counts[s]
    ) or '<i style="width:100%;background:#3E8E5A"></i>'

    tally = "".join(
        f'<li><span style="color:{HEX[s]}">{s}</span><b>{counts[s]}</b></li>'
        for s in SEVERITIES
    )

    body = []
    if not report.findings:
        body.append('<div class="clean">Nothing to report. This project passes every check.</div>')
    for severity, group in report.by_severity():
        body.append(f'<section><h2 style="color:{HEX[severity]}">'
                    f'{severity} ({len(group)})</h2>')
        for f in group:
            loc = f'<div class="loc">{e(f.location())}</div>' if f.location() else ""
            detail = f"<p>{e(f.detail)}</p>" if f.detail else ""
            fix = f'<div class="fix"><b>Fix</b> {e(f.fix)}</div>' if f.fix else ""
            body.append(
                f'<div class="f" style="border-left-color:{HEX[severity]}">'
                f"<h3>{e(f.title)}</h3>{loc}{detail}{fix}</div>"
            )
        body.append("</section>")

    meta = "<br>".join(
        f"{e(str(k).replace('_', ' '))}: {e(str(v))}" for k, v in report.stats.items()
    )
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Project Doctor: {e(report.project)}</title>
<style>{CSS}</style></head><body>
<div class="wrap">
<header>
  <h1>{e(report.project)}</h1>
  <div class="path">{e(report.root)}</div>
</header>
<aside>
  <div class="score">{score}<span>/100</span></div>
  <div class="grade">grade {report.grade()}</div>
  <div class="dist">{dist}</div>
  <ul class="tally">{tally}</ul>
  <div class="meta">{meta}<br>scanned {stamp}<br>{report.duration:.2f}s</div>
</aside>
<main>{''.join(body)}</main>
<footer>Generated by project-doctor. Findings are heuristics: read the fix, then decide.</footer>
</div></body></html>"""


RENDERERS = {
    "terminal": render_terminal,
    "json": render_json,
    "markdown": render_markdown,
    "html": render_html,
}
