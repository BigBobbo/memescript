"""Data models for the MemeScript pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional


class ComedyMechanism(str, Enum):
    IRONY = "irony"
    PAIN = "pain"
    ABSURDITY = "absurdity"
    HUBRIS = "hubris"
    CONTRAST = "contrast"
    UNDERSTATEMENT = "understatement"
    CALLBACK = "callback"
    ESCALATION = "escalation"
    SARCASM = "sarcasm"
    FLEX = "flex"


class EmotionalBeat(str, Enum):
    FRUSTRATION = "frustration"
    SMUGNESS = "smugness"
    HORROR = "horror"
    DISBELIEF = "disbelief"
    RESIGNATION = "resignation"
    EXCITEMENT = "excitement"
    CONFUSION = "confusion"
    NOSTALGIA = "nostalgia"
    TRIUMPH = "triumph"
    DREAD = "dread"


class MemeDensity(str, Enum):
    SPARSE = "sparse"       # ~1 meme per 2-3 minutes
    MODERATE = "moderate"   # ~1 per 45-60 seconds
    FIRESHIP = "fireship"   # maximum density


class MemeFormat(str, Enum):
    TWO_PANEL = "two_panel"
    THREE_LABEL = "three_label"
    SINGLE_CAPTION = "single_caption"
    TOP_BOTTOM = "top_bottom"
    MULTI_PANEL = "multi_panel"
    EXPANDING_BRAIN = "expanding_brain"
    DRAKE = "drake"
    REACTION = "reaction"
    CUSTOM = "custom"


@dataclass
class TextRegion:
    """A region on a meme template where text can be placed."""
    label: str
    x: int
    y: int
    width: int
    height: int
    font_size: int = 32
    color: str = "white"
    stroke_color: str = "black"
    stroke_width: int = 2
    align: str = "center"


@dataclass
class MemeTemplate:
    """A meme template with metadata for matching and compositing."""
    name: str
    filename: str
    format: MemeFormat
    emotions: list[str]
    tags: list[str]
    humor_convention: str
    text_regions: list[TextRegion]
    typical_uses: list[str] = field(default_factory=list)
    width: int = 800
    height: int = 600
    year_origin: int = 2010
    is_classic: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> MemeTemplate:
        data = data.copy()
        data["format"] = MemeFormat(data["format"])
        data["text_regions"] = [
            TextRegion(**r) if isinstance(r, dict) else r
            for r in data.get("text_regions", [])
        ]
        return cls(**data)


@dataclass
class ScriptLine:
    """A single line/segment from the video script."""
    text: str
    timestamp: Optional[str] = None
    index: int = 0


@dataclass
class MemeableMoment:
    """A moment in the script identified as having meme potential."""
    line: str
    timestamp: Optional[str]
    line_index: int
    comedy_mechanism: str
    emotional_beat: str
    subtext: str
    confidence: float  # 0.0 - 1.0
    context_summary: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> MemeableMoment:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class MemeSuggestion:
    """A specific meme suggestion for a moment."""
    moment: MemeableMoment
    template_name: str
    captions: dict[str, str]  # region_label -> caption text
    reasoning: str
    modification_needed: bool = False
    rank: int = 1

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> MemeSuggestion:
        data = data.copy()
        if isinstance(data.get("moment"), dict):
            data["moment"] = MemeableMoment.from_dict(data["moment"])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CritiqueResult:
    """Quality assessment of a meme suggestion."""
    suggestion: MemeSuggestion
    surprise_score: int      # 1-5
    relevance_score: int     # 1-5
    timing_score: int        # 1-5
    freshness_score: int     # 1-5
    passes_layer_test: bool
    overall_score: float     # computed average
    feedback: str = ""
    alternative: Optional[MemeSuggestion] = None

    @property
    def is_good_enough(self) -> bool:
        return self.passes_layer_test and self.overall_score >= 3.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MemeOutput:
    """Final output: a rendered meme tied to a script timestamp."""
    moment: MemeableMoment
    suggestion: MemeSuggestion
    critique: Optional[CritiqueResult]
    image_path: Optional[str]
    timestamp_start: Optional[str]
    timestamp_end: Optional[str]
    display_duration_sec: float = 3.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PipelineConfig:
    """Configuration for the full pipeline."""
    density: MemeDensity = MemeDensity.MODERATE
    max_suggestions_per_moment: int = 3
    quality_threshold: float = 3.0
    enable_critic: bool = True
    enable_compositing: bool = True
    enable_terrain: bool = True
    template_dir: str = "meme_templates"
    output_dir: str = "output"
    model: str = "claude-sonnet-4-20250514"
    audience: str = (
        "mid-to-senior developers, very online, aware of tech Twitter drama, "
        "slightly cynical about hype cycles, appreciate dry humor and absurdist takes"
    )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["density"] = self.density.value
        return d


@dataclass
class PipelineResult:
    """Full result from the meme generation pipeline."""
    script_lines: list[ScriptLine]
    moments: list[MemeableMoment]
    suggestions: list[MemeSuggestion]
    critiques: list[CritiqueResult]
    outputs: list[MemeOutput]
    config: PipelineConfig

    def to_manifest(self) -> dict:
        return {
            "config": self.config.to_dict(),
            "total_moments_detected": len(self.moments),
            "total_suggestions_generated": len(self.suggestions),
            "total_memes_output": len(self.outputs),
            "memes": [o.to_dict() for o in self.outputs],
        }

    def save_manifest(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_manifest(), f, indent=2, default=str)
