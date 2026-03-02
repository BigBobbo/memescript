"""Stage 1: Script analysis and comedic beat detection."""

from __future__ import annotations

import logging
import re
from typing import Optional

from .llm import LLMClient
from .models import (
    MemeableMoment,
    MemeDensity,
    PipelineConfig,
    ScriptLine,
)
from .prompts import SCRIPT_ANALYSIS_SYSTEM, SCRIPT_ANALYSIS_USER

logger = logging.getLogger(__name__)

# Matches lines like "00:00 - Some text" or "[01:23] Some text" or "1:23 Some text"
TIMESTAMP_PATTERN = re.compile(
    r"^[\[\(]?(\d{1,2}:\d{2}(?::\d{2})?)[\]\)]?\s*[-–—]?\s*(.*)"
)


def parse_script(raw_script: str) -> list[ScriptLine]:
    """Parse a raw script string into structured ScriptLine objects.

    Supports optional timestamps in formats like:
        00:00 - Introduction to the topic
        [01:23] This is another line
        1:45 And yet another
    """
    lines = []
    for i, raw_line in enumerate(raw_script.strip().splitlines()):
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        match = TIMESTAMP_PATTERN.match(raw_line)
        if match:
            timestamp = match.group(1)
            text = match.group(2).strip()
        else:
            timestamp = None
            text = raw_line

        if text:
            lines.append(ScriptLine(text=text, timestamp=timestamp, index=i))

    return lines


def format_script_for_analysis(lines: list[ScriptLine]) -> str:
    """Format script lines into a numbered string for LLM analysis."""
    parts = []
    for line in lines:
        prefix = f"[{line.timestamp}] " if line.timestamp else ""
        parts.append(f"{line.index}: {prefix}{line.text}")
    return "\n".join(parts)


def analyze_script(
    lines: list[ScriptLine],
    config: PipelineConfig,
    llm: Optional[LLMClient] = None,
) -> list[MemeableMoment]:
    """Analyze script lines and identify meme-worthy moments.

    Stage 1 of the pipeline: reads the script and flags moments with
    comedic potential using an LLM.
    """
    if not lines:
        logger.info("Empty script — no moments to detect.")
        return []

    if llm is None:
        llm = LLMClient(model=config.model)

    formatted_script = format_script_for_analysis(lines)

    system_prompt = SCRIPT_ANALYSIS_SYSTEM.format(
        audience=config.audience,
        density=config.density.value,
    )
    user_prompt = SCRIPT_ANALYSIS_USER.format(script=formatted_script)

    logger.info("Analyzing script (%d lines) for meme-worthy moments...", len(lines))
    raw_moments = llm.query_json(system_prompt, user_prompt)

    if not isinstance(raw_moments, list):
        raw_moments = [raw_moments]

    moments = []
    for raw in raw_moments:
        try:
            moment = MemeableMoment(
                line=raw["line"],
                timestamp=raw.get("timestamp"),
                line_index=raw.get("line_index", 0),
                comedy_mechanism=raw.get("comedy_mechanism", "irony"),
                emotional_beat=raw.get("emotional_beat", "frustration"),
                subtext=raw.get("subtext", ""),
                confidence=float(raw.get("confidence", 0.5)),
                context_summary=raw.get("context_summary", ""),
            )
            moments.append(moment)
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("Skipping malformed moment: %s — %s", raw, e)

    # Sort by confidence descending
    moments.sort(key=lambda m: m.confidence, reverse=True)

    # Apply density filtering
    max_moments = _density_to_max_count(config.density, len(lines))
    if len(moments) > max_moments:
        logger.info(
            "Trimming from %d to %d moments (density=%s)",
            len(moments),
            max_moments,
            config.density.value,
        )
        moments = moments[:max_moments]

    logger.info("Identified %d meme-worthy moments.", len(moments))
    return moments


def _density_to_max_count(density: MemeDensity, num_lines: int) -> int:
    """Estimate max memes based on density and script length."""
    # Rough heuristic: assume ~2-3 seconds per line
    if density == MemeDensity.SPARSE:
        return max(1, num_lines // 10)
    elif density == MemeDensity.MODERATE:
        return max(2, num_lines // 5)
    else:  # FIRESHIP
        return max(3, num_lines // 2)
