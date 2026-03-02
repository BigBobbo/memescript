"""Stage 3: Caption refinement — polishing meme captions with chain-of-thought."""

from __future__ import annotations

import logging
from typing import Optional

from .llm import LLMClient
from .meme_db import MemeDatabase
from .models import (
    MemeSuggestion,
    PipelineConfig,
)
from .prompts import CAPTION_REFINEMENT

logger = logging.getLogger(__name__)


def refine_captions(
    suggestions: list[MemeSuggestion],
    config: PipelineConfig,
    meme_db: Optional[MemeDatabase] = None,
    llm: Optional[LLMClient] = None,
) -> list[MemeSuggestion]:
    """Refine captions for meme suggestions using chain-of-thought reasoning.

    Only refines suggestions where a matching template is found in the database,
    since the refinement prompt uses template-specific metadata (humor convention,
    text regions). Suggestions without a template match are passed through unchanged.
    """
    if llm is None:
        llm = LLMClient(model=config.model)

    if meme_db is None or len(meme_db.templates) == 0:
        logger.info("No meme database — skipping caption refinement.")
        return suggestions

    refined = []
    for suggestion in suggestions:
        template = meme_db.fuzzy_match(suggestion.template_name)
        if template is None:
            logger.debug(
                "No template match for '%s' — keeping original captions.",
                suggestion.template_name,
            )
            refined.append(suggestion)
            continue

        try:
            refined_suggestion = _refine_single(suggestion, template, config, llm)
            refined.append(refined_suggestion)
        except Exception as e:
            logger.warning(
                "Caption refinement failed for '%s': %s — keeping original.",
                suggestion.template_name,
                e,
            )
            refined.append(suggestion)

    return refined


def _refine_single(
    suggestion: MemeSuggestion,
    template,
    config: PipelineConfig,
    llm: LLMClient,
) -> MemeSuggestion:
    """Refine captions for a single suggestion."""
    regions_desc = ", ".join(
        f'"{r.label}"' for r in template.text_regions
    )

    import json
    user_prompt = CAPTION_REFINEMENT.format(
        template_name=template.name,
        humor_convention=template.humor_convention,
        regions=regions_desc,
        context_summary=suggestion.moment.context_summary,
        line=suggestion.moment.line,
        current_captions=json.dumps(suggestion.captions),
    )

    result = llm.query_json(
        system="You are a meme caption writer. Return only valid JSON.",
        user=user_prompt,
        temperature=0.8,
    )

    if isinstance(result, dict) and "captions" in result:
        new_captions = result["captions"]
        if isinstance(new_captions, dict) and new_captions:
            logger.info(
                "Refined captions for '%s': %s",
                suggestion.template_name,
                new_captions,
            )
            return MemeSuggestion(
                moment=suggestion.moment,
                template_name=suggestion.template_name,
                captions=new_captions,
                reasoning=result.get("reasoning", suggestion.reasoning),
                modification_needed=suggestion.modification_needed,
                rank=suggestion.rank,
            )

    return suggestion
