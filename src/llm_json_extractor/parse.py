"""Pull the first balanced JSON object out of model chatter.

Models love to wrap JSON in prose and markdown fences. This module finds the
first syntactically balanced ``{ ... }`` block (string-aware), preferring
``json.loads``-parseable content and degrading gracefully.
"""

import json
from typing import Any


class JsonParseError(ValueError):
    """Raised when no balanced, parseable JSON object can be recovered."""


def strip_code_fences(text: str) -> str:
    """Remove a single outer ```json ... ``` fence, if present."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        # Drop a trailing fence line if there is one.
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip().startswith("```"):
                lines = lines[:i]
                break
        stripped = "\n".join(lines).strip()
    return stripped


def balanced_object_spans(text: str):
    """Yield (start, end) spans of balanced top-level-looking ``{...}`` blocks.

    String-aware: braces inside JSON string literals are ignored, and escaped
    quotes are honored. Yields spans in order of the opening brace.
    """
    spans = []
    in_string = False
    escape = False
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    spans.append((start, i + 1))
                    start = -1
    return spans


def extract_json_object(text: str) -> Any:
    """Return the parsed first balanced ``{...}`` object in *text*.

    Tries the whole content first (fast path), then each balanced span.
    Raises :class:`JsonParseError` if nothing parses as an object.
    """
    if text is None:
        raise JsonParseError("empty response")
    candidates = [strip_code_fences(text)]
    raw = strip_code_fences(text)
    try:
        value = json.loads(raw)
        if isinstance(value, dict):
            return value
        raise JsonParseError(
            "top-level value is %s, not a JSON object" % type(value).__name__
        )
    except JsonParseError:
        raise
    except json.JSONDecodeError:
        pass

    lowered = raw
    spans = balanced_object_spans(lowered)
    errors = []
    for start, end in spans:
        chunk = raw[start:end]
        try:
            value = json.loads(chunk)
        except json.JSONDecodeError as exc:
            errors.append("span at offset %d: %s" % (start, exc))
            continue
        if isinstance(value, dict):
            return value
        errors.append("span at offset %d is not an object" % start)
    raise JsonParseError(
        "no parseable JSON object found"
        + (("; %s" % "; ".join(errors[:3])) if errors else "")
    )
