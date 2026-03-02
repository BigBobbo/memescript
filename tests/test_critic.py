"""Tests for the meme critic (Stage 4)."""

from unittest.mock import MagicMock

import pytest

from memescript.critic import (
    _neutral_critique,
    critique_suggestions,
    filter_by_quality,
)
from memescript.models import (
    CritiqueResult,
    MemeableMoment,
    MemeSuggestion,
    PipelineConfig,
)


def _make_moment(line_index=0):
    return MemeableMoment(
        line="Test line",
        timestamp=None,
        line_index=line_index,
        comedy_mechanism="irony",
        emotional_beat="smugness",
        subtext="test subtext",
        confidence=0.9,
    )


def _make_suggestion(line_index=0, template_name="Drake Preference"):
    return MemeSuggestion(
        moment=_make_moment(line_index),
        template_name=template_name,
        captions={"top": "A", "bottom": "B"},
        reasoning="Test",
        rank=1,
    )


class TestCritiqueSuggestions:
    def test_basic_critique(self):
        suggestions = [_make_suggestion()]
        config = PipelineConfig()

        llm = MagicMock()
        llm.query_json.return_value = {
            "surprise_score": 4,
            "relevance_score": 5,
            "timing_score": 4,
            "freshness_score": 3,
            "passes_layer_test": True,
            "feedback": "Good choice, unexpected application.",
            "alternative": None,
        }

        critiques = critique_suggestions(suggestions, config, llm)
        assert len(critiques) == 1
        assert critiques[0].surprise_score == 4
        assert critiques[0].relevance_score == 5
        assert critiques[0].passes_layer_test is True
        assert critiques[0].overall_score == 4.0

    def test_critique_with_alternative(self):
        suggestions = [_make_suggestion()]
        config = PipelineConfig()

        llm = MagicMock()
        llm.query_json.return_value = {
            "surprise_score": 2,
            "relevance_score": 3,
            "timing_score": 3,
            "freshness_score": 2,
            "passes_layer_test": False,
            "feedback": "Too predictable. Try something unexpected.",
            "alternative": {
                "template_name": "Expanding Brain",
                "captions": {"level_1": "A", "level_4": "D"},
                "reasoning": "Escalation fits better",
            },
        }

        critiques = critique_suggestions(suggestions, config, llm)
        assert len(critiques) == 1
        assert critiques[0].passes_layer_test is False
        assert critiques[0].alternative is not None
        assert critiques[0].alternative.template_name == "Expanding Brain"

    def test_handles_llm_error_gracefully(self):
        suggestions = [_make_suggestion()]
        config = PipelineConfig()

        llm = MagicMock()
        llm.query_json.side_effect = ValueError("Parse error")

        critiques = critique_suggestions(suggestions, config, llm)
        assert len(critiques) == 1
        # Should get neutral critique
        assert critiques[0].overall_score == 3.0
        assert critiques[0].passes_layer_test is True


class TestNeutralCritique:
    def test_neutral_values(self):
        suggestion = _make_suggestion()
        critique = _neutral_critique(suggestion)
        assert critique.overall_score == 3.0
        assert critique.passes_layer_test is True
        assert critique.surprise_score == 3


class TestFilterByQuality:
    def test_filters_below_threshold(self):
        s1 = _make_suggestion(line_index=0, template_name="Good")
        s2 = _make_suggestion(line_index=1, template_name="Bad")

        c1 = CritiqueResult(
            suggestion=s1,
            surprise_score=4, relevance_score=4,
            timing_score=4, freshness_score=4,
            passes_layer_test=True, overall_score=4.0,
        )
        c2 = CritiqueResult(
            suggestion=s2,
            surprise_score=1, relevance_score=1,
            timing_score=1, freshness_score=1,
            passes_layer_test=False, overall_score=1.0,
        )

        config = PipelineConfig(quality_threshold=3.0)
        filtered_suggestions, filtered_critiques = filter_by_quality(
            [s1, s2], [c1, c2], config
        )
        assert len(filtered_suggestions) == 1
        assert filtered_suggestions[0].template_name == "Good"

    def test_keeps_best_per_moment(self):
        s1 = _make_suggestion(line_index=0, template_name="Okay")
        s2 = _make_suggestion(line_index=0, template_name="Better")

        c1 = CritiqueResult(
            suggestion=s1,
            surprise_score=3, relevance_score=3,
            timing_score=3, freshness_score=3,
            passes_layer_test=True, overall_score=3.0,
        )
        c2 = CritiqueResult(
            suggestion=s2,
            surprise_score=5, relevance_score=5,
            timing_score=5, freshness_score=5,
            passes_layer_test=True, overall_score=5.0,
        )

        config = PipelineConfig(quality_threshold=3.0)
        filtered_suggestions, _ = filter_by_quality(
            [s1, s2], [c1, c2], config
        )
        assert len(filtered_suggestions) == 1
        assert filtered_suggestions[0].template_name == "Better"

    def test_uses_alternative_when_original_fails(self):
        s1 = _make_suggestion(line_index=0, template_name="Bad")

        alt = MemeSuggestion(
            moment=s1.moment,
            template_name="Alternative",
            captions={"top": "Better"},
            reasoning="Better choice",
            rank=0,
        )

        c1 = CritiqueResult(
            suggestion=s1,
            surprise_score=1, relevance_score=1,
            timing_score=1, freshness_score=1,
            passes_layer_test=False, overall_score=1.0,
            alternative=alt,
        )

        config = PipelineConfig(quality_threshold=3.0)
        filtered_suggestions, _ = filter_by_quality([s1], [c1], config)
        assert len(filtered_suggestions) == 1
        assert filtered_suggestions[0].template_name == "Alternative"

    def test_empty_input(self):
        config = PipelineConfig()
        filtered_suggestions, filtered_critiques = filter_by_quality([], [], config)
        assert filtered_suggestions == []
        assert filtered_critiques == []
