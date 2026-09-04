"""Command-line interface for project-doctor."""
from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import sys
import webbrowser
from pathlib import Path

from . import __version__
from .checks import all_checks
from .model import SEVERITIES, Project
from .report import RENDERERS, render_html, render_terminal, supports_color
from .scanner import run

FAIL_LEVELS = {s: i for i, s in enumerate(SEVERITIES)}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="project-doctor",
        description="Scan a project or GitHub repository and report what is broken, "
                    "missing or risky.",
        epilog="examples:\n"
               "  project-doctor .\n"
               "  project-doctor --github psf/requests --format markdown -o report.md\n"
               "  project-doctor . --serve\n"
               "  project-doctor . --fail-on high    # for CI\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("path", nargs="?", default=".", help="local project directory (default: .)")
    p.add_argument("--github", metavar="OWNER/REPO",
                   help="scan a GitHub repository instead of a local path")
    p.add_argument("--branch", help="branch or tag to fetch with --github")
    p.add_argument("--clone", action="store_true",
                   help="use `git clone` instead of the tarball download")
    p.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"),
                   help="GitHub token for private repos (or set GITHUB_TOKEN)")
    p.add_argument("-f", "--format", choices=sorted(RENDERERS), default="terminal")
    p.add_argument("-o", "--output", metavar="FILE", help="write the report to a file")
    p.add_argument("--serve", action="store_true",
                   help="render HTML and open it in a local web server")
    p.add_argument("--port", type=int, default=8787, help="port for --serve (default 8787)")
    p.add_argument("--only", default="", metavar="IDS",
                   help="comma-separated check ids to run exclusively")
    p.add_argument("--skip", default="", metavar="IDS", help="comma-separated check ids to skip")
    p.add_argument("--offline", action="store_true", help="skip every check that needs network")
    p.add_argument("--ignore", action="append", default=[], metavar="GLOB",
                   help="extra path glob to ignore (repeatable)")
    p.add_argument("--fail-on", choices=list(SEVERITIES) + ["never"], default="never",
                   help="exit non-zero if any finding is at or above this severity")
    p.add_argument("--min-severity", choices=list(SEVERITIES), default="info",
                   help="hide findings below this severity")
    p.add_argument("-v", "--verbose", action="store_true", help="show every finding")
    p.add_argument("--no-color", action="store_true")
    p.add_argument("--list-checks", action="store_true", help="list available checks and exit")
    p.add_argument("--version", action="version", version=f"project-doctor {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_checks:
        for c in all_checks():
            tag = " (network)" if c.network else ""
            print(f"  {c.id:<10} {c.name}{tag}\n             {c.description}")
        return 0

    tmp_root: Path | None = None
    try:
        if args.github:
            from .fetch import FetchError, clone_github, fetch_github
            try:
                print(f"fetching {args.github} ...", file=sys.stderr)
                root = (clone_github(args.github, args.branch) if args.clone
                        else fetch_github(args.github, args.branch, args.token))
            except FetchError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            tmp_root = root.parent
            name = args.github
        else:
            root = Path(args.path).expanduser()
            if not root.is_dir():
                print(f"error: not a directory: {root}", file=sys.stderr)
                return 2
            name = None

        project = Project(root, extra_ignores=args.ignore)
        report = run(project,
                     only=args.only.split(","), skip=args.skip.split(","),
                     offline=args.offline)
        if name:
            report.project = name

        floor = FAIL_LEVELS[args.min_severity]
        if args.min_severity != "info":
            report.score_override = report.score()  # score the whole project, show a subset
            report.findings = [
                f for f in report.findings if FAIL_LEVELS.get(f.severity, 9) <= floor
            ]

        if args.serve:
            return serve(report, args.port)

        renderer = RENDERERS[args.format]
        if args.format == "terminal":
            color = supports_color() and not args.no_color and not args.output
            text = render_terminal(report, color=color, verbose=args.verbose)
        else:
            text = renderer(report)

        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
            print(f"wrote {args.output}", file=sys.stderr)
        else:
            try:
                print(text)
            except BrokenPipeError:  # piped into head/less and the reader closed
                os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
                return 0

        if args.fail_on != "never":
            threshold = FAIL_LEVELS[args.fail_on]
            if any(FAIL_LEVELS.get(f.severity, 9) <= threshold for f in report.findings):
                return 1
        return 0
    finally:
        if tmp_root is not None:
            shutil.rmtree(tmp_root, ignore_errors=True)


def serve(report, port: int) -> int:
    """Serve the HTML report on localhost and open a browser."""
    import http.server
    import socketserver

    page = render_html(report).encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *a):
            pass

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), Handler) as httpd:
        url = f"http://127.0.0.1:{port}/"
        print(f"report at {url}  (ctrl-c to stop)", file=sys.stderr)
        with contextlib.suppress(Exception):  # opening a browser is optional
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
