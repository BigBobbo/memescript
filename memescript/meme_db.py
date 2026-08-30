"""Meme template database — loading, searching, and matching."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from .models import MemeTemplate, MemeFormat, TextRegion

logger = logging.getLogger(__name__)

# Default registry path relative to this module
DEFAULT_REGISTRY = Path(__file__).parent.parent / "meme_templates" / "registry.json"


class MemeDatabase:
    """In-memory database of meme templates with search capabilities."""

    def __init__(self, templates: list[MemeTemplate] | None = None):
        self.templates: list[MemeTemplate] = templates or []
        self._by_name: dict[str, MemeTemplate] = {}
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        self._by_name = {t.name.lower(): t for t in self.templates}

    def add(self, template: MemeTemplate) -> None:
        name_lower = template.name.lower()
        # Replace existing template with the same name instead of duplicating
        for i, existing in enumerate(self.templates):
            if existing.name.lower() == name_lower:
                self.templates[i] = template
                self._by_name[name_lower] = template
                return
        self.templates.append(template)
        self._by_name[name_lower] = template

    def get_by_name(self, name: str) -> Optional[MemeTemplate]:
        """Exact name lookup (case-insensitive)."""
        return self._by_name.get(name.lower())

    def fuzzy_match(self, name: str) -> Optional[MemeTemplate]:
        """Find the closest template by name (case-insensitive substring match)."""
        name_lower = name.lower()

        # Exact match first
        if name_lower in self._by_name:
            return self._by_name[name_lower]

        # Substring match
        for key, template in self._by_name.items():
            if name_lower in key or key in name_lower:
                return template

        # Word overlap match
        name_words = set(name_lower.split())
        best_match = None
        best_overlap = 0
        for key, template in self._by_name.items():
            key_words = set(key.split())
            overlap = len(name_words & key_words)
            if overlap > best_overlap:
                best_overlap = overlap
                best_match = template

        return best_match if best_overlap > 0 else None

    def search_by_emotion(self, emotion: str) -> list[MemeTemplate]:
        """Find templates matching a given emotion."""
        emotion_lower = emotion.lower()
        return [
            t for t in self.templates
            if any(emotion_lower in e.lower() for e in t.emotions)
        ]

    def search_by_tags(self, tags: list[str]) -> list[MemeTemplate]:
        """Find templates matching any of the given tags."""
        tag_set = {t.lower() for t in tags}
        results = []
        for template in self.templates:
            template_tags = {t.lower() for t in template.tags}
            if tag_set & template_tags:
                results.append(template)
        return results

    def format_for_prompt(self, templates: list[MemeTemplate] | None = None) -> str:
        """Format templates as a structured description for LLM prompts."""
        templates = templates or self.templates
        parts = []
        for t in templates:
            regions_desc = ", ".join(
                f'"{r.label}"' for r in t.text_regions
            )
            parts.append(
                f"- Name: {t.name}\n"
                f"  Format: {t.format.value}\n"
                f"  Structure: {t.humor_convention}\n"
                f"  Emotional register: {', '.join(t.emotions)}\n"
                f"  Customizable text regions: [{regions_desc}]\n"
                f"  Typical uses: {', '.join(t.typical_uses[:3])}"
            )
        return "\n\n".join(parts)

    @classmethod
    def load_from_file(cls, path: str | Path) -> MemeDatabase:
        """Load templates from a JSON registry file."""
        path = Path(path)
        if not path.exists():
            logger.warning("Registry file not found: %s — using empty database", path)
            return cls()

        with open(path) as f:
            data = json.load(f)

        templates = []
        for entry in data.get("templates", []):
            try:
                templates.append(MemeTemplate.from_dict(entry))
            except (KeyError, TypeError, ValueError) as e:
                logger.warning("Skipping malformed template: %s — %s", entry.get("name"), e)

        db = cls(templates)
        logger.info("Loaded %d meme templates from %s", len(templates), path)
        return db

    def save_to_file(self, path: str | Path) -> None:
        """Save templates to a JSON registry file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"templates": [t.to_dict() for t in self.templates]}
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)


def get_default_database() -> MemeDatabase:
    """Load the default meme template database."""
    return MemeDatabase.load_from_file(DEFAULT_REGISTRY)
