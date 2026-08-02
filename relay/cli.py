"""RELAY command-line interface (SRS FR-25)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config
from .ingest.campaign import list_sheets
from .pipeline import run_pipeline
from .report.crosscheck import compare, parse_reference
from .report.generator import build_report


def _pick_port(host: str, first: int, tries: int = 20) -> int:
    """The first free port at or after `first`.

    A double-clicked launcher has no console to read a traceback from, and
    "address already in use" is the likeliest thing to go wrong on a desktop
    where RELAY is already running in another window.
    """
    import socket

    bind = "127.0.0.1" if host == "0.0.0.0" else host
    for port in range(first, first + tries):
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((bind, port))
                return port
            except OSError:
                continue
    raise SystemExit(f"no free port between {first} and {first + tries - 1}")


def _open_when_ready(host: str, port: int, url: str, timeout: float = 30.0) -> None:
    """Open a browser once the server actually answers, in the background.

    Opening it before uvicorn is listening shows the user a connection error on
    the very first thing they see, so this waits for the socket instead of
    guessing at a delay.
    """
    import socket
    import threading
    import time
    import webbrowser

    connect = "127.0.0.1" if host == "0.0.0.0" else host

    def wait():
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with socket.create_connection((connect, port), timeout=0.5):
                    webbrowser.open(url)
                    return
            except OSError:
                time.sleep(0.25)

    threading.Thread(target=wait, daemon=True, name="open-browser").start()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="relay", description="Sponsored-content reporting")
    sub = p.add_subparsers(dest="cmd", required=True)

    sheets = sub.add_parser("sheets", help="List tabs in a campaign workbook")
    sheets.add_argument("campaign")

    run = sub.add_parser("run", help="Match + generate a sponsor report")
    run.add_argument("--campaign", required=True)
    run.add_argument("--sheet", required=True, help="Month tab name, e.g. April")
    run.add_argument("--brand", required=True)
    run.add_argument("--insights", action="append", metavar="EXPORT",
                     help="Facebook Business Suite content export (.csv/.xlsx) — "
                          "exact Reach/Views per post. Repeat once per file.")
    run.add_argument("--ig-insights", action="append", metavar="EXPORT",
                     help="Instagram content export (.csv/.xlsx). Joined by post "
                          "shortcode, so it needs no browser session at all.")
    run.add_argument("--out", help="Output .xlsx path")
    run.add_argument("--reference", help="Existing hand-made report to cross-check against")
    run.add_argument("--collect-x", action="store_true",
                     help="Fill X impressions from public post pages (no login)")
    run.add_argument("--resolve-fb", action="store_true",
                     help="Identify every unresolved FB post by its post id via the "
                          "Meta session, and fill it from the export")
    run.add_argument("--collect-ig", action="store_true",
                     help="Fill missing Instagram cells from post pages (Meta session)")
    run.add_argument("--dry-run", action="store_true",
                     help="Collectors log intended visits without touching the network")

    login = sub.add_parser("login", help="One-time interactive login for collectors")
    login.add_argument("target", choices=["meta"])

    serve = sub.add_parser("serve", help="Start the dashboard")
    serve.add_argument("--port", type=int, default=8501)
    # Default stays 0.0.0.0 for the container, whose published port needs it.
    # The Windows launcher passes 127.0.0.1: binding every interface makes
    # Windows Defender pop a firewall prompt the first time, which is alarming
    # for a double-click user and buys nothing on a single desktop.
    serve.add_argument("--host", default="0.0.0.0",
                       help="interface to bind (default: every interface)")
    serve.add_argument("--auto-port", action="store_true",
                       help="if --port is taken, use the next free one")
    serve.add_argument("--open", action="store_true", dest="open_browser",
                       help="open the dashboard in a browser once it is listening")

    args = p.parse_args(argv)

    if args.cmd == "login":
        from .collectors.browser import login_meta
        login_meta()
        return 0

    if args.cmd == "sheets":
        for name in list_sheets(args.campaign):
            print(name)
        return 0

    if args.cmd == "serve":
        import uvicorn
        from .web.app import app
        port = _pick_port(args.host, args.port) if args.auto_port else args.port
        url = f"http://{'localhost' if args.host in ('0.0.0.0', '127.0.0.1') else args.host}:{port}/"
        print(f"RELAY dashboard: {url}")
        if args.open_browser:
            _open_when_ready(args.host, port, url)
        uvicorn.run(app, host=args.host, port=port)
        return 0

    result = run_pipeline(
        args.campaign, args.sheet, args.brand,
        insights_paths=args.insights, ig_insights_paths=args.ig_insights,
    )
    if args.insights or args.ig_insights:
        index = result.insights
        n_filled = sum(1 for r in result.rows for s in ("fb1", "fb2", "fb3", "ig")
                       if r.cells[s].provenance == "collected")
        print(f"insights exports: {len(index):,} posts loaded from "
              f"{len(index.files)} file(s); {n_filled} cells filled exactly")
    if args.collect_x or args.resolve_fb or args.collect_ig:
        from . import store
        from .collectors.base import Pacer
        from .collectors.runner import collect_instagram, collect_x, resolve_facebook
        pacer = Pacer(dry_run=args.dry_run)
        persist = None
        if not args.dry_run:
            # resume: inherit checkpointed values from a previous run of the
            # same inputs, then checkpoint this run's cells as they land
            inputs = {"campaign": args.campaign, "sheet": args.sheet, "brand": args.brand}
            prev_id = store.find_resumable_run(inputs)
            if prev_id:
                restored = store.hydrate_cells(result, store.load_cells(prev_id))
                if restored:
                    print(f"resumed: {restored} previously collected cells restored")
            db_id = store.save_run(result, inputs)

            def persist(run, row_idx, slot, cell):
                store.update_cell(db_id, row_idx, slot, cell)
        if args.collect_x:
            print(f"X collector filled {collect_x(result, pacer, persist=persist)} cells")
        if args.resolve_fb:
            print(f"Facebook resolved {resolve_facebook(result, pacer=pacer, persist=persist)} cells")
        if args.collect_ig:
            print(f"IG collector filled {collect_instagram(result, pacer=pacer, persist=persist)} cells")
    cov = result.coverage()
    print(f"{args.brand} {args.sheet}: {len(result.rows)} rows")
    for slot, frac in cov.items():
        print(f"  {slot}: {frac:.0%} of linked cells filled")
    for issue in result.issues:
        where = f" {issue.where}" if issue.where else ""
        print(f"  ! {issue.file}{where}: {issue.reason}", file=sys.stderr)

    out = Path(args.out) if args.out else config.OUTPUT_DIR / f"{args.brand} ({args.sheet}).xlsx"
    build_report(result, out)
    print(f"report written: {out}")

    if args.reference:
        cc = compare(result, parse_reference(args.reference, args.sheet))
        s = cc.summary()
        print(f"cross-check vs {args.reference}: {s['equal']}/{s['cells']} equal "
              f"({s['accuracy']:.1%})")
        for d in s["differs"]:
            print(f"  differs row {d.row_no} {d.slot}: relay={d.generated} ref={d.reference}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
