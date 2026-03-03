"""Stage 5: Image compositing — rendering text onto meme templates with Pillow."""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from .meme_db import MemeDatabase
from .models import (
    MemeOutput,
    MemeSuggestion,
    MemeTemplate,
    PipelineConfig,
    TextRegion,
)

logger = logging.getLogger(__name__)

# Fallback: Pillow's built-in default font
_DEFAULT_FONT = None


def _get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Try to load Impact (the classic meme font), fall back to default."""
    font_paths = [
        "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/Impact.ttf",
        "/System/Library/Fonts/Impact.ttf",
        "C:\\Windows\\Fonts\\Impact.ttf",
    ]
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue

    # Last resort: Pillow default
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def render_meme(
    suggestion: MemeSuggestion,
    template: MemeTemplate,
    template_dir: str | Path,
    output_dir: str | Path,
    index: int = 0,
) -> Optional[str]:
    """Render a meme by overlaying captions onto a template image.

    Returns the path to the output image, or None if rendering fails.
    """
    template_dir = Path(template_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    template_path = template_dir / template.filename
    if not template_path.exists():
        logger.warning(
            "Template image not found: %s — generating placeholder.",
            template_path,
        )
        img = _create_placeholder(template, suggestion)
    else:
        img = Image.open(template_path).convert("RGBA")

    # Draw captions onto the image
    draw = ImageDraw.Draw(img)

    for region in template.text_regions:
        caption_text = suggestion.captions.get(region.label, "")
        if not caption_text:
            continue

        _draw_text_in_region(draw, region, caption_text, img.size)

    # Save output
    output_filename = f"meme_{index:03d}_{_slugify(suggestion.template_name)}.png"
    output_path = output_dir / output_filename
    img.save(str(output_path), "PNG")
    logger.info("Rendered meme: %s", output_path)
    return str(output_path)


def _draw_text_in_region(
    draw: ImageDraw.ImageDraw,
    region: TextRegion,
    text: str,
    image_size: tuple[int, int],
) -> None:
    """Draw text within a defined region with meme-style formatting."""
    font_size = region.font_size
    font = _get_font(font_size)

    # Word-wrap to fit region width
    max_chars = max(1, region.width // (font_size // 2))
    wrapped_lines = textwrap.wrap(text.upper(), width=max_chars)

    if not wrapped_lines:
        return

    # Calculate total text height
    line_height = font_size + 4
    total_height = line_height * len(wrapped_lines)

    # Vertical centering within region
    y_start = region.y + (region.height - total_height) // 2
    y_start = max(region.y, y_start)

    for i, line in enumerate(wrapped_lines):
        y = y_start + i * line_height

        # Calculate x position for alignment
        try:
            bbox = font.getbbox(line)
            text_width = bbox[2] - bbox[0]
        except AttributeError:
            text_width = len(line) * (font_size // 2)

        if region.align == "center":
            x = region.x + (region.width - text_width) // 2
        elif region.align == "right":
            x = region.x + region.width - text_width
        else:
            x = region.x

        # Draw stroke/outline
        if region.stroke_width > 0:
            for dx in range(-region.stroke_width, region.stroke_width + 1):
                for dy in range(-region.stroke_width, region.stroke_width + 1):
                    if dx != 0 or dy != 0:
                        draw.text(
                            (x + dx, y + dy),
                            line,
                            font=font,
                            fill=region.stroke_color,
                        )

        # Draw main text
        draw.text((x, y), line, font=font, fill=region.color)


def _create_placeholder(
    template: MemeTemplate,
    suggestion: MemeSuggestion,
) -> Image.Image:
    """Create a placeholder image when the actual template image is not available."""
    width = template.width or 800
    height = template.height or 600
    img = Image.new("RGBA", (width, height), (40, 40, 40, 255))
    draw = ImageDraw.Draw(img)

    # Draw template name watermark
    font = _get_font(20)
    draw.text(
        (10, 10),
        f"[{template.name}]",
        font=font,
        fill=(100, 100, 100),
    )

    # Draw region outlines for debugging
    for region in template.text_regions:
        draw.rectangle(
            [region.x, region.y, region.x + region.width, region.y + region.height],
            outline=(80, 80, 80),
            width=1,
        )

    return img


def composite_all(
    suggestions: list[MemeSuggestion],
    config: PipelineConfig,
    meme_db: Optional[MemeDatabase] = None,
) -> list[MemeOutput]:
    """Render all suggestions and produce MemeOutput objects."""
    outputs = []

    for i, suggestion in enumerate(suggestions):
        # Try to find the matching template
        template = None
        if meme_db:
            template = meme_db.fuzzy_match(suggestion.template_name)

        if template is None:
            # Create a generic template for open-ended suggestions
            template = _make_generic_template(suggestion)

        image_path = render_meme(
            suggestion=suggestion,
            template=template,
            template_dir=config.template_dir,
            output_dir=config.output_dir,
            index=i,
        )

        output = MemeOutput(
            moment=suggestion.moment,
            suggestion=suggestion,
            critique=None,
            image_path=image_path,
            timestamp_start=suggestion.moment.timestamp,
            timestamp_end=None,
            display_duration_sec=_estimate_duration(suggestion),
        )
        outputs.append(output)

    return outputs


def _make_generic_template(suggestion: MemeSuggestion) -> MemeTemplate:
    """Create a generic template with evenly distributed regions for each caption."""
    from .models import MemeFormat

    captions = suggestion.captions
    keys = list(captions.keys())

    template_height = 600
    padding = 20
    gap = 10

    if not keys:
        regions = []
    else:
        num_regions = len(keys)
        available_height = template_height - 2 * padding - gap * (num_regions - 1)
        region_height = max(60, available_height // num_regions)
        font_size = 36 if num_regions <= 2 else 30

        regions = []
        for idx, key in enumerate(keys):
            y_pos = padding + idx * (region_height + gap)
            regions.append(
                TextRegion(
                    label=key, x=20, y=y_pos, width=760, height=region_height,
                    font_size=font_size, color="white", stroke_color="black",
                    stroke_width=3,
                )
            )

    return MemeTemplate(
        name=suggestion.template_name,
        filename=f"{_slugify(suggestion.template_name)}.png",
        format=MemeFormat.TOP_BOTTOM,
        emotions=[suggestion.moment.emotional_beat],
        tags=[],
        humor_convention="Generic top/bottom text meme",
        text_regions=regions,
        width=800,
        height=600,
    )


def _estimate_duration(suggestion: MemeSuggestion) -> float:
    """Estimate how long a meme should be displayed based on text length."""
    total_chars = sum(len(v) for v in suggestion.captions.values())
    # ~15 chars per second reading speed, minimum 2s, max 5s
    return max(2.0, min(5.0, total_chars / 15.0))


def _slugify(text: str) -> str:
    """Convert text to a filename-safe slug."""
    import re
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "_", slug)
    return slug[:50]
