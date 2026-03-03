"""Tests for the image compositor (Stage 5)."""

import pytest
from pathlib import Path

from memescript.compositor import (
    _create_plain_background,
    _estimate_duration,
    _make_generic_template,
    _slugify,
    composite_all,
    render_meme,
)
from memescript.meme_db import MemeDatabase
from memescript.models import (
    MemeableMoment,
    MemeFormat,
    MemeSuggestion,
    MemeTemplate,
    PipelineConfig,
    TextRegion,
)


def _make_moment():
    return MemeableMoment(
        line="Test line",
        timestamp="00:15",
        line_index=0,
        comedy_mechanism="irony",
        emotional_beat="smugness",
        subtext="test",
        confidence=0.9,
    )


def _make_suggestion(captions=None, template_name="Drake Preference"):
    return MemeSuggestion(
        moment=_make_moment(),
        template_name=template_name,
        captions=captions or {"rejected": "Old stuff", "preferred": "New stuff"},
        reasoning="Test",
    )


def _make_template():
    return MemeTemplate(
        name="Drake Preference",
        filename="drake.png",
        format=MemeFormat.DRAKE,
        emotions=["smugness"],
        tags=["comparison"],
        humor_convention="Top rejected, bottom preferred",
        text_regions=[
            TextRegion(
                label="rejected", x=400, y=20, width=380, height=280,
                font_size=32, color="white", stroke_color="black", stroke_width=2,
            ),
            TextRegion(
                label="preferred", x=400, y=320, width=380, height=280,
                font_size=32, color="white", stroke_color="black", stroke_width=2,
            ),
        ],
        width=800,
        height=600,
    )


class TestRenderMeme:
    def test_renders_placeholder_when_no_template_image(self, tmp_path):
        suggestion = _make_suggestion()
        template = _make_template()

        output_path = render_meme(
            suggestion=suggestion,
            template=template,
            template_dir=tmp_path / "templates",
            output_dir=tmp_path / "output",
            index=0,
        )

        assert output_path is not None
        assert Path(output_path).exists()
        assert output_path.endswith(".png")

    def test_output_filename_format(self, tmp_path):
        suggestion = _make_suggestion(template_name="Surprised Pikachu")
        template = _make_template()
        template.name = "Surprised Pikachu"

        output_path = render_meme(
            suggestion=suggestion,
            template=template,
            template_dir=tmp_path / "templates",
            output_dir=tmp_path / "output",
            index=5,
        )

        assert "meme_005_" in output_path
        assert "surprised_pikachu" in output_path

    def test_renders_with_empty_captions(self, tmp_path):
        suggestion = _make_suggestion(captions={})
        template = _make_template()

        output_path = render_meme(
            suggestion=suggestion,
            template=template,
            template_dir=tmp_path / "templates",
            output_dir=tmp_path / "output",
            index=0,
        )
        assert output_path is not None
        assert Path(output_path).exists()

    def test_creates_output_directory(self, tmp_path):
        suggestion = _make_suggestion()
        template = _make_template()
        output_dir = tmp_path / "nested" / "output" / "dir"

        output_path = render_meme(
            suggestion=suggestion,
            template=template,
            template_dir=tmp_path,
            output_dir=output_dir,
            index=0,
        )

        assert output_dir.exists()
        assert Path(output_path).exists()

    def test_renders_with_terrain_disabled(self, tmp_path):
        suggestion = _make_suggestion()
        template = _make_template()

        output_path = render_meme(
            suggestion=suggestion,
            template=template,
            template_dir=tmp_path / "templates",
            output_dir=tmp_path / "output",
            index=0,
            enable_terrain=False,
        )

        assert output_path is not None
        assert Path(output_path).exists()

    def test_renders_with_terrain_enabled(self, tmp_path):
        suggestion = _make_suggestion()
        template = _make_template()

        output_path = render_meme(
            suggestion=suggestion,
            template=template,
            template_dir=tmp_path / "templates",
            output_dir=tmp_path / "output",
            index=0,
            enable_terrain=True,
        )

        assert output_path is not None
        assert Path(output_path).exists()


class TestCreatePlainBackground:
    def test_creates_correct_size_image(self):
        template = _make_template()
        img = _create_plain_background(template)
        assert img.size == (800, 600)

    def test_uses_default_size_when_not_set(self):
        template = _make_template()
        template.width = 0
        template.height = 0
        img = _create_plain_background(template)
        assert img.size == (800, 600)


class TestCompositeAll:
    def test_composites_multiple_suggestions(self, tmp_path):
        suggestions = [
            _make_suggestion(captions={"rejected": "A", "preferred": "B"}),
            _make_suggestion(captions={"rejected": "C", "preferred": "D"}),
        ]
        config = PipelineConfig(
            template_dir=str(tmp_path / "templates"),
            output_dir=str(tmp_path / "output"),
        )

        outputs = composite_all(suggestions, config, meme_db=None)
        assert len(outputs) == 2
        assert all(o.image_path is not None for o in outputs)
        assert all(Path(o.image_path).exists() for o in outputs)

    def test_composites_with_db(self, tmp_path):
        db = MemeDatabase()
        db.add(_make_template())

        suggestions = [_make_suggestion()]
        config = PipelineConfig(
            template_dir=str(tmp_path / "templates"),
            output_dir=str(tmp_path / "output"),
        )

        outputs = composite_all(suggestions, config, meme_db=db)
        assert len(outputs) == 1

    def test_output_has_timestamp(self, tmp_path):
        suggestions = [_make_suggestion()]
        config = PipelineConfig(
            template_dir=str(tmp_path / "templates"),
            output_dir=str(tmp_path / "output"),
        )

        outputs = composite_all(suggestions, config)
        assert outputs[0].timestamp_start == "00:15"

    def test_composites_with_terrain_disabled(self, tmp_path):
        suggestions = [_make_suggestion()]
        config = PipelineConfig(
            template_dir=str(tmp_path / "templates"),
            output_dir=str(tmp_path / "output"),
        )

        outputs = composite_all(suggestions, config, enable_terrain=False)
        assert len(outputs) == 1
        assert all(o.image_path is not None for o in outputs)


class TestMakeGenericTemplate:
    def test_two_caption_template(self):
        suggestion = _make_suggestion(captions={"top": "A", "bottom": "B"})
        template = _make_generic_template(suggestion)
        assert len(template.text_regions) == 2
        assert template.text_regions[0].label == "top"
        assert template.text_regions[1].label == "bottom"

    def test_single_caption_template(self):
        suggestion = _make_suggestion(captions={"caption": "Solo text"})
        template = _make_generic_template(suggestion)
        assert len(template.text_regions) == 1

    def test_empty_caption_template(self):
        # Build a suggestion with truly empty captions (override default)
        moment = _make_moment()
        suggestion = MemeSuggestion(
            moment=moment,
            template_name="Empty",
            captions={},
            reasoning="Test",
        )
        template = _make_generic_template(suggestion)
        assert len(template.text_regions) == 0

    def test_three_plus_caption_template(self):
        suggestion = _make_suggestion(
            captions={"a": "1", "b": "2", "c": "3", "d": "4"}
        )
        template = _make_generic_template(suggestion)
        assert len(template.text_regions) == 4


class TestEstimateDuration:
    def test_short_captions(self):
        suggestion = _make_suggestion(captions={"top": "Hi"})
        duration = _estimate_duration(suggestion)
        assert duration == 2.0  # minimum

    def test_long_captions(self):
        suggestion = _make_suggestion(
            captions={"top": "A" * 50, "bottom": "B" * 50}
        )
        duration = _estimate_duration(suggestion)
        assert duration == 5.0  # maximum

    def test_medium_captions(self):
        suggestion = _make_suggestion(
            captions={"top": "Some medium text", "bottom": "More text here"}
        )
        duration = _estimate_duration(suggestion)
        assert 2.0 <= duration <= 5.0


class TestSlugify:
    def test_basic(self):
        assert _slugify("Drake Preference") == "drake_preference"

    def test_special_chars(self):
        assert _slugify("It's the Same Picture!") == "its_the_same_picture"

    def test_truncation(self):
        long_name = "A" * 100
        assert len(_slugify(long_name)) <= 50
