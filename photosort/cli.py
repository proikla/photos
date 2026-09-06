"""photosort CLI."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from photosort import __version__
from photosort.decision_log import ActionLogger
from photosort.metadata_store import (
    DEFAULT_METADATA_NAME,
    load_metadata,
    resolve_metadata_records,
    save_metadata,
)
from photosort.organizer import organize
from photosort.progress import Progress
from photosort.stats import (
    format_stats,
    matplotlib_available,
    open_with_default_app,
    plot_focal_lengths,
    prompt_yes_no,
)


def _setup_logging(*, verbose: bool, quiet: bool, log_file: Path | None) -> None:
    """
    - default: decisions go to log file only (progress covers stderr)
    - verbose: also echo INFO/DEBUG decisions to stderr
    - quiet: WARNING+ only
    """
    file_level = logging.DEBUG if verbose else logging.INFO
    if quiet:
        console_level = logging.WARNING
    elif verbose:
        console_level = logging.DEBUG
    else:
        console_level = logging.WARNING

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(console_level)
    console.setFormatter(fmt)
    root.addHandler(console)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(file_level)
        fh.setFormatter(fmt)
        root.addHandler(fh)


def cmd_organize(args: argparse.Namespace) -> int:
    source = Path(args.source)
    if not source.exists():
        print(f"error: source does not exist: {source}", file=sys.stderr)
        return 2

    # dest optional: omit → in-place sort under source
    dest = Path(args.dest) if args.dest is not None else source
    inplace = source.resolve() == dest.resolve()

    # Default is MOVE; --copy opts into non-destructive copy. --move is an
    # explicit no-op alias for the default (back-compat).
    move = not bool(getattr(args, "copy", False))

    log_file = Path(args.log) if args.log else dest / "photosort.log"
    actions_log = (
        Path(args.actions_log)
        if getattr(args, "actions_log", None)
        else dest / "photosort_actions.log"
    )
    write_tech_log = not (args.dry_run and not args.log)
    _setup_logging(
        verbose=args.verbose,
        quiet=args.quiet,
        log_file=log_file if write_tech_log else None,
    )
    progress = Progress(quiet=args.quiet)
    mode_label = "MOVE" if move else "COPY"
    if not args.quiet:
        if inplace:
            progress.status(
                f"in-place sort under {source} ({'move' if move else 'copy'})"
            )
        progress.status(
            f"photosort organize  source={source}  dest={dest}  "
            f"depth={args.depth}  mode={'move' if move else 'copy'}"
            + ("  dry-run" if args.dry_run else "")
            + ("  in-place" if inplace else "")
        )
        if write_tech_log:
            progress.status(f"technical log: {log_file}")
        progress.status(f"actions log: {actions_log}")
    else:
        print(f"actions log: {actions_log}")

    action_logger = ActionLogger(actions_log)
    try:
        action_logger.write_header(
            mode=mode_label,
            source=source,
            dest=dest,
            depth=args.depth,
            dry_run=args.dry_run,
        )
        result = organize(
            source,
            dest,
            depth=args.depth,
            move=move,
            dry_run=args.dry_run,
            recursive=not args.no_recursive,
            collect_metadata=True,
            progress=progress,
            action_logger=action_logger,
        )
        action_logger.write_footer(
            summary=(
                f"done  copied/moved={result.copied + result.moved} "
                f"renamed={result.renamed} skipped_dup={result.skipped} "
                f"already_sorted={result.already_sorted}"
            )
        )
    finally:
        action_logger.close()

    meta_path = Path(args.metadata) if args.metadata else dest / DEFAULT_METADATA_NAME
    if result.metadata and not args.dry_run:
        # Merge with existing inventory by content_hash
        existing = {r.get("content_hash"): r for r in load_metadata(meta_path) if r.get("content_hash")}
        for r in result.metadata:
            existing[r["content_hash"]] = r
        save_metadata(list(existing.values()), meta_path)
        print(f"metadata: {meta_path}")

    print(f"decisions: {len(result.decisions)}")
    print(f"  copied/moved: {result.copied + result.moved}")
    print(f"  renamed:      {result.renamed}")
    print(f"  skipped dup:  {result.skipped}")
    print(f"  already sorted: {result.already_sorted}")
    print(f"hashes before:  {len(result.hashes_before)}")
    print(f"hashes after:   {len(result.hashes_after)}")

    # Unique content inventory: after should equal before ∪ newly placed.
    # skipped_duplicate / skipped_already_sorted do not add new hashes.
    # For in-place moves, hashes_after must equal hashes_before (all unique
    # content preserved; already_sorted is not a loss).
    newly = {
        d.content_hash
        for d in result.decisions
        if d.action not in ("skipped_duplicate", "skipped_already_sorted")
    }
    if inplace:
        expected = set(result.hashes_before)
    else:
        expected = result.hashes_before | newly
    if not args.dry_run and result.hashes_after != expected:
        missing = expected - result.hashes_after
        extra = result.hashes_after - expected
        print("WARNING: hash inventory mismatch!", file=sys.stderr)
        if missing:
            print(f"  missing after: {len(missing)}", file=sys.stderr)
        if extra:
            print(f"  unexpected after: {len(extra)}", file=sys.stderr)
        return 1
    print("inventory: OK (unique content preserved)")
    print(f"actions log: {actions_log}")
    if args.dry_run:
        print("(dry-run: no files written)")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    path = Path(args.path)
    progress = Progress(quiet=args.quiet)
    try:
        records, source = resolve_metadata_records(
            path,
            rescan=args.rescan,
            use_cache=args.cache,
            recursive=not args.no_recursive,
            progress=progress,
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if not records:
        print(
            f"error: no photo metadata found under {path}\n"
            f"hint: pass your library folder, e.g. photosort stats ./library\n"
            f"      or run organize first, then photosort stats ./library",
            file=sys.stderr,
        )
        return 2

    if args.save is not None:
        if isinstance(args.save, str):
            save_path = Path(args.save)
        elif path.is_dir():
            save_path = path / DEFAULT_METADATA_NAME
        else:
            save_path = path.parent / DEFAULT_METADATA_NAME
        save_metadata(records, save_path)
        print(f"metadata saved: {save_path}")

    print(f"source: {source}")
    print(format_stats(records, lens_filter=args.lens), end="")

    # Chart path: explicit --chart, else next to library / cwd
    if args.chart:
        chart_path = Path(args.chart)
    elif path.is_dir():
        chart_path = path / "photosort_focal_lengths.png"
    else:
        chart_path = path.parent / "photosort_focal_lengths.png"

    want_chart = False
    if args.no_chart_prompt:
        want_chart = bool(args.chart) or args.open_chart
    elif args.open_chart or args.chart:
        want_chart = True
    elif not args.quiet and sys.stdin.isatty() and sys.stdout.isatty():
        # After scan: offer to draw + open
        has_focal = any(r.get("focal_length_mm") is not None for r in records)
        if has_focal:
            want_chart = prompt_yes_no(
                "Show focal-length chart (X=mm min→max, Y=photos)?",
                default_yes=True,
            )
        else:
            print("(no focal-length data — chart skipped)", file=sys.stderr)

    if want_chart:
        if not matplotlib_available():
            print(
                "error: matplotlib is required for charts\n"
                "  pip install matplotlib",
                file=sys.stderr,
            )
            return 2
        ok = plot_focal_lengths(records, chart_path, lens=args.lens)
        if not ok:
            print("warning: could not write chart (no focal-length data?)", file=sys.stderr)
        else:
            print(f"chart written: {chart_path}")
            if not args.no_open:
                if open_with_default_app(chart_path):
                    print(f"opened: {chart_path}")
                else:
                    print(
                        f"could not auto-open; open manually: {chart_path}",
                        file=sys.stderr,
                    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="photosort",
        description="Sort photos into date folders with content-hash duplicate safety.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    org = sub.add_parser(
        "organize",
        help="Sort photos by date (dest optional → in-place under source)",
    )
    org.add_argument("source", help="Source file or directory")
    org.add_argument(
        "dest",
        nargs="?",
        default=None,
        help="Destination root (default: same as source — in-place YYYY/MM)",
    )
    org.add_argument(
        "--depth",
        choices=("month", "day"),
        default="month",
        help="Folder depth: YYYY/MM (default) or YYYY/MM/DD",
    )
    org.add_argument(
        "--copy",
        action="store_true",
        help="Copy files instead of moving (default is MOVE)",
    )
    org.add_argument(
        "--move",
        action="store_true",
        help="Move files (default; kept as explicit alias for back-compat)",
    )
    org.add_argument("--dry-run", action="store_true", help="Log actions without writing")
    org.add_argument("--no-recursive", action="store_true", help="Do not scan subfolders")
    org.add_argument(
        "--log",
        help="Technical decision log file (default: DEST/photosort.log)",
    )
    org.add_argument(
        "--actions-log",
        help="Human-readable actions log (default: DEST/photosort_actions.log)",
    )
    org.add_argument(
        "--metadata",
        help=f"JSON metadata inventory path (default: DEST/{DEFAULT_METADATA_NAME})",
    )
    org.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print every decision to stderr (also more detail in the log)",
    )
    org.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Hide progress; only print the final summary",
    )
    org.set_defaults(func=cmd_organize)

    st = sub.add_parser(
        "stats",
        help="Show lens / focal-length stats from a library folder or metadata JSON",
    )
    st.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Library folder (scans photos) or photosort_metadata.json (default: .)",
    )
    st.add_argument(
        "--rescan",
        action="store_true",
        help="Force a full EXIF walk of all subfolders (default for directories)",
    )
    st.add_argument(
        "--cache",
        action="store_true",
        help="Use DIR/photosort_metadata.json instead of walking the tree",
    )
    st.add_argument(
        "--no-recursive",
        action="store_true",
        help="When scanning a folder, do not descend into subfolders",
    )
    st.add_argument(
        "--save",
        nargs="?",
        const=True,
        default=None,
        metavar="FILE",
        help=f"Write/update metadata JSON (default path: DIR/{DEFAULT_METADATA_NAME})",
    )
    st.add_argument("--lens", help="Filter focal lengths to this lens name")
    st.add_argument(
        "--chart",
        help="Write focal-length bar chart PNG to this path "
        "(default after prompt: DIR/photosort_focal_lengths.png)",
    )
    st.add_argument(
        "--open-chart",
        action="store_true",
        help="Build the chart and open it (skip Y/n prompt)",
    )
    st.add_argument(
        "--no-chart-prompt",
        action="store_true",
        help="Do not ask to show a chart after scanning",
    )
    st.add_argument(
        "--no-open",
        action="store_true",
        help="Write the chart PNG but do not open the default viewer",
    )
    st.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Reserved for extra detail (progress is on by default)",
    )
    st.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Hide progress; only print the stats report",
    )
    st.set_defaults(func=cmd_stats)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
