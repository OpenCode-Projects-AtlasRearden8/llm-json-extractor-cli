# STATUS

## What was built

**llm-json-extractor** (v0.1.0) — a Python CLI that turns messy prose into
clean data. It accepts a JSON Schema and a text file, requests structured
output from any configurable OpenAI-compatible endpoint (base URL only —
never an API key, default Ollama `localhost:11434/v1`), repairs shaky JSON
with strict retries, validates every record against the schema, and writes
JSONL. It complements prompt-lab-cli (prompt design → this tool → batch
extraction).

- Local-first: no secrets, no telemetry; header vars `LJE_BASE_URL` /
  `LJE_MODEL` keep setup out of shell history.
- Explicit `--offline` mode: extraction refuses outright with
  "no model, no extraction" (exit 2); the `validate` subcommand is always
  fully offline.
- `--api-key` is accepted solely to be refused with an explanation.
- Strict repair loop: code-fence stripping, string-aware balanced-`{...}`
  extraction, then repair messages containing precise parse/schema errors,
  `--retries` extra attempts (default 2 = 3 total tries per document).
- Failure isolation: extra tabs? No — invalid records never touch the
  output file; per-document failures go to `--errors` as JSONL.
- Exit codes: 0 all good, 2 offline/usage refusal, 3 some documents failed.

## Layout

```
src/llm_json_extractor/   cli.py, client.py, extractor.py, parse.py
tests/                    pytest suite + in-process mock OpenAI endpoint
examples/                 band-roster schema + prose sample
pyproject.toml            deps: jsonschema; scripts: llm-json-extractor, lje
LICENSE                   MIT, Copyright (c) 2026 Asdale Dynamics, LLC
README.md                 full docs, crediting Asdale Dynamics, LLC
```

## How to run

```bash
pip install .                       # or: pip install -e .[dev] for tests
llm-json-extractor run \
  --schema examples/band-roster.schema.json \
  --input examples/band-roster.txt \
  --output records.jsonl \
  --model llama3.1:8b               # Ollama assumed at localhost:11434/v1
llm-json-extractor validate \
  --schema examples/band-roster.schema.json --input records.jsonl
```

## Verification results

- `pytest`: **26 passed, 0 failed, 0 warnings** (Python 3.13, pytest 9.2,
  jsonschema 4.26). Coverage of: happy path (asserts `response_format`
  sent), repair of fence-soup (`--retries` consumed as expected), retry
  exhaustion (exit 3 + `--errors` JSONL), schema-failure → repair loop,
  HTTP 500 behavior, unreachable endpoint, offline refusal, `--api-key`
  refusal, missing-model refusal, `--split-separator` chunking,
  `--json-mode off`, validate pass/fail paths, parser unit tests
  (fences, prose-wrapped JSON, braces-inside-strings, non-object errors).
- Package build: `pip wheel` succeeds; installed into a **fresh venv**, and
  both console scripts (`llm-json-extractor`, `lje`) ran correctly
  including the offline refusal checked against the example files.
- End-to-end smoke script (mock endpoint scripted to return unparsable
  first drafts): 2 documents → each repaired on attempt 2 → 2 valid JSONL
  lines; `validate` returned "2 record(s) conform"; `--offline` run
  exited 2 with the "no model, no extraction" message.

## Known gaps

- Streaming is not implemented (whole completions only); fine for typical
  extraction prompts, slower for very long generation.
- JSON Schema features beyond draft-07/2020-12 constructs that
  `jsonschema` itself handles well (e.g. exotic `$ref` trees over counters)
  are untested territory.
- The mock server covers deterministic behaviors, not latency/timeout
  races; live endpoints with slow models work via `--timeout` but that
  path's edge cases are not fuzz-tested.
- No `--resume`/checkpointing: a rerun re-extracts every document.
- Output sorting (`sort_keys=True`) is fixed; no pretty-JSONL option yet.
