"""Entry point for ``llm-json-extractor`` (and the ``lje`` alias).

Copyright (c) 2026 Asdale Dynamics, LLC. MIT licensed.
"""

import argparse
import json
import os
import sys
from typing import Optional

from .client import Endpoint
from .extractor import (
    extract_document,
    split_documents,
    validator_for,
    write_jsonl,
)

DEFAULT_BASE_URL = "http://localhost:11434/v1"

BANNER = "llm-json-extractor 0.1.0 — messy prose in, validated JSONL out."


def _refuse_key(_value: str, context: str) -> None:
    sys.stderr.write(
        "error: %s is not accepted. This tool is configured by base URL only — "
        "local-first, no API keys. Hosted endpoints can front a local proxy.\n"
        % context
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm-json-extractor",
        description=BANNER
        + " Configured by base URL, never by API key. See `run` and `validate`.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="extract records from a text file")
    run.add_argument("--schema", required=True, help="JSON Schema file for one record")
    run.add_argument("--input", required=True, help="text file with messy prose")
    run.add_argument(
        "--output", default="-", help="JSONL destination (default: stdout)"
    )
    run.add_argument(
        "--base-url",
        default=os.environ.get("LJE_BASE_URL", DEFAULT_BASE_URL),
        help="OpenAI-compatible endpoint root (default: Ollama localhost:11434/v1)",
    )
    run.add_argument(
        "--model",
        default=os.environ.get("LJE_MODEL", ""),
        help="model name (default: $LJE_MODEL)",
    )
    run.add_argument(
        "--temperature", type=float, default=0.0, help="sampling temperature"
    )
    run.add_argument(
        "--retries", type=int, default=2, help="extra repair attempts per document"
    )
    run.add_argument("--timeout", type=float, default=120.0, help="HTTP timeout")
    run.add_argument(
        "--split-separator",
        default=None,
        metavar="SEP",
        help="split documents on lines exactly equal to SEP",
    )
    run.add_argument(
        "--json-mode",
        choices=("auto", "off"),
        default="auto",
        help="auto = request response_format json_object, fall back if rejected",
    )
    run.add_argument("--errors", default=None, help="optional failure-report JSONL")
    run.add_argument(
        "--offline",
        action="store_true",
        help="no model, no extraction: refuse to touch the network",
    )
    run.add_argument(
        "--api-key",
        default=None,
        help=argparse.SUPPRESS,  # accepted only to refuse it loudly
    )

    val = sub.add_parser("validate", help="check a JSONL file against a schema (offline)")
    val.add_argument("--schema", required=True)
    val.add_argument("--input", required=True)
    val.add_argument(
        "--offline",
        action="store_true",
        help="accepted for symmetry; validate is always offline",
    )
    val.add_argument(
        "--api-key",
        default=None,
        help=argparse.SUPPRESS,
    )
    return parser


def cmd_run(args: argparse.Namespace) -> int:
    if args.api_key is not None:
        _refuse_key(args.api_key, "--api-key")
        return 2
    if args.offline:
        sys.stderr.write(
            "no model, no extraction: %s refused to touch the network.\n"
            "Use `validate` instead, or drop --offline to extract.\n"
            % os.path.basename(sys.argv[0])
        )
        return 2
    if not args.model:
        sys.stderr.write(
            "error: no --model given (and $LJE_MODEL is unset). "
            "Try e.g. --model llama3.1:8b, or use --offline to stay dark.\n"
        )
        return 2

    try:
        with open(args.schema, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
        validator_for(schema)  # fail fast on a bad schema
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write("error: cannot load schema %s: %s\n" % (args.schema, exc))
        return 2

    try:
        with open(args.input, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        sys.stderr.write("error: cannot read input %s: %s\n" % (args.input, exc))
        return 2

    documents = split_documents(text, args.split_separator)
    if not documents:
        sys.stderr.write("error: input %s is empty.\n" % args.input)
        return 2

    endpoint = Endpoint(base_url=args.base_url, timeout=args.timeout)
    errors_file = open(args.errors, "w", encoding="utf-8") if args.errors else None
    out = (
        open(args.output, "w", encoding="utf-8") if args.output != "-" else sys.stdout
    )
    failures = 0
    written = 0
    try:
        for index, document in enumerate(documents, start=1):
            sys.stderr.write(
                "document %d/%d (chars %d) ..." % (index, len(documents), len(document))
            )
            result = extract_document(
                endpoint,
                schema,
                document,
                model=args.model,
                temperature=args.temperature,
                retries=args.retries,
                json_mode=args.json_mode,
                log=sys.stderr,
            )
            if result.ok:
                write_jsonl([result.value], out)
                out.flush()
                written += 1
                sys.stderr.write(" ok (attempt %d)\n" % result.attempts)
            else:
                failures += 1
                sys.stderr.write(" FAILED: %s\n" % result.error)
                if errors_file:
                    write_jsonl(
                        [
                            {
                                "document": index,
                                "error": result.error,
                                "attempts": result.attempts,
                            }
                        ],
                        errors_file,
                    )
    finally:
        if errors_file:
            errors_file.close()
        if out is not sys.stdout:
            out.close()

    if failures:
        sys.stderr.write(
            "done: %d record(s) written, %d document(s) failed (%d total).\n"
            % (written, failures, len(documents))
        )
        return 3
    sys.stderr.write(
        "done: %d record(s) written (from %d document(s)).\n" % (written, len(documents))
    )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    if args.api_key is not None:
        _refuse_key(args.api_key, "--api-key")
        return 2
    try:
        with open(args.schema, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
        validator = validator_for(schema)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write("error: cannot load schema %s: %s\n" % (args.schema, exc))
        return 2

    bad = 0
    total = 0
    try:
        with open(args.input, "r", encoding="utf-8") as fh:
            for line_number, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                total += 1
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    bad += 1
                    sys.stderr.write(
                        "line %d: not JSON: %s\n" % (line_number, exc)
                    )
                    continue
                for error in validator.iter_errors(record):
                    bad += 1
                    path = "/".join(str(p) for p in error.absolute_path) or "<root>"
                    sys.stderr.write(
                        "line %d: schema violation at %s: %s\n"
                        % (line_number, path, error.message)
                    )
    except OSError as exc:
        sys.stderr.write("error: cannot read %s: %s\n" % (args.input, exc))
        return 2
    if bad:
        sys.stderr.write(
            "invalid: %d of %d record(s) failed. Nothing here needed a network.\n"
            % (bad, total)
        )
        return 3
    sys.stderr.write("valid: %d record(s) conform. No network was touched.\n" % total)
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "validate":
        return cmd_validate(args)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
