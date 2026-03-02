"""Tests for the LLM client and JSON parsing."""

import pytest

from memescript.llm import parse_json_response


class TestParseJsonResponse:
    def test_plain_json_array(self):
        result = parse_json_response('[{"a": 1}, {"b": 2}]')
        assert result == [{"a": 1}, {"b": 2}]

    def test_plain_json_object(self):
        result = parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_in_markdown_block(self):
        text = '```json\n[{"x": 1}]\n```'
        result = parse_json_response(text)
        assert result == [{"x": 1}]

    def test_json_in_generic_code_block(self):
        text = '```\n{"a": "b"}\n```'
        result = parse_json_response(text)
        assert result == {"a": "b"}

    def test_json_with_surrounding_text(self):
        text = 'Here is the result:\n[{"meme": "test"}]\nDone!'
        result = parse_json_response(text)
        assert result == [{"meme": "test"}]

    def test_json_object_with_surrounding_text(self):
        text = 'The analysis shows:\n{"score": 5, "good": true}\nEnd.'
        result = parse_json_response(text)
        assert result == {"score": 5, "good": True}

    def test_whitespace_handling(self):
        result = parse_json_response('  \n  {"a": 1}  \n  ')
        assert result == {"a": 1}

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Could not parse JSON"):
            parse_json_response("This is not JSON at all")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            parse_json_response("")

    def test_nested_json(self):
        text = '{"outer": {"inner": [1, 2, 3]}}'
        result = parse_json_response(text)
        assert result["outer"]["inner"] == [1, 2, 3]

    def test_json_with_markdown_and_explanation(self):
        text = """Here are the meme suggestions:

```json
[
    {
        "template_name": "Drake Preference",
        "rank": 1
    }
]
```

These should work well for the video."""
        result = parse_json_response(text)
        assert len(result) == 1
        assert result[0]["template_name"] == "Drake Preference"
