"""Stage 4: The Meme Doctor — quality control and critique of meme suggestions."""

from __future__ import annotations

import json
import logging
from typing import Optional

from .llm import LLMClient
from .models import (
    CritiqueResult,
    MemeableMoment,
    MemeSuggestion,
    PipelineConfig,
)
from .prompts import CRITIC_SYSTEM, CRITIC_USER

logger = logging.getLogger(__name__)


def critique_suggestions(
    suggestions: list[MemeSuggestion],
    config: PipelineConfig,
    llm: Optional[LLMClient] = None,
) -> list[CritiqueResult]:
    """Evaluate meme suggestions and return quality critiques.

    Uses a separate LLM pass with a "meme critic" persona to rate
    each suggestion on surprise, relevance, timing, freshness,
    and whether it passes the "layer test" (adds meaning vs. illustrates).
    """
    if llm is None:
        llm = LLMClient(model=config.model)

    critiques = []
    for suggestion in suggestions:
        try:
            critique = _critique_single(suggestion, config, llm)
            critiques.append(critique)
        except Exception as e:
            logger.warning(
                "Critique failed for '%s': %s — assigning neutral score.",
                suggestion.template_name,
                e,
            )
            critiques.append(_neutral_critique(suggestion))

    return critiques


def _critique_single(
    suggestion: MemeSuggestion,
    config: PipelineConfig,
    llm: LLMClient,
) -> CritiqueResult:
    """Critique a single meme suggestion."""
    moment = suggestion.moment

    user_prompt = CRITIC_USER.format(
        line=moment.line,
        template_name=suggestion.template_name,
        captions=json.dumps(suggestion.captions),
        reasoning=suggestion.reasoning,
        comedy_mechanism=moment.comedy_mechanism,
        emotional_beat=moment.emotional_beat,
        subtext=moment.subtext,
    )

    result = llm.query_json(CRITIC_SYSTEM, user_prompt, temperature=0.5)

    surprise = int(result.get("surprise_score", 3))
    relevance = int(result.get("relevance_score", 3))
    timing = int(result.get("timing_score", 3))
    freshness = int(result.get("freshness_score", 3))
    passes = bool(result.get("passes_layer_test", True))
    feedback = result.get("feedback", "")

    overall = (surprise + relevance + timing + freshness) / 4.0

    # Parse alternative if provided
    alternative = None
    raw_alt = result.get("alternative")
    if raw_alt and isinstance(raw_alt, dict):
        try:
            alternative = MemeSuggestion(
                moment=moment,
                template_name=raw_alt["template_name"],
                captions=raw_alt.get("captions", {}),
                reasoning=raw_alt.get("reasoning", ""),
                modification_needed=False,
                rank=0,
            )
        except (KeyError, TypeError):
            pass

    critique = CritiqueResult(
        suggestion=suggestion,
        surprise_score=surprise,
        relevance_score=relevance,
        timing_score=timing,
        freshness_score=freshness,
        passes_layer_test=passes,
        overall_score=overall,
        feedback=feedback,
        alternative=alternative,
    )

    logger.info(
        "Critique for '%s': overall=%.1f, layer_test=%s — %s",
        suggestion.template_name,
        overall,
        passes,
        feedback[:80],
    )

    return critique


def _neutral_critique(suggestion: MemeSuggestion) -> CritiqueResult:
    """Create a neutral (passing) critique when the real one fails."""
    return CritiqueResult(
        suggestion=suggestion,
        surprise_score=3,
        relevance_score=3,
        timing_score=3,
        freshness_score=3,
        passes_layer_test=True,
        overall_score=3.0,
        feedback="Critique unavailable — defaulting to neutral score.",
    )


def filter_by_quality(
    suggestions: list[MemeSuggestion],
    critiques: list[CritiqueResult],
    config: PipelineConfig,
) -> tuple[list[MemeSuggestion], list[CritiqueResult]]:
    """Filter suggestions to keep only those meeting quality threshold.

    For each moment, keeps the best suggestion (preferring critic alternatives
    when the original fails quality checks).
    """
    # Build critique lookup
    critique_map: dict[int, CritiqueResult] = {}
    for critique in critiques:
        key = id(critique.suggestion)
        critique_map[key] = critique

    # Group suggestions by moment
    moment_groups: dict[int, list[MemeSuggestion]] = {}
    for suggestion in suggestions:
        moment_key = suggestion.moment.line_index
        if moment_key not in moment_groups:
            moment_groups[moment_key] = []
        moment_groups[moment_key].append(suggestion)

    filtered_suggestions = []
    filtered_critiques = []

    for moment_key, group in moment_groups.items():
        best_suggestion = None
        best_critique = None
        best_score = -1.0

        for suggestion in group:
            critique = critique_map.get(id(suggestion))
            if critique is None:
                continue

            # If critique suggests an alternative and original is weak, use alternative
            if not critique.is_good_enough and critique.alternative:
                candidate = critique.alternative
                score = config.quality_threshold  # give it a fair chance
            else:
                candidate = suggestion
                score = critique.overall_score

            if score > best_score:
                best_score = score
                best_suggestion = candidate
                best_critique = critique

        if best_suggestion and best_score >= config.quality_threshold:
            filtered_suggestions.append(best_suggestion)
            if best_critique:
                filtered_critiques.append(best_critique)

    logger.info(
        "Quality filter: %d/%d suggestions passed (threshold=%.1f).",
        len(filtered_suggestions),
        len(suggestions),
        config.quality_threshold,
    )

    return filtered_suggestions, filtered_critiques
