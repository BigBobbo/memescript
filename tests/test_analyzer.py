"""Tests for the script analyzer (Stage 1)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from memescript.analyzer import (
    _density_to_max_count,
    analyze_script,
    format_script_for_analysis,
    parse_script,
)
from memescript.models import MemeDensity, PipelineConfig, ScriptLine


class TestParseScript:
    def test_simple_lines(self):
        script = "Hello world\nThis is a test\nAnother line"
        lines = parse_script(script)
        assert len(lines) == 3
        assert lines[0].text == "Hello world"
        assert lines[0].timestamp is None
        assert lines[2].text == "Another line"

    def test_timestamped_lines(self):
        script = "00:00 - Introduction\n00:15 - Main content\n01:30 - Conclusion"
        lines = parse_script(script)
        assert len(lines) == 3
        assert lines[0].timestamp == "00:00"
        assert lines[0].text == "Introduction"
        assert lines[1].timestamp == "00:15"
        assert lines[2].timestamp == "01:30"

    def test_bracket_timestamps(self):
        script = "[00:05] Some line\n[1:30] Another line"
        lines = parse_script(script)
        assert len(lines) == 2
        assert lines[0].timestamp == "00:05"
        assert lines[0].text == "Some line"
        assert lines[1].timestamp == "1:30"

    def test_empty_lines_skipped(self):
        script = "Line one\n\n\nLine two\n\n"
        lines = parse_script(script)
        assert len(lines) == 2

    def test_whitespace_handling(self):
        script = "  Hello  \n  World  "
        lines = parse_script(script)
        assert len(lines) == 2
        assert lines[0].text == "Hello"
        assert lines[1].text == "World"

    def test_mixed_format(self):
        script = "00:00 - Timestamped line\nNo timestamp here\n[01:00] Bracketed"
        lines = parse_script(script)
        assert len(lines) == 3
        assert lines[0].timestamp == "00:00"
        assert lines[1].timestamp is None
        assert lines[2].timestamp == "01:00"

    def test_empty_script(self):
        lines = parse_script("")
        assert lines == []

    def test_timestamp_with_hours(self):
        script = "1:23:45 - Long video line"
        lines = parse_script(script)
        assert len(lines) == 1
        assert lines[0].timestamp == "1:23:45"

    def test_line_index_assigned(self):
        script = "Line A\nLine B\nLine C"
        lines = parse_script(script)
        assert lines[0].index == 0
        assert lines[1].index == 1
        assert lines[2].index == 2


class TestFormatScriptForAnalysis:
    def test_basic_formatting(self):
        lines = [
            ScriptLine(text="Hello", timestamp=None, index=0),
            ScriptLine(text="World", timestamp="00:05", index=1),
        ]
        result = format_script_for_analysis(lines)
        assert "0: Hello" in result
        assert "1: [00:05] World" in result


class TestDensityToMaxCount:
    def test_sparse(self):
        assert _density_to_max_count(MemeDensity.SPARSE, 30) == 3
        assert _density_to_max_count(MemeDensity.SPARSE, 5) == 1

    def test_moderate(self):
        assert _density_to_max_count(MemeDensity.MODERATE, 25) == 5
        assert _density_to_max_count(MemeDensity.MODERATE, 5) == 2

    def test_fireship(self):
        assert _density_to_max_count(MemeDensity.FIRESHIP, 20) == 10
        assert _density_to_max_count(MemeDensity.FIRESHIP, 4) == 3


class TestAnalyzeScript:
    def _make_mock_llm(self, response):
        """Create a mock LLM that returns a predefined JSON response."""
        mock = MagicMock()
        mock.query_json.return_value = response
        return mock

    def test_basic_analysis(self):
        lines = [
            ScriptLine(text="JavaScript has too many frameworks", index=0),
            ScriptLine(text="Here's a boring transition", index=1),
            ScriptLine(text="The bundle size is 450 kilobytes for hello world", index=2),
        ]
        config = PipelineConfig(density=MemeDensity.MODERATE)

        mock_response = [
            {
                "line": "JavaScript has too many frameworks",
                "line_index": 0,
                "timestamp": None,
                "comedy_mechanism": "pain",
                "emotional_beat": "frustration",
                "subtext": "Here we go again",
                "confidence": 0.9,
                "context_summary": "Discussing JS ecosystem",
            },
            {
                "line": "The bundle size is 450 kilobytes for hello world",
                "line_index": 2,
                "timestamp": None,
                "comedy_mechanism": "absurdity",
                "emotional_beat": "horror",
                "subtext": "That's insane for a hello world",
                "confidence": 0.85,
                "context_summary": "Bundle size criticism",
            },
        ]
        llm = self._make_mock_llm(mock_response)

        moments = analyze_script(lines, config, llm)
        assert len(moments) == 2
        assert moments[0].confidence >= moments[1].confidence
        assert moments[0].comedy_mechanism == "pain"

    def test_density_filtering(self):
        lines = [ScriptLine(text=f"Line {i}", index=i) for i in range(5)]
        config = PipelineConfig(density=MemeDensity.SPARSE)

        # Return more moments than sparse density allows
        mock_response = [
            {
                "line": f"Line {i}",
                "line_index": i,
                "comedy_mechanism": "irony",
                "emotional_beat": "smugness",
                "subtext": f"sub {i}",
                "confidence": 0.9 - i * 0.1,
            }
            for i in range(5)
        ]
        llm = self._make_mock_llm(mock_response)

        moments = analyze_script(lines, config, llm)
        max_allowed = _density_to_max_count(MemeDensity.SPARSE, 5)
        assert len(moments) <= max_allowed

    def test_handles_malformed_response(self):
        lines = [ScriptLine(text="Test", index=0)]
        config = PipelineConfig()

        mock_response = [
            {"line": "Test", "line_index": 0, "comedy_mechanism": "irony",
             "emotional_beat": "frustration", "subtext": "ok", "confidence": 0.8},
            {"bad_key": "missing required fields"},  # malformed
        ]
        llm = self._make_mock_llm(mock_response)

        moments = analyze_script(lines, config, llm)
        assert len(moments) == 1

    def test_empty_response(self):
        lines = [ScriptLine(text="Boring content", index=0)]
        config = PipelineConfig()
        llm = self._make_mock_llm([])

        moments = analyze_script(lines, config, llm)
        assert moments == []

    def test_single_object_response(self):
        """LLM returns a single object instead of an array."""
        lines = [ScriptLine(text="Test", index=0)]
        config = PipelineConfig()

        mock_response = {
            "line": "Test",
            "line_index": 0,
            "comedy_mechanism": "irony",
            "emotional_beat": "frustration",
            "subtext": "test",
            "confidence": 0.7,
        }
        llm = self._make_mock_llm(mock_response)

        moments = analyze_script(lines, config, llm)
        assert len(moments) == 1
