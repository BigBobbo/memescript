"""Tests for the meme selector (Stage 2)."""

from unittest.mock import MagicMock

import pytest

from memescript.meme_db import MemeDatabase
from memescript.models import (
    MemeableMoment,
    MemeSuggestion,
    MemeFormat,
    MemeTemplate,
    PipelineConfig,
    TextRegion,
)
from memescript.selector import select_memes


def _make_moment(**kwargs):
    defaults = dict(
        line="JavaScript has too many frameworks",
        timestamp=None,
        line_index=0,
        comedy_mechanism="pain",
        emotional_beat="frustration",
        subtext="Here we go again",
        confidence=0.9,
        context_summary="Discussing JS ecosystem",
    )
    defaults.update(kwargs)
    return MemeableMoment(**defaults)


def _make_mock_llm(response):
    mock = MagicMock()
    mock.query_json.return_value = response
    return mock


class TestSelectMemes:
    def test_open_selection(self):
        moments = [_make_moment()]
        config = PipelineConfig(max_suggestions_per_moment=2)

        mock_response = [
            {
                "template_name": "Drake Preference",
                "reasoning": "Classic comparison meme",
                "captions": {"rejected": "Stable code", "preferred": "New framework"},
                "modification_needed": False,
                "rank": 1,
            },
            {
                "template_name": "This Is Fine",
                "reasoning": "Everything is burning",
                "captions": {"caption": "JS ecosystem"},
                "modification_needed": False,
                "rank": 2,
            },
        ]
        llm = _make_mock_llm(mock_response)

        suggestions = select_memes(moments, config, meme_db=None, llm=llm)
        assert len(suggestions) == 2
        assert suggestions[0].template_name == "Drake Preference"
        assert suggestions[0].rank == 1

    def test_constrained_selection_with_db(self):
        moments = [_make_moment()]
        config = PipelineConfig(max_suggestions_per_moment=1)

        db = MemeDatabase()
        db.add(MemeTemplate(
            name="Drake Preference",
            filename="drake.png",
            format=MemeFormat.DRAKE,
            emotions=["frustration", "preference"],
            tags=["comparison"],
            humor_convention="Top rejected, bottom preferred",
            text_regions=[
                TextRegion(label="rejected", x=0, y=0, width=400, height=300),
                TextRegion(label="preferred", x=0, y=300, width=400, height=300),
            ],
        ))

        mock_response = [
            {
                "template_name": "Drake Preference",
                "reasoning": "Perfect for comparison",
                "captions": {"rejected": "Old way", "preferred": "New way"},
                "modification_needed": False,
                "rank": 1,
            },
        ]
        llm = _make_mock_llm(mock_response)

        suggestions = select_memes(moments, config, meme_db=db, llm=llm)
        assert len(suggestions) == 1
        assert suggestions[0].template_name == "Drake Preference"

    def test_multiple_moments(self):
        moments = [
            _make_moment(line="Moment 1", line_index=0),
            _make_moment(line="Moment 2", line_index=5),
        ]
        config = PipelineConfig(max_suggestions_per_moment=1)

        mock_response = [
            {
                "template_name": "Surprised Pikachu",
                "reasoning": "Obvious outcome",
                "captions": {"caption": "Test"},
                "modification_needed": False,
                "rank": 1,
            },
        ]
        llm = _make_mock_llm(mock_response)

        suggestions = select_memes(moments, config, meme_db=None, llm=llm)
        # One suggestion per moment
        assert len(suggestions) == 2

    def test_handles_malformed_suggestion(self):
        moments = [_make_moment()]
        config = PipelineConfig()

        mock_response = [
            {
                "template_name": "Good One",
                "reasoning": "Works",
                "captions": {"top": "A"},
                "rank": 1,
            },
            {"bad": "missing template_name"},  # malformed
        ]
        llm = _make_mock_llm(mock_response)

        suggestions = select_memes(moments, config, meme_db=None, llm=llm)
        assert len(suggestions) == 1

    def test_handles_llm_error_gracefully(self):
        moments = [_make_moment()]
        config = PipelineConfig()

        llm = MagicMock()
        llm.query_json.side_effect = ValueError("Parse error")

        suggestions = select_memes(moments, config, meme_db=None, llm=llm)
        assert suggestions == []

    def test_suggestions_sorted_by_rank(self):
        moments = [_make_moment()]
        config = PipelineConfig(max_suggestions_per_moment=3)

        mock_response = [
            {"template_name": "C", "reasoning": "", "captions": {}, "rank": 3},
            {"template_name": "A", "reasoning": "", "captions": {}, "rank": 1},
            {"template_name": "B", "reasoning": "", "captions": {}, "rank": 2},
        ]
        llm = _make_mock_llm(mock_response)

        suggestions = select_memes(moments, config, meme_db=None, llm=llm)
        assert suggestions[0].template_name == "A"
        assert suggestions[1].template_name == "B"
        assert suggestions[2].template_name == "C"
