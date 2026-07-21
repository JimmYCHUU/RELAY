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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="relay", description="Sponsored-content reporting")
    sub = p.add_subparsers(dest="cmd", required=True)

    sheets = sub.add_parser("sheets", help="List tabs in a campaign workbook")
    sheets.add_argument("campaign")

    run = sub.add_parser("run", help="Match + generate a sponsor report")
    run.add_argument("--campaign", required=True)
    run.add_argument("--sheet", required=True, help="Month tab name, e.g. April")
    run.add_argument("--brand", required=True)
    run.add_argument("--mainpage")
    run.add_argument("--subpage")
    run.add_argument("--insta")
    run.add_argument("--out", help="Output .xlsx path")
    run.add_argument("--reference", help="Existing hand-made report to cross-check against")
    run.add_argument("--collect-x", action="store_true",
                     help="Fill X impressions from public post pages (no login)")
    run.add_argument("--collect-fb", action="store_true",
                     help="Fill missing FB cells via Meta Business Suite session")
    run.add_argument("--collect-ig", action="store_true",
                     help="Fill missing Instagram cells from post pages (Meta session)")
    run.add_argument("--k", type=float, default=None,
                     help="Pin the reactions multiplier for estimates (70-150); "
                          "default: randomized per cell")
    run.add_argument("--dry-run", action="store_true",
                     help="Collectors log intended visits without touching the network")

    login = sub.add_parser("login", help="One-time interactive login for collectors")
    login.add_argument("target", choices=["meta"])

    serve = sub.add_parser("serve", help="Start the dashboard")
    serve.add_argument("--port", type=int, default=8501)

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
        uvicorn.run(app, host="0.0.0.0", port=args.port)
        return 0

    result = run_pipeline(
        args.campaign, args.sheet, args.brand,
        mainpage_path=args.mainpage, subpage_path=args.subpage, insta_path=args.insta,
    )
    if args.collect_x or args.collect_fb or args.collect_ig:
        from .collectors.base import Pacer
        from .collectors.runner import collect_facebook, collect_instagram, collect_x
        pacer = Pacer(dry_run=args.dry_run)
        if args.collect_x:
            print(f"X collector filled {collect_x(result, pacer)} cells")
        if args.collect_fb:
            print(f"FB collector filled {collect_facebook(result, args.k, pacer)} cells")
        if args.collect_ig:
            print(f"IG collector filled {collect_instagram(result, args.k, pacer)} cells")
    cov = result.coverage()
    print(f"{args.brand} {args.sheet}: {len(result.rows)} rows")
    for slot, frac in cov.items():
        print(f"  {slot}: {frac:.0%} of linked cells filled")
    for issue in result.issues:
        print(f"  ! {issue.file} row {issue.row}: {issue.reason}", file=sys.stderr)

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
