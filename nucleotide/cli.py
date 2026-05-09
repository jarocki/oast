"""Command-line entry point: build the lookup, query it against URLs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .build import build_lookup
from .fetch import PROJECTDISCOVERY_REPO, fetch


def _build(args: argparse.Namespace) -> int:
    if args.templates_dir:
        tdir = args.templates_dir
        source = str(tdir.resolve())
    else:
        tdir = fetch(args.repo, args.cache_dir, update=not args.no_fetch)
        source = args.repo
    result = build_lookup(tdir, source_url=source)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True))
    md = result["metadata"]
    print(
        f"Wrote {args.out} | templates={md['template_count']} "
        f"snippets={md['resolved_snippets']} unresolved={md['unresolved_count']}",
        file=sys.stderr,
    )
    return 0


def _lookup(args: argparse.Namespace) -> int:
    data = json.loads(args.lookup_file.read_text())
    index = data.get("snippet_index", {})
    items = sorted(index.items(), key=lambda kv: -len(kv[0]))
    queries = args.query
    if not queries and not sys.stdin.isatty():
        queries = [line.rstrip("\n") for line in sys.stdin if line.strip()]
    for q in queries:
        hits = [(snip, tid) for snip, tid in items if snip in q]
        if not hits:
            print(f"{q}\tNO_MATCH")
            continue
        for snip, tid in hits:
            meta = data["templates"].get(tid, {})
            sev = meta.get("severity", "")
            name = meta.get("name", "")
            print(f"{q}\t{tid}\t{snip}\t{sev}\t{name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="nucleotide",
        description="Build a URL-snippet lookup table mapping observed URLs back to Nuclei templates.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    bld = sub.add_parser("build", help="Fetch templates and build the lookup table.")
    bld.add_argument("--repo", default=PROJECTDISCOVERY_REPO, help="Template repo URL.")
    bld.add_argument(
        "--templates-dir",
        type=Path,
        default=None,
        help="Use an existing local template tree instead of fetching.",
    )
    bld.add_argument(
        "--cache-dir",
        type=Path,
        default=Path.home() / ".cache" / "nucleotide" / "templates",
        help="Where to clone templates if --templates-dir is not set.",
    )
    bld.add_argument("--out", type=Path, default=Path("nucleotide-lookup.json"))
    bld.add_argument(
        "--no-fetch",
        action="store_true",
        help="Reuse the cache directory without pulling updates.",
    )
    bld.set_defaults(func=_build)

    look = sub.add_parser(
        "lookup", help="Match URLs (args or stdin) against a built lookup file."
    )
    look.add_argument("lookup_file", type=Path)
    look.add_argument("query", nargs="*")
    look.set_defaults(func=_lookup)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
