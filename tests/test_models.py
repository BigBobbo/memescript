"""Tests for data models."""

import json
import pytest

from memescript.models import (
    ComedyMechanism,
    CritiqueResult,
    EmotionalBeat,
    MemeDensity,
    MemeFormat,
    MemeOutput,
    MemeTemplate,
    MemeableMoment,
    MemeSuggestion,
    PipelineConfig,
    PipelineResult,
    ScriptLine,
    TextRegion,
)


class TestTextRegion:
    def test_defaults(self):
        region = TextRegion(label="top", x=0, y=0, width=100, height=50)
        assert region.font_size == 32
        assert region.color == "white"
        assert region.stroke_color == "black"
        assert region.align == "center"


class TestMemeTemplate:
    def test_to_dict_roundtrip(self):
        template = MemeTemplate(
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
        )
        d = template.to_dict()
        assert d["name"] == "Drake Preference"
        assert d["format"] == "drake"
        assert len(d["text_regions"]) == 2

    def test_from_dict(self):
        data = {
            "name": "Test Meme",
            "filename": "test.png",
            "format": "top_bottom",
            "emotions": ["frustration"],
            "tags": ["test"],
            "humor_convention": "Top and bottom text",
            "text_regions": [
                {"label": "top", "x": 0, "y": 0, "width": 800, "height": 200},
            ],
            "width": 800,
            "height": 600,
            "year_origin": 2020,
            "is_classic": False,
        }
        template = MemeTemplate.from_dict(data)
        assert template.name == "Test Meme"
        assert template.format == MemeFormat.TOP_BOTTOM
        assert len(template.text_regions) == 1
        assert template.text_regions[0].label == "top"

    def test_from_dict_with_extra_region_fields(self):
        data = {
            "name": "Full Region",
            "filename": "full.png",
            "format": "single_caption",
            "emotions": [],
            "tags": [],
            "humor_convention": "test",
            "text_regions": [
                {
                    "label": "caption",
                    "x": 10,
                    "y": 20,
                    "width": 300,
                    "height": 100,
                    "font_size": 48,
                    "color": "yellow",
                    "stroke_color": "red",
                    "stroke_width": 5,
                    "align": "left",
                },
            ],
        }
        template = MemeTemplate.from_dict(data)
        region = template.text_regions[0]
        assert region.font_size == 48
        assert region.color == "yellow"
        assert region.align == "left"


class TestMemeableMoment:
    def test_creation(self):
        moment = MemeableMoment(
            line="JavaScript is great",
            timestamp="00:15",
            line_index=3,
            comedy_mechanism="irony",
            emotional_beat="smugness",
            subtext="No it isn't",
            confidence=0.9,
        )
        assert moment.confidence == 0.9
        assert moment.comedy_mechanism == "irony"

    def test_to_dict(self):
        moment = MemeableMoment(
            line="test", timestamp=None, line_index=0,
            comedy_mechanism="pain", emotional_beat="frustration",
            subtext="sub", confidence=0.5,
        )
        d = moment.to_dict()
        assert d["line"] == "test"
        assert d["timestamp"] is None

    def test_from_dict(self):
        data = {
            "line": "test line",
            "timestamp": "01:00",
            "line_index": 5,
            "comedy_mechanism": "absurdity",
            "emotional_beat": "horror",
            "subtext": "oh no",
            "confidence": 0.8,
        }
        moment = MemeableMoment.from_dict(data)
        assert moment.line == "test line"
        assert moment.line_index == 5

    def test_from_dict_ignores_extra_keys(self):
        data = {
            "line": "test",
            "timestamp": None,
            "line_index": 0,
            "comedy_mechanism": "irony",
            "emotional_beat": "frustration",
            "subtext": "sub",
            "confidence": 0.5,
            "extra_field": "ignored",
        }
        moment = MemeableMoment.from_dict(data)
        assert moment.line == "test"


class TestMemeSuggestion:
    def _make_moment(self):
        return MemeableMoment(
            line="test", timestamp=None, line_index=0,
            comedy_mechanism="irony", emotional_beat="smugness",
            subtext="sub", confidence=0.8,
        )

    def test_creation(self):
        suggestion = MemeSuggestion(
            moment=self._make_moment(),
            template_name="Drake Preference",
            captions={"rejected": "Testing", "preferred": "Not testing"},
            reasoning="Classic choice meme",
        )
        assert suggestion.rank == 1
        assert not suggestion.modification_needed

    def test_to_dict(self):
        suggestion = MemeSuggestion(
            moment=self._make_moment(),
            template_name="This Is Fine",
            captions={"caption": "Everything is on fire"},
            reasoning="Perfect for chaos",
        )
        d = suggestion.to_dict()
        assert d["template_name"] == "This Is Fine"
        assert d["moment"]["line"] == "test"


class TestCritiqueResult:
    def _make_suggestion(self):
        moment = MemeableMoment(
            line="test", timestamp=None, line_index=0,
            comedy_mechanism="irony", emotional_beat="smugness",
            subtext="sub", confidence=0.8,
        )
        return MemeSuggestion(
            moment=moment,
            template_name="Test",
            captions={"top": "A"},
            reasoning="test",
        )

    def test_is_good_enough_passing(self):
        critique = CritiqueResult(
            suggestion=self._make_suggestion(),
            surprise_score=4, relevance_score=4,
            timing_score=4, freshness_score=4,
            passes_layer_test=True, overall_score=4.0,
        )
        assert critique.is_good_enough

    def test_is_good_enough_failing_score(self):
        critique = CritiqueResult(
            suggestion=self._make_suggestion(),
            surprise_score=2, relevance_score=2,
            timing_score=2, freshness_score=2,
            passes_layer_test=True, overall_score=2.0,
        )
        assert not critique.is_good_enough

    def test_is_good_enough_failing_layer_test(self):
        critique = CritiqueResult(
            suggestion=self._make_suggestion(),
            surprise_score=5, relevance_score=5,
            timing_score=5, freshness_score=5,
            passes_layer_test=False, overall_score=5.0,
        )
        assert not critique.is_good_enough


class TestPipelineConfig:
    def test_defaults(self):
        config = PipelineConfig()
        assert config.density == MemeDensity.MODERATE
        assert config.max_suggestions_per_moment == 3
        assert config.enable_critic is True

    def test_to_dict(self):
        config = PipelineConfig(density=MemeDensity.FIRESHIP)
        d = config.to_dict()
        assert d["density"] == "fireship"


class TestPipelineResult:
    def test_to_manifest(self):
        config = PipelineConfig()
        result = PipelineResult(
            script_lines=[],
            moments=[],
            suggestions=[],
            critiques=[],
            outputs=[],
            config=config,
        )
        manifest = result.to_manifest()
        assert manifest["total_moments_detected"] == 0
        assert manifest["total_memes_output"] == 0
        assert manifest["memes"] == []

    def test_save_manifest(self, tmp_path):
        config = PipelineConfig()
        result = PipelineResult(
            script_lines=[],
            moments=[],
            suggestions=[],
            critiques=[],
            outputs=[],
            config=config,
        )
        manifest_path = tmp_path / "manifest.json"
        result.save_manifest(manifest_path)
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert "memes" in data


class TestEnums:
    def test_comedy_mechanism_values(self):
        assert ComedyMechanism.IRONY.value == "irony"
        assert ComedyMechanism.ESCALATION.value == "escalation"

    def test_emotional_beat_values(self):
        assert EmotionalBeat.HORROR.value == "horror"
        assert EmotionalBeat.DREAD.value == "dread"

    def test_meme_density_values(self):
        assert MemeDensity.SPARSE.value == "sparse"
        assert MemeDensity.FIRESHIP.value == "fireship"

    def test_meme_format_values(self):
        assert MemeFormat.DRAKE.value == "drake"
        assert MemeFormat.TOP_BOTTOM.value == "top_bottom"
