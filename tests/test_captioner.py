"""Tests for the caption refinement stage (Stage 3)."""

from unittest.mock import MagicMock

import pytest

from memescript.captioner import refine_captions
from memescript.meme_db import MemeDatabase
from memescript.models import (
    MemeableMoment,
    MemeFormat,
    MemeSuggestion,
    MemeTemplate,
    PipelineConfig,
    TextRegion,
)


def _make_suggestion(template_name="Drake Preference", captions=None):
    moment = MemeableMoment(
        line="Test line",
        timestamp=None,
        line_index=0,
        comedy_mechanism="irony",
        emotional_beat="smugness",
        subtext="test subtext",
        confidence=0.9,
        context_summary="Test context",
    )
    return MemeSuggestion(
        moment=moment,
        template_name=template_name,
        captions=captions or {"rejected": "Old", "preferred": "New"},
        reasoning="Test reasoning",
    )


def _make_db():
    db = MemeDatabase()
    db.add(MemeTemplate(
        name="Drake Preference",
        filename="drake.png",
        format=MemeFormat.DRAKE,
        emotions=["smugness"],
        tags=["comparison"],
        humor_convention="Top rejected, bottom preferred",
        text_regions=[
            TextRegion(label="rejected", x=0, y=0, width=400, height=300),
            TextRegion(label="preferred", x=0, y=300, width=400, height=300),
        ],
    ))
    return db


class TestRefineCaptions:
    def test_refines_with_matching_template(self):
        suggestions = [_make_suggestion()]
        config = PipelineConfig()
        db = _make_db()

        llm = MagicMock()
        llm.query_json.return_value = {
            "reasoning": "Better captions because of wordplay",
            "captions": {"rejected": "Refined old", "preferred": "Refined new"},
        }

        refined = refine_captions(suggestions, config, db, llm)
        assert len(refined) == 1
        assert refined[0].captions["rejected"] == "Refined old"
        assert refined[0].captions["preferred"] == "Refined new"

    def test_skips_without_db(self):
        suggestions = [_make_suggestion()]
        config = PipelineConfig()

        refined = refine_captions(suggestions, config, meme_db=None, llm=MagicMock())
        assert len(refined) == 1
        # Original captions preserved
        assert refined[0].captions["rejected"] == "Old"

    def test_skips_without_template_match(self):
        suggestions = [_make_suggestion(template_name="Unknown Meme")]
        config = PipelineConfig()
        db = _make_db()  # Only has Drake Preference

        refined = refine_captions(suggestions, config, db, llm=MagicMock())
        assert len(refined) == 1
        assert refined[0].template_name == "Unknown Meme"
        assert refined[0].captions["rejected"] == "Old"

    def test_falls_back_on_error(self):
        suggestions = [_make_suggestion()]
        config = PipelineConfig()
        db = _make_db()

        llm = MagicMock()
        llm.query_json.side_effect = ValueError("Parse error")

        refined = refine_captions(suggestions, config, db, llm)
        assert len(refined) == 1
        # Original captions preserved on error
        assert refined[0].captions["rejected"] == "Old"

    def test_falls_back_on_empty_captions(self):
        suggestions = [_make_suggestion()]
        config = PipelineConfig()
        db = _make_db()

        llm = MagicMock()
        llm.query_json.return_value = {
            "reasoning": "Something",
            "captions": {},  # empty
        }

        refined = refine_captions(suggestions, config, db, llm)
        assert len(refined) == 1
        assert refined[0].captions["rejected"] == "Old"

    def test_multiple_suggestions(self):
        suggestions = [
            _make_suggestion(captions={"rejected": "A1", "preferred": "A2"}),
            _make_suggestion(captions={"rejected": "B1", "preferred": "B2"}),
        ]
        config = PipelineConfig()
        db = _make_db()

        llm = MagicMock()
        llm.query_json.return_value = {
            "reasoning": "Refined",
            "captions": {"rejected": "Refined", "preferred": "Refined"},
        }

        refined = refine_captions(suggestions, config, db, llm)
        assert len(refined) == 2
        assert all(r.captions["rejected"] == "Refined" for r in refined)
