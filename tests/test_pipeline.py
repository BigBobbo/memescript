"""Tests for the pipeline orchestrator."""

import json
from unittest.mock import MagicMock, patch

import pytest

from memescript.meme_db import MemeDatabase
from memescript.models import (
    MemeFormat,
    MemeTemplate,
    MemeDensity,
    PipelineConfig,
    TextRegion,
)
from memescript.pipeline import run_pipeline, run_analysis_only, run_suggestions_only


def _make_db():
    db = MemeDatabase()
    db.add(MemeTemplate(
        name="Drake Preference",
        filename="drake.png",
        format=MemeFormat.DRAKE,
        emotions=["smugness", "preference"],
        tags=["comparison"],
        humor_convention="Top rejected, bottom preferred",
        text_regions=[
            TextRegion(label="rejected", x=400, y=20, width=380, height=280),
            TextRegion(label="preferred", x=400, y=320, width=380, height=280),
        ],
    ))
    db.add(MemeTemplate(
        name="This Is Fine",
        filename="this_is_fine.png",
        format=MemeFormat.SINGLE_CAPTION,
        emotions=["resignation", "horror"],
        tags=["disaster", "denial"],
        humor_convention="Dog in burning room",
        text_regions=[
            TextRegion(label="caption", x=300, y=20, width=450, height=120),
        ],
    ))
    return db


def _make_mock_llm():
    """Create a mock LLM with canned responses for each pipeline stage."""
    mock = MagicMock()

    # Track call count to return different responses for different stages
    call_count = [0]

    def side_effect(system, user, **kwargs):
        call_count[0] += 1
        # First call: script analysis
        if "comedy writer analyzing" in system.lower() or "analyze this script" in user.lower():
            return [
                {
                    "line": "There's a new JavaScript framework",
                    "line_index": 2,
                    "timestamp": "00:10",
                    "comedy_mechanism": "pain",
                    "emotional_beat": "frustration",
                    "subtext": "Not again",
                    "confidence": 0.9,
                    "context_summary": "JS frameworks",
                },
            ]
        # Critique stage
        elif "meme critic" in system.lower() or "senior meme critic" in system.lower():
            return {
                "surprise_score": 4,
                "relevance_score": 4,
                "timing_score": 4,
                "freshness_score": 4,
                "passes_layer_test": True,
                "feedback": "Good choice.",
                "alternative": None,
            }
        # Caption refinement
        elif "caption writer" in system.lower() or "refin" in user.lower():
            return {
                "reasoning": "Good analogy",
                "captions": {"rejected": "Refined A", "preferred": "Refined B"},
            }
        # Meme selection (default)
        else:
            return [
                {
                    "template_name": "Drake Preference",
                    "reasoning": "Classic comparison",
                    "captions": {"rejected": "Stability", "preferred": "New framework"},
                    "modification_needed": False,
                    "rank": 1,
                },
            ]

    mock.query_json.side_effect = side_effect
    return mock


class TestRunPipeline:
    def test_full_pipeline(self, tmp_path):
        script = "00:00 - Intro\n00:10 - There's a new JavaScript framework\n00:20 - Outro"
        config = PipelineConfig(
            density=MemeDensity.MODERATE,
            max_suggestions_per_moment=1,
            enable_critic=True,
            enable_compositing=True,
            template_dir=str(tmp_path / "templates"),
            output_dir=str(tmp_path / "output"),
        )
        db = _make_db()
        llm = _make_mock_llm()

        result = run_pipeline(script, config, db, llm)

        assert len(result.script_lines) == 3
        assert len(result.moments) >= 1
        assert len(result.suggestions) >= 1
        assert len(result.outputs) >= 1
        assert result.config is config

    def test_pipeline_without_critic(self, tmp_path):
        script = "Line one\nLine two"
        config = PipelineConfig(
            enable_critic=False,
            enable_compositing=True,
            template_dir=str(tmp_path / "templates"),
            output_dir=str(tmp_path / "output"),
        )
        llm = _make_mock_llm()

        result = run_pipeline(script, config, meme_db=_make_db(), llm=llm)
        assert result.critiques == []

    def test_pipeline_without_compositing(self):
        script = "Just some text\nMore text"
        config = PipelineConfig(
            enable_critic=False,
            enable_compositing=False,
        )
        llm = _make_mock_llm()

        result = run_pipeline(script, config, meme_db=_make_db(), llm=llm)
        assert all(o.image_path is None for o in result.outputs)

    def test_empty_script(self):
        config = PipelineConfig()
        llm = MagicMock()
        # parse_script returns empty for blank text — no LLM call needed
        result = run_pipeline("", config, llm=llm)
        assert len(result.moments) == 0

    def test_no_moments_detected(self):
        script = "Boring content"
        config = PipelineConfig()
        llm = MagicMock()
        llm.query_json.return_value = []

        result = run_pipeline(script, config, llm=llm)
        assert result.moments == []
        assert result.suggestions == []

    def test_manifest_generation(self, tmp_path):
        script = "Test line\nAnother line"
        config = PipelineConfig(
            enable_critic=False,
            enable_compositing=False,
        )
        llm = _make_mock_llm()
        result = run_pipeline(script, config, meme_db=_make_db(), llm=llm)

        manifest_path = tmp_path / "manifest.json"
        result.save_manifest(manifest_path)

        data = json.loads(manifest_path.read_text())
        assert "memes" in data
        assert "config" in data
        assert isinstance(data["total_memes_output"], int)


class TestRunAnalysisOnly:
    def test_returns_only_moments(self):
        script = "Some test content\nMore content"
        config = PipelineConfig()
        llm = _make_mock_llm()

        result = run_analysis_only(script, config, llm)
        assert len(result.moments) >= 1
        assert result.suggestions == []
        assert result.outputs == []


class TestRunSuggestionsOnly:
    def test_returns_suggestions_without_images(self):
        script = "Test content\nAnother line"
        config = PipelineConfig()
        llm = _make_mock_llm()

        result = run_suggestions_only(script, config, meme_db=_make_db(), llm=llm)
        assert len(result.suggestions) >= 1
        assert all(o.image_path is None for o in result.outputs)
