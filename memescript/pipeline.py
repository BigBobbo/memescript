"""Pipeline orchestrator — ties all stages together."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from .analyzer import analyze_script, parse_script
from .captioner import refine_captions
from .compositor import composite_all
from .critic import critique_suggestions, filter_by_quality
from .llm import LLMClient
from .meme_db import MemeDatabase, get_default_database
from .models import (
    MemeOutput,
    PipelineConfig,
    PipelineResult,
)
from .selector import select_memes

logger = logging.getLogger(__name__)


def run_pipeline(
    script: str,
    config: Optional[PipelineConfig] = None,
    meme_db: Optional[MemeDatabase] = None,
    llm: Optional[LLMClient] = None,
) -> PipelineResult:
    """Run the full meme generation pipeline on a script.

    Stages:
        1. Parse and analyze script for meme-worthy moments
        2. Select meme templates and generate captions
        3. Refine captions with chain-of-thought
        4. Critique suggestions (optional, controlled by config)
        5. Render meme images (optional, controlled by config)

    Args:
        script: Raw script text (with optional timestamps).
        config: Pipeline configuration. Defaults to moderate density.
        meme_db: Meme template database. Loads default if not provided.
        llm: LLM client. Created from config if not provided.

    Returns:
        PipelineResult with all intermediate and final outputs.
    """
    if config is None:
        config = PipelineConfig()

    if meme_db is None:
        meme_db = get_default_database()

    if llm is None:
        llm = LLMClient(model=config.model)

    # Stage 1: Script analysis
    logger.info("=== Stage 1: Script Analysis ===")
    lines = parse_script(script)
    moments = analyze_script(lines, config, llm)

    if not moments:
        logger.warning("No meme-worthy moments detected. Returning empty result.")
        return PipelineResult(
            script_lines=lines,
            moments=[],
            suggestions=[],
            critiques=[],
            outputs=[],
            config=config,
        )

    # Stage 2: Meme selection
    logger.info("=== Stage 2: Meme Selection ===")
    suggestions = select_memes(moments, config, meme_db, llm)

    if not suggestions:
        logger.warning("No meme suggestions generated.")
        return PipelineResult(
            script_lines=lines,
            moments=moments,
            suggestions=[],
            critiques=[],
            outputs=[],
            config=config,
        )

    # Stage 3: Caption refinement
    logger.info("=== Stage 3: Caption Refinement ===")
    suggestions = refine_captions(suggestions, config, meme_db, llm)

    # Stage 4: Quality critique
    critiques = []
    if config.enable_critic:
        logger.info("=== Stage 4: Quality Critique ===")
        critiques = critique_suggestions(suggestions, config, llm)
        suggestions, critiques = filter_by_quality(suggestions, critiques, config)

    # Stage 5: Image compositing
    outputs = []
    if config.enable_compositing:
        logger.info("=== Stage 5: Image Compositing ===")
        outputs = composite_all(suggestions, config, meme_db, config.enable_terrain)

        # Attach critiques to outputs
        critique_map = {id(c.suggestion): c for c in critiques}
        for output in outputs:
            output.critique = critique_map.get(id(output.suggestion))
    else:
        # Create outputs without images
        for suggestion in suggestions:
            outputs.append(
                MemeOutput(
                    moment=suggestion.moment,
                    suggestion=suggestion,
                    critique=None,
                    image_path=None,
                    timestamp_start=suggestion.moment.timestamp,
                    timestamp_end=None,
                )
            )

    result = PipelineResult(
        script_lines=lines,
        moments=moments,
        suggestions=suggestions,
        critiques=critiques,
        outputs=outputs,
        config=config,
    )

    logger.info(
        "Pipeline complete: %d moments → %d suggestions → %d outputs",
        len(moments),
        len(suggestions),
        len(outputs),
    )

    return result


def run_analysis_only(
    script: str,
    config: Optional[PipelineConfig] = None,
    llm: Optional[LLMClient] = None,
) -> PipelineResult:
    """Run only the analysis stage — identify moments, no meme generation."""
    if config is None:
        config = PipelineConfig()
    if llm is None:
        llm = LLMClient(model=config.model)

    lines = parse_script(script)
    moments = analyze_script(lines, config, llm)

    return PipelineResult(
        script_lines=lines,
        moments=moments,
        suggestions=[],
        critiques=[],
        outputs=[],
        config=config,
    )


def run_suggestions_only(
    script: str,
    config: Optional[PipelineConfig] = None,
    meme_db: Optional[MemeDatabase] = None,
    llm: Optional[LLMClient] = None,
) -> PipelineResult:
    """Run analysis + selection, but skip compositing.

    Useful for generating a meme plan without rendering images.
    """
    if config is None:
        config = PipelineConfig()
    config.enable_compositing = False

    return run_pipeline(script, config, meme_db, llm)
