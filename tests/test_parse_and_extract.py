import pytest

from llm_json_extractor.parse import (
    JsonParseError,
    balanced_object_spans,
    extract_json_object,
    strip_code_fences,
)
from llm_json_extractor.extractor import (
    build_user_prompt,
    repair_message,
    split_documents,
    validator_for,
)


def test_strip_code_fences():
    assert strip_code_fences("```json\n{}\n```") == "{}"
    assert strip_code_fences("```\n{}\n```") == "{}"
    assert strip_code_fences('{"a": 1}') == '{"a": 1}'
    # fences mid-text are left alone
    assert strip_code_fences('text ```x``` more') == 'text ```x``` more'


def test_balanced_spans_string_aware():
    spans = balanced_object_spans('{"a": "{not real}"} trailing')
    assert spans == [(0, len('{"a": "{not real}"}'))]
    assert balanced_object_spans('no braces') == []


def test_extract_plain():
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_extract_prose_wrapped():
    text = 'Certainly! {"a": {"b": 1}} hope that helps!'
    assert extract_json_object(text) == {"a": {"b": 1}}


def test_extract_from_two_candidates_takes_first():
    text = '{"first": 1} junk {"second": 2}'
    assert extract_json_object(text) == {"first": 1}


def test_extract_braces_inside_strings():
    text = 'prefix {"code": "if (x) { return \\"}\\" ;"} } suffix'
    assert extract_json_object(text) == {"code": 'if (x) { return "}" ;'}


def test_extract_non_object_raises():
    with pytest.raises(JsonParseError):
        extract_json_object('[1, 2, 3]')
    with pytest.raises(JsonParseError):
        extract_json_object(r'utterly no json \}{ here')
    with pytest.raises(JsonParseError):
        extract_json_object("")


def test_repair_message_lists_errors():
    msg = repair_message(["missing field", "bad type"])
    assert "- missing field" in msg
    assert "corrected JSON object" in msg


def test_user_prompt_contains_schema_and_text():
    prompt = build_user_prompt({"type": "object"}, "hello world")
    assert '"type": "object"' in prompt
    assert "hello world" in prompt


def test_split_documents_default_single():
    assert split_documents("  a\nb  ", None) == ["a\nb"]
    assert split_documents("", None) == []
    assert split_documents("   ", None) == []


def test_split_documents_with_separator():
    text = "one\n---\n---\ntwo\n---\n\nthree\n"
    docs = split_documents(text, "---")
    assert docs == ["one", "two", "three"]


def test_validator_for_transform_schema():
    schema = {
        "type": "object",
        "properties": {"n": {"type": "integer"}},
        "required": ["n"],
    }
    v = validator_for(schema)
    assert v.is_valid({"n": 3})
    assert not v.is_valid({"n": "3"})
