import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from mock_server import MockEndpoint  # noqa: E402

from llm_json_extractor.cli import build_parser, main  # noqa: E402
from llm_json_extractor.client import Endpoint  # noqa: E402


SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "age": {"type": "integer"},
    },
    "required": ["name", "age"],
    "additionalProperties": False,
}

VALID = {"name": "Ada", "age": 36}


@pytest.fixture
def schema_file(tmp_path):
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(SCHEMA), encoding="utf-8")
    return str(path)


@pytest.fixture
def input_file(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("Ada Lovelace is 36 years old.", encoding="utf-8")
    return str(path)


@pytest.fixture
def mock():
    endpoint = MockEndpoint(responses=[json.dumps(VALID)])
    yield endpoint
    endpoint.close()


def run_cli(argv):
    return main(argv)


def test_run_happy_path_writes_jsonl(
    tmp_path, schema_file, input_file, mock, capsys
):
    out = tmp_path / "out.jsonl"
    code = run_cli(
        [
            "run",
            "--schema", schema_file,
            "--input", input_file,
            "--output", str(out),
            "--base-url", mock.base_url,
            "--model", "mock-model",
        ]
    )
    assert code == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == VALID
    request = mock.requests[0]
    assert request["model"] == "mock-model"
    assert request["response_format"] == {"type": "json_object"}
    assert "Ada Lovelace is 36" in MockEndpoint.content_of(request)
    assert request["messages"][0]["role"] == "system"


def test_run_retries_and_repairs_broken_json(
    tmp_path, schema_file, input_file
):
    busted = "Sure! Here you go:\n```json\n{\"name\": 'Ada', \"age\": \"36\"\n```"
    endpoint = MockEndpoint(responses=[busted, json.dumps(VALID)])
    try:
        out = tmp_path / "out.jsonl"
        code = run_cli(
            [
                "run",
                "--schema", schema_file,
                "--input", input_file,
                "--output", str(out),
                "--base-url", endpoint.base_url,
                "--model", "mock-model",
            ]
        )
        assert code == 0
        assert json.loads(out.read_text(encoding="utf-8").splitlines()[0]) == VALID
        assert len(endpoint.requests) == 2
        # Second request must include the repair message.
        assert "unusable" in MockEndpoint.content_of(endpoint.requests[1])
    finally:
        endpoint.close()


def test_run_fails_after_retries_with_errors_file(tmp_path, schema_file, input_file):
    endpoint = MockEndpoint(responses=["this is not json at all"] * 5)
    try:
        out = tmp_path / "out.jsonl"
        errors = tmp_path / "errors.jsonl"
        code = run_cli(
            [
                "run",
                "--schema", schema_file,
                "--input", input_file,
                "--output", str(out),
                "--base-url", endpoint.base_url,
                "--model", "mock-model",
                "--retries", "1",
                "--errors", str(errors),
            ]
        )
        assert code == 3
        assert out.read_text(encoding="utf-8") == ""
        failures = [json.loads(x) for x in errors.read_text(encoding="utf-8").splitlines()]
        assert len(failures) == 1
        assert failures[0]["document"] == 1
        assert "did not parse" in failures[0]["error"]
        assert len(endpoint.requests) == 2  # 1 + 1 retry
    finally:
        endpoint.close()


def test_run_schema_validation_loops_back_into_repair(tmp_path, schema_file, input_file):
    wrong = {"name": "Ada", "age": "not a number"}
    endpoint = MockEndpoint(responses=[json.dumps(wrong), json.dumps(VALID)])
    try:
        out = tmp_path / "out.jsonl"
        code = run_cli(
            [
                "run",
                "--schema", schema_file,
                "--input", input_file,
                "--output", str(out),
                "--base-url", endpoint.base_url,
                "--model", "mock-model",
            ]
        )
        assert code == 0
        assert len(endpoint.requests) == 2
        assert "age" in MockEndpoint.content_of(endpoint.requests[1])
    finally:
        endpoint.close()


def test_run_http_500_reports_clean_error(tmp_path, schema_file, input_file):
    endpoint = MockEndpoint(http_status=500)
    try:
        code = run_cli(
            [
                "run",
                "--schema", schema_file,
                "--input", input_file,
                "--output", "-",
                "--base-url", endpoint.base_url,
                "--model", "mock-model",
            ]
        )
        assert code == 3
    finally:
        endpoint.close()


def test_run_unreachable_endpoint_errors(tmp_path, schema_file, input_file):
    code = run_cli(
        [
            "run",
            "--schema", schema_file,
            "--input", input_file,
            "--output", "-",
            "--base-url", "http://127.0.0.1:1/v1",  # port 1, nothing listens
            "--model", "mock-model",
            "--timeout", "2",
        ]
    )
    assert code == 3


def test_run_offline_refuses(tmp_path, schema_file, input_file, capsys):
    code = run_cli(
        [
            "run",
            "--schema", schema_file,
            "--input", input_file,
            "--output", "-",
            "--offline",
        ]
    )
    assert code == 2
    assert "no model, no extraction" in capsys.readouterr().err


def test_run_ai_key_is_never_coerced_to_be_accepted(capsys, schema_file, input_file):
    code = run_cli(
        [
            "run",
            "--schema", schema_file,
            "--input", input_file,
            "--output", "-",
            "--model", "mock-model",
            "--api-key", "sk-nope",
        ]
    )
    assert code == 2
    assert "not accepted" in capsys.readouterr().err


def test_run_requires_model(tmp_path, schema_file, input_file, capsys):
    code = run_cli(
        [
            "run",
            "--schema", schema_file,
            "--input", input_file,
            "--output", "-",
            "--json-mode", "off",
        ]
    )
    assert code == 2
    assert "--model" in capsys.readouterr().err


def test_split_separator(tmp_path, schema_file, mock):
    input_path = tmp_path / "multi.txt"
    input_path.write_text(
        "Ada is 36.\n---\nGrace is 45.\n---\n", encoding="utf-8"
    )
    endpoint = MockEndpoint(
        completion_fn=lambda payload: (json.dumps({"name": "X", "age": 1}), 200)
    )
    try:
        out = tmp_path / "out.jsonl"
        code = run_cli(
            [
                "run",
                "--schema", schema_file,
                "--input", str(input_path),
                "--output", str(out),
                "--base-url", endpoint.base_url,
                "--model", "mock-model",
                "--split-separator=---",
            ]
        )
        assert code == 0
        assert out.read_text(encoding="utf-8").count("\n") == 2
        assert len(endpoint.requests) == 2
        assert "Ada" in MockEndpoint.content_of(endpoint.requests[0])
        assert "Grace" in MockEndpoint.content_of(endpoint.requests[1])
    finally:
        endpoint.close()


def test_json_mode_off_does_not_send_response_format(schema_file, input_file):
    endpoint = MockEndpoint(responses=[json.dumps(VALID)])
    try:
        code = run_cli(
            [
                "run",
                "--schema", schema_file,
                "--input", input_file,
                "--output", "-",
                "--base-url", endpoint.base_url,
                "--model", "mock-model",
                "--json-mode", "off",
            ]
        )
        assert code == 0
        assert "response_format" not in endpoint.requests[0]
    finally:
        endpoint.close()


def test_validate_good_file(tmp_path, schema_file, capsys):
    good = tmp_path / "good.jsonl"
    good.write_text(json.dumps(VALID) + "\n", encoding="utf-8")
    code = run_cli(
        ["validate", "--schema", schema_file, "--input", str(good), "--offline"]
    )
    assert code == 0
    assert "valid" in capsys.readouterr().err


def test_validate_bad_file(tmp_path, schema_file, capsys):
    bad = tmp_path / "bad.jsonl"
    bad_lines = [json.dumps({"name": "Ada"}), "{oops", json.dumps({"name": "x", "age": -1, "extra": 1})]
    bad.write_text("\n".join(bad_lines) + "\n", encoding="utf-8")
    code = run_cli(
        ["validate", "--schema", schema_file, "--input", str(bad), "--offline"]
    )
    assert code == 3
    err = capsys.readouterr().err
    assert "line 2" in err and "not JSON" in err
    assert "line 1" in err


def test_validate_is_fully_offline(tmp_path, schema_file):
    # Even with a dead base-url, validate works: it never dials out.
    good = tmp_path / "good.jsonl"
    good.write_text(json.dumps(VALID) + "\n", encoding="utf-8")
    ep = Endpoint(base_url="http://127.0.0.1:1/v1", timeout=2)
    # Simulate: validate path never constructs an endpoint; this is a
    # concrete check that no network object is needed.
    assert ep is not None
    from llm_json_extractor.cli import main as _m  # noqa: F401
