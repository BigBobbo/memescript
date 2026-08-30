"""Tests for the meme template database."""

import json
import pytest

from memescript.meme_db import MemeDatabase
from memescript.models import MemeFormat, MemeTemplate, TextRegion


def _make_template(name="Test Meme", emotions=None, tags=None):
    return MemeTemplate(
        name=name,
        filename=f"{name.lower().replace(' ', '_')}.png",
        format=MemeFormat.TOP_BOTTOM,
        emotions=emotions or ["frustration"],
        tags=tags or ["test"],
        humor_convention="test convention",
        text_regions=[
            TextRegion(label="top", x=0, y=0, width=800, height=300),
            TextRegion(label="bottom", x=0, y=300, width=800, height=300),
        ],
    )


class TestMemeDatabase:
    def test_add_and_get_by_name(self):
        db = MemeDatabase()
        template = _make_template("Drake Preference")
        db.add(template)

        result = db.get_by_name("Drake Preference")
        assert result is not None
        assert result.name == "Drake Preference"

    def test_add_replaces_existing_template(self):
        db = MemeDatabase()
        original = _make_template("Drake Preference", emotions=["frustration"])
        db.add(original)
        assert len(db.templates) == 1

        updated = _make_template("Drake Preference", emotions=["joy"])
        db.add(updated)
        # Should replace, not duplicate
        assert len(db.templates) == 1
        assert db.get_by_name("Drake Preference").emotions == ["joy"]

    def test_add_replaces_case_insensitive(self):
        db = MemeDatabase()
        db.add(_make_template("Drake Preference"))
        db.add(_make_template("drake preference"))
        assert len(db.templates) == 1

    def test_get_by_name_case_insensitive(self):
        db = MemeDatabase()
        db.add(_make_template("Drake Preference"))

        assert db.get_by_name("drake preference") is not None
        assert db.get_by_name("DRAKE PREFERENCE") is not None

    def test_get_by_name_missing(self):
        db = MemeDatabase()
        assert db.get_by_name("nonexistent") is None

    def test_fuzzy_match_exact(self):
        db = MemeDatabase()
        db.add(_make_template("Distracted Boyfriend"))
        assert db.fuzzy_match("Distracted Boyfriend") is not None

    def test_fuzzy_match_substring(self):
        db = MemeDatabase()
        db.add(_make_template("Distracted Boyfriend"))
        result = db.fuzzy_match("Distracted")
        assert result is not None
        assert result.name == "Distracted Boyfriend"

    def test_fuzzy_match_word_overlap(self):
        db = MemeDatabase()
        db.add(_make_template("Drake Preference"))
        db.add(_make_template("Surprised Pikachu"))
        result = db.fuzzy_match("Drake")
        assert result is not None
        assert result.name == "Drake Preference"

    def test_fuzzy_match_no_match(self):
        db = MemeDatabase()
        db.add(_make_template("Test Meme"))
        assert db.fuzzy_match("completely unrelated xyz") is None

    def test_search_by_emotion(self):
        db = MemeDatabase()
        db.add(_make_template("A", emotions=["frustration", "anger"]))
        db.add(_make_template("B", emotions=["joy", "excitement"]))
        db.add(_make_template("C", emotions=["frustration"]))

        results = db.search_by_emotion("frustration")
        assert len(results) == 2
        names = {r.name for r in results}
        assert "A" in names
        assert "C" in names

    def test_search_by_emotion_case_insensitive(self):
        db = MemeDatabase()
        db.add(_make_template("A", emotions=["Horror"]))
        results = db.search_by_emotion("horror")
        assert len(results) == 1

    def test_search_by_tags(self):
        db = MemeDatabase()
        db.add(_make_template("A", tags=["comparison", "choice"]))
        db.add(_make_template("B", tags=["disaster", "fire"]))
        db.add(_make_template("C", tags=["comparison", "identical"]))

        results = db.search_by_tags(["comparison"])
        assert len(results) == 2

    def test_search_by_tags_multiple(self):
        db = MemeDatabase()
        db.add(_make_template("A", tags=["x"]))
        db.add(_make_template("B", tags=["y"]))
        db.add(_make_template("C", tags=["z"]))

        results = db.search_by_tags(["x", "y"])
        assert len(results) == 2

    def test_format_for_prompt(self):
        db = MemeDatabase()
        db.add(_make_template("Test Meme"))
        text = db.format_for_prompt()
        assert "Test Meme" in text
        assert "top" in text
        assert "test convention" in text

    def test_load_from_file(self, tmp_path):
        registry = {
            "templates": [
                {
                    "name": "Test",
                    "filename": "test.png",
                    "format": "top_bottom",
                    "emotions": ["joy"],
                    "tags": ["happy"],
                    "humor_convention": "happy stuff",
                    "text_regions": [
                        {"label": "top", "x": 0, "y": 0, "width": 800, "height": 300},
                    ],
                }
            ]
        }
        path = tmp_path / "registry.json"
        path.write_text(json.dumps(registry))

        db = MemeDatabase.load_from_file(path)
        assert len(db.templates) == 1
        assert db.templates[0].name == "Test"

    def test_load_from_missing_file(self, tmp_path):
        db = MemeDatabase.load_from_file(tmp_path / "nonexistent.json")
        assert len(db.templates) == 0

    def test_save_to_file(self, tmp_path):
        db = MemeDatabase()
        db.add(_make_template("Saved Meme"))
        path = tmp_path / "output.json"
        db.save_to_file(path)

        assert path.exists()
        data = json.loads(path.read_text())
        assert len(data["templates"]) == 1
        assert data["templates"][0]["name"] == "Saved Meme"

    def test_load_default_registry(self):
        """Test loading the actual default registry file."""
        from memescript.meme_db import get_default_database
        db = get_default_database()
        assert len(db.templates) > 0
        # Verify some expected templates exist
        names = {t.name for t in db.templates}
        assert "Drake Preference" in names
        assert "This Is Fine" in names
        assert "Surprised Pikachu" in names
