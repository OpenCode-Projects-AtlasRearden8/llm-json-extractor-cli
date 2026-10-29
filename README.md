# llm-json-extractor

A small, local-first CLI that turns messy prose into clean data.

Give it a JSON schema and a text file, and it asks a configurable
OpenAI-compatible endpoint for structured output, repairs shaky JSON with
strict retries, validates every record against your schema, and writes
clean JSONL — one line per record.

Complements [prompt-lab-cli](https://github.com/dylanasdale/prompt-lab-cli):
that tool helps you *write and compare prompts*; this one turns finalized
prompts into a dependable batch extraction pipeline.

Part of the free tool set from **Asdale Dynamics, LLC** — beginner-friendly
AI education and practical tools from Dylan Asdale's
*The Massive AI Manual* (see <https://dylanasdale.github.io>).

## Highlights

- **Any OpenAI-compatible endpoint, by base URL only.** Default is Ollama at
  `http://localhost:11434/v1`. Point it at LM Studio, vLLM, llama.cpp,
  OpenRouter, anything that speaks `/v1/chat/completions`. The tool takes a
  `--base-url` and *never* an API key — local-first means no secrets.
- **Strict retries.** If the model returns prose-wrapped, truncated, or
  broken JSON, the tool extracts what it can, then asks again with a repair
  message and a precise error report until it succeeds or runs out of
  attempts.
- **Schema validation.** Every record is checked with `jsonschema` before it
  is written. Nothing invalid slips into your JSONL.
- **JSONL output.** Line-delimited JSON, ready for `jq`, pandas, or your
  next pipeline step.
- **Works fully offline.** An explicit `--offline` mode never touches the
  network: extraction attempts are refused outright ("no model, no
  extraction") while the `validate` subcommand still checks any JSONL file
  against your schema with zero network access.

## Install

```bash
pip install .
```

With Ollama running locally (`ollama pull llama3.1:8b` or any
JSON-friendly model), you are ready to go.

## Quick start

```bash
# Extract structured records from notes.txt into records.jsonl
llm-json-extractor run \
  --schema examples/patients.json \
  --input examples/notes.txt \
  --output records.jsonl \
  --model llama3.1:8b

# Check results later, fully offline
llm-json-extractor validate --schema examples/patients.json --input records.jsonl

# Explicit offline extraction attempt: refuses, "no model, no extraction"
llm-json-extractor run --schema s.json --input t.txt --output o.jsonl --offline
```

## How it works

1. **Split** the input into documents. By default the whole file is one
   document; pass `--split-separator "---"` to treat lines of `---` as
   document boundaries.
2. **Ask** the endpoint for a completion that is *only* a JSON object
   matching the schema. When the server supports it, the request sets
   `response_format: {"type": "json_object"}`.
3. **Repair.** If the reply is not parseable JSON, the tool strips code
   fences, finds the first balanced `{...}` block, and retries with error
   feedback — `--retries` extra attempts (default 2).
4. **Validate** the parsed object against the schema (fixable failures loop
   back through the same repair path).
5. **Write** one JSON line per valid record. Failures never touch the
   output; they are logged to `--errors` if you ask for them.

## CLI reference

```
llm-json-extractor run
    --schema FILE          JSON Schema describing one record (required)
    --input FILE           Text file containing the messy prose (required)
    --output FILE          JSONL destination (default: stdout)
    --base-url URL         OpenAI-compatible base URL
                           (default: http://localhost:11434/v1, or $LJE_BASE_URL)
    --model NAME           Model name (default: $LJE_MODEL)
    --temperature FLOAT    Sampling temperature (default: 0.0)
    --retries N            Extra repair attempts per document (default: 2)
    --timeout SECONDS      HTTP timeout per request (default: 120)
    --split-separator SEP  Split documents on exact lines equal to SEP
    --json-mode auto|off   auto: request response_format json_object and
                           fall back to plain prompting if unsupported
                           (default: auto)
    --errors FILE          Where to write per-document failure reports
    --offline              Never touch the network: run refuses with
                           "no model, no extraction" (exit 2)
    --api-key ...          Rejected. Base URL only. No keys, ever.

llm-json-extractor validate
    --schema FILE          JSON Schema to check against
    --input FILE           JSONL file with one record per line
    --offline              Accepted here too; validate is always offline,
                           the flag simply documents it
```

Exit codes: `0` all records extracted, `2` offline refusal, `1` network or
usage error, `3` completed with some document failures (see `--errors`).

Environment: `LJE_BASE_URL` and `LJE_MODEL` are read as defaults so you can
keep your setup out of shell history.

## Why no API key support?

Because you do not need one for local AI — and the moment a tool starts
asking for keys, it starts tempting people to paste them into shells and
scripts. `llm-json-extractor` is configured by **endpoint address only**. If
you pass `--api-key`, it politely refuses and explains why. If your hosted
provider technically requires a key, put it in the provider's own env
(`OLLAMA_API_KEY`-style setups) or use a local proxy; this tool stays
key-free by design.

## Everything works offline

Once installed, the tool runs with no network required: point `--base-url`
at your local Ollama (or LM Studio on `http://localhost:1234/v1`), and the
`validate` subcommand uses only the standard library plus `jsonschema`, so a
laptop with no connectivity can still check yesterday's results.

## Privacy by default

- No API keys are accepted, stored, or logged.
- Nothing is telemetry-ed; there is no accounts system or phone-home path.
- Input text goes only to the endpoint you name. With a local Ollama it
  never leaves your machine.
- No personal data belongs in this repo, and the tool never asks for any.

## Development

```bash
pip install -e .[dev]
pytest
```

Tests use a built-in in-process mock OpenAI-compatible HTTP server
(`tests/mock_server.py`) covering the happy path, code-fence soup, JSON
repair loops, server 500s, and schema-validation failures — no network
needed.

## License

MIT — © Copyright (c) 2026 Asdale Dynamics, LLC. See [LICENSE](LICENSE).
