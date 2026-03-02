"""Stage 2: Meme selection — matching moments to templates and generating captions."""

from __future__ import annotations

import json
import logging
from typing import Optional

from .llm import LLMClient
from .meme_db import MemeDatabase
from .models import (
    MemeableMoment,
    MemeSuggestion,
    PipelineConfig,
)
from .prompts import (
    MEME_SELECTION_SYSTEM,
    MEME_SELECTION_OPEN,
    MEME_SELECTION_CONSTRAINED,
)

logger = logging.getLogger(__name__)


def select_memes(
    moments: list[MemeableMoment],
    config: PipelineConfig,
    meme_db: Optional[MemeDatabase] = None,
    llm: Optional[LLMClient] = None,
) -> list[MemeSuggestion]:
    """For each meme-worthy moment, generate meme suggestions.

    If a meme database is provided and non-empty, uses constrained selection
    from the library. Otherwise, uses open-ended selection where the LLM
    draws from its general meme knowledge.
    """
    if llm is None:
        llm = LLMClient(model=config.model)

    all_suggestions = []

    for moment in moments:
        logger.info("Selecting memes for: %s", moment.line[:60])
        try:
            suggestions = _select_for_moment(
                moment, config, meme_db, llm
            )
            all_suggestions.extend(suggestions)
        except Exception as e:
            logger.warning("Failed to select memes for moment: %s — %s", moment.line[:60], e)

    return all_suggestions


def _select_for_moment(
    moment: MemeableMoment,
    config: PipelineConfig,
    meme_db: Optional[MemeDatabase],
    llm: LLMClient,
) -> list[MemeSuggestion]:
    """Generate meme suggestions for a single moment."""
    system_prompt = MEME_SELECTION_SYSTEM.format(audience=config.audience)

    # Choose constrained vs open selection
    use_constrained = meme_db is not None and len(meme_db.templates) > 0

    if use_constrained:
        # Try to narrow down relevant templates by emotion/tags
        candidates = meme_db.search_by_emotion(moment.emotional_beat)
        if len(candidates) < 3:
            candidates = meme_db.templates  # fall back to full library

        user_prompt = MEME_SELECTION_CONSTRAINED.format(
            line=moment.line,
            comedy_mechanism=moment.comedy_mechanism,
            subtext=moment.subtext,
            emotional_beat=moment.emotional_beat,
            context_summary=moment.context_summary,
            num_suggestions=config.max_suggestions_per_moment,
            templates_description=meme_db.format_for_prompt(candidates),
        )
    else:
        user_prompt = MEME_SELECTION_OPEN.format(
            line=moment.line,
            comedy_mechanism=moment.comedy_mechanism,
            subtext=moment.subtext,
            emotional_beat=moment.emotional_beat,
            context_summary=moment.context_summary,
            num_suggestions=config.max_suggestions_per_moment,
        )

    raw_suggestions = llm.query_json(system_prompt, user_prompt)

    if not isinstance(raw_suggestions, list):
        raw_suggestions = [raw_suggestions]

    suggestions = []
    for raw in raw_suggestions:
        try:
            suggestion = MemeSuggestion(
                moment=moment,
                template_name=raw["template_name"],
                captions=raw.get("captions", {}),
                reasoning=raw.get("reasoning", ""),
                modification_needed=raw.get("modification_needed", False),
                rank=raw.get("rank", len(suggestions) + 1),
            )
            suggestions.append(suggestion)
        except (KeyError, TypeError) as e:
            logger.warning("Skipping malformed suggestion: %s — %s", raw, e)

    suggestions.sort(key=lambda s: s.rank)
    return suggestions
