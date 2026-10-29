"""Split text into documents and drive the extraction/repair loop."""

import json
import sys
from typing import Any, Dict, List, NamedTuple, Optional

from jsonschema import Draft202012Validator, Draft7Validator

from .client import Endpoint, UnsupportedJsonMode
from .parse import JsonParseError, extract_json_object

SYSTEM_PROMPT = (
    "You are a data-extraction engine. You reply with exactly one JSON "
    "object and nothing else: no prose, no markdown, no code fences. The "
    "JSON object must conform to the provided JSON Schema. If a value is "
    "not present in the text, use null or an empty value allowed by the "
    "schema rather than inventing facts."
)


def validator_for(schema: Dict[str, Any]):
    """Pick the best jsonschema validator for *schema* and return it."""
    try:
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema)
    except Exception:
        Draft7Validator.check_schema(schema)
        return Draft7Validator(schema)


def build_user_prompt(schema: Dict[str, Any], text: str) -> str:
    serialized = json.dumps(schema, indent=2, ensure_ascii=False)
    return (
        "Extract data from the following text.\n\n"
        "JSON Schema the object must conform to:\n"
        + serialized
        + "\n\nTEXT:\n"
        + text
        + "\n\nReply with only the JSON object."
    )


def repair_message(errors: List[str]) -> str:
    bullet = "\n".join("- " + e for e in errors[:12])
    return (
        "Your previous reply was unusable. Problems:\n"
        + bullet
        + "\nReply again with exactly one corrected JSON object and nothing else."
    )


def split_documents(text: str, separator: Optional[str]) -> List[str]:
    """Split raw file text into document chunks.

    With no separator the whole file is one document. With a separator,
    lines exactly equal to it (after strip) act as boundaries; empty
    documents are dropped.
    """
    if not separator:
        stripped = text.strip()
        return [stripped] if stripped else []
    docs, current = [], []
    for line in text.splitlines():
        if line.strip() == separator:
            docs.append("\n".join(current))
            current = []
        else:
            current.append(line)
    docs.append("\n".join(current))
    return [d.strip() for d in docs if d.strip()]


class ExtractResult(NamedTuple):
    ok: bool
    value: Optional[Dict[str, Any]]
    error: Optional[str]
    attempts: int


def _complete(
    endpoint: Endpoint,
    messages: List[Dict[str, str]],
    model: str,
    temperature: float,
    json_mode: str,
) -> str:
    """One completion, honoring json_mode ('auto' | 'off')."""
    if json_mode == "auto":
        try:
            return endpoint.chat(
                messages, model=model, temperature=temperature, response_json=True
            )
        except UnsupportedJsonMode:
            pass
    return endpoint.chat(messages, model=model, temperature=temperature)


def extract_document(
    endpoint: Optional[Endpoint],
    schema: Dict[str, Any],
    text: str,
    model: str = "",
    temperature: float = 0.0,
    retries: int = 2,
    json_mode: str = "auto",
    log: Optional[Any] = None,
) -> ExtractResult:
    """Extract one record from *text* with strict repair retries.

    *endpoint* may be None only for offline dry runs, which raise
    NotImplementedError here (the CLI refuses earlier with a friendly
    message).
    """
    if endpoint is None:
        raise NotImplementedError("no model, no extraction")
    validator = validator_for(schema)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(schema, text)},
    ]
    failures: List[str] = []
    attempts = 1 + max(0, retries)
    last_error = ""
    for attempt in range(attempts):
        try:
            content = _complete(
                endpoint, messages, model=model, temperature=temperature,
                json_mode=json_mode,
            )
        except NotImplementedError:
            raise
        except Exception as exc:  # endpoint transport/HTTP problems
            last_error = "endpoint error: %s" % exc
            if log:
                print("  attempt %d failed: %s" % (attempt + 1, last_error), file=log)
            break
        messages.append({"role": "assistant", "content": content})
        try:
            value = extract_json_object(content)
        except JsonParseError as exc:
            failures.append("JSON did not parse: %s" % exc)
            last_error = "JSON did not parse: %s" % exc
            messages.append({"role": "user", "content": repair_message(failures[-3:])})
            if log:
                print("  attempt %d: %s" % (attempt + 1, last_error), file=log)
            continue
        schema_errors = []
        for err in validator.iter_errors(value):
            path = "/".join(str(p) for p in err.absolute_path) or "<root>"
            schema_errors.append("at %s: %s" % (path, err.message))
        if schema_errors:
            failures.extend(schema_errors[:5])
            last_error = "schema validation failed: " + "; ".join(schema_errors[:3])
            messages.append(
                {"role": "user", "content": repair_message(schema_errors[:5])}
            )
            if log:
                print("  attempt %d: %s" % (attempt + 1, last_error), file=log)
            continue
        return ExtractResult(ok=True, value=value, error=None, attempts=attempt + 1)
    return ExtractResult(ok=False, value=None, error=last_error, attempts=attempts)


def write_jsonl(records, out) -> None:
    for record in records:
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        out.write(line + "\n")
