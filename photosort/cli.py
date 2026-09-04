"""photosort CLI."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from photosort import __version__
from photosort.metadata_store import load_metadata, save_metadata
from photosort.organizer import organize
from photosort.stats import format_stats, maybe_plot_focal_lengths, stats_from_file


def _setup_logging(verbose: bool, log_file: Path | None) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )


def cmd_organize(args: argparse.Namespace) -> int:
    source = Path(args.source)
    dest = Path(args.dest)
    if not source.exists():
        print(f"error: source does not exist: {source}", file=sys.stderr)
        return 2

    log_file = Path(args.log) if args.log else dest / "photosort.log"
    _setup_logging(args.verbose, None if args.dry_run and not args.log else log_file)

    result = organize(
        source,
        dest,
        depth=args.depth,
        move=args.move,
        dry_run=args.dry_run,
        recursive=not args.no_recursive,
        collect_metadata=True,
    )

    meta_path = Path(args.metadata) if args.metadata else dest / "photosort_metadata.json"
    if result.metadata and not args.dry_run:
        # Merge with existing inventory by content_hash
        existing = {r.get("content_hash"): r for r in load_metadata(meta_path) if r.get("content_hash")}
        for r in result.metadata:
            existing[r["content_hash"]] = r
        save_metadata(list(existing.values()), meta_path)

    print(f"decisions: {len(result.decisions)}")
    print(f"  copied/moved: {result.copied + result.moved}")
    print(f"  renamed:      {result.renamed}")
    print(f"  skipped dup:  {result.skipped}")
    print(f"hashes before:  {len(result.hashes_before)}")
    print(f"hashes after:   {len(result.hashes_after)}")

    # Unique content inventory: after should equal before ∪ newly placed
    newly = {d.content_hash for d in result.decisions if d.action != "skipped_duplicate"}
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
    if args.dry_run:
        print("(dry-run: no files written)")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    meta_path = Path(args.metadata)
    if not meta_path.exists():
        print(f"error: metadata file not found: {meta_path}", file=sys.stderr)
        return 2
    records = load_metadata(meta_path)
    print(format_stats(records, lens_filter=args.lens), end="")
    if args.chart:
        ok = maybe_plot_focal_lengths(records, Path(args.chart), lens=args.lens)
        if not ok:
            print(
                "warning: could not write chart (need matplotlib and focal-length data)",
                file=sys.stderr,
            )
        else:
            print(f"chart written: {args.chart}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="photosort",
        description="Sort photos into date folders with content-hash duplicate safety.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    org = sub.add_parser("organize", help="Sort photos from source into dest by date")
    org.add_argument("source", help="Source file or directory")
    org.add_argument("dest", help="Destination root directory")
    org.add_argument(
        "--depth",
        choices=("month", "day"),
        default="month",
        help="Folder depth: YYYY/MM (default) or YYYY/MM/DD",
    )
    org.add_argument(
        "--move",
        action="store_true",
        help="Move files instead of copying (default is non-destructive copy)",
    )
    org.add_argument("--dry-run", action="store_true", help="Log actions without writing")
    org.add_argument("--no-recursive", action="store_true", help="Do not scan subfolders")
    org.add_argument("--log", help="Decision log file (default: DEST/photosort.log)")
    org.add_argument(
        "--metadata",
        help="JSON metadata inventory path (default: DEST/photosort_metadata.json)",
    )
    org.add_argument("-v", "--verbose", action="store_true")
    org.set_defaults(func=cmd_organize)

    st = sub.add_parser("stats", help="Show lens / focal-length stats from metadata JSON")
    st.add_argument(
        "metadata",
        nargs="?",
        default="photosort_metadata.json",
        help="Path to metadata JSON",
    )
    st.add_argument("--lens", help="Filter focal lengths to this lens name")
    st.add_argument("--chart", help="Optional path to write a matplotlib bar chart PNG")
    st.set_defaults(func=cmd_stats)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
