"""Interactive terminal preview mode for MemeScript with hotkey support.

Provides a curses-based TUI that lets users browse rendered memes and toggle
display settings (like terrain) via keyboard hotkeys instead of CLI flags.
"""

from __future__ import annotations

import curses
import logging
import textwrap
from pathlib import Path
from typing import Optional

from .compositor import render_meme, _make_generic_template
from .hotkeys import HotkeyRegistry, build_default_registry, format_hotkey_menu
from .meme_db import MemeDatabase
from .models import MemeOutput, PipelineConfig, PipelineResult

logger = logging.getLogger(__name__)


class PreviewState:
    """Mutable state for the interactive preview session."""

    def __init__(self, result: PipelineResult, config: PipelineConfig) -> None:
        self.result = result
        self.config = config
        self.current_index: int = 0
        self.enable_terrain: bool = config.enable_terrain
        self.show_hotkey_menu: bool = False
        self.should_quit: bool = False
        self.status_message: str = ""

    @property
    def total(self) -> int:
        return len(self.result.outputs)

    @property
    def current_output(self) -> Optional[MemeOutput]:
        if 0 <= self.current_index < self.total:
            return self.result.outputs[self.current_index]
        return None


def run_preview(
    result: PipelineResult,
    config: PipelineConfig,
    meme_db: Optional[MemeDatabase] = None,
    registry: Optional[HotkeyRegistry] = None,
) -> None:
    """Launch the interactive preview mode.

    Args:
        result: Pipeline result containing rendered memes.
        config: Pipeline configuration.
        meme_db: Meme template database (for re-rendering).
        registry: Hotkey registry. Uses default if not provided.
    """
    if not result.outputs:
        print("No memes to preview.")
        return

    if registry is None:
        registry = build_default_registry()

    state = PreviewState(result, config)

    try:
        curses.wrapper(lambda stdscr: _preview_loop(stdscr, state, registry, meme_db))
    except curses.error as e:
        logger.error("Terminal error: %s", e)
        print(f"Terminal error: {e}")
        print("Try resizing your terminal to at least 80x24.")


def _preview_loop(
    stdscr: curses.window,
    state: PreviewState,
    registry: HotkeyRegistry,
    meme_db: Optional[MemeDatabase],
) -> None:
    """Main event loop for the interactive preview."""
    curses.curs_set(0)  # Hide cursor
    stdscr.timeout(-1)  # Blocking reads

    # Set up colors if available
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_YELLOW, -1)
        curses.init_pair(3, curses.COLOR_CYAN, -1)
        curses.init_pair(4, curses.COLOR_RED, -1)

    while not state.should_quit:
        stdscr.clear()

        if state.show_hotkey_menu:
            _draw_hotkey_menu(stdscr, registry)
        else:
            _draw_preview(stdscr, state)

        stdscr.refresh()

        key = stdscr.getch()
        _handle_input(key, state, registry, meme_db)


def _draw_preview(stdscr: curses.window, state: PreviewState) -> None:
    """Draw the main preview screen."""
    max_y, max_x = stdscr.getmaxyx()
    output = state.current_output

    # Header
    header = f" MemeScript Preview [{state.current_index + 1}/{state.total}]"
    terrain_status = "ON" if state.enable_terrain else "OFF"
    header += f"  |  Terrain: {terrain_status}"
    header += "  |  Press ? for hotkeys"
    _safe_addstr(stdscr, 0, 0, header[:max_x - 1], curses.A_REVERSE)
    _safe_addstr(stdscr, 0, len(header), " " * max(0, max_x - len(header) - 1), curses.A_REVERSE)

    if output is None:
        _safe_addstr(stdscr, 2, 2, "No meme at this index.")
        return

    row = 2

    # Template name
    _safe_addstr(stdscr, row, 2, "Template: ", _color(3))
    _safe_addstr(stdscr, row, 12, output.suggestion.template_name)
    row += 1

    # Timestamp
    ts = output.timestamp_start or "N/A"
    _safe_addstr(stdscr, row, 2, "Timestamp: ", _color(3))
    _safe_addstr(stdscr, row, 13, ts)
    row += 1

    # Comedy mechanism and emotional beat
    moment = output.moment
    _safe_addstr(stdscr, row, 2, "Comedy: ", _color(3))
    _safe_addstr(stdscr, row, 10, f"{moment.comedy_mechanism} / {moment.emotional_beat}")
    row += 1

    # Confidence
    _safe_addstr(stdscr, row, 2, "Confidence: ", _color(3))
    _safe_addstr(stdscr, row, 14, f"{moment.confidence:.0%}")
    row += 2

    # Script line
    _safe_addstr(stdscr, row, 2, "Line:", _color(2))
    row += 1
    line_text = moment.line
    for wrapped in textwrap.wrap(line_text, width=max_x - 6):
        _safe_addstr(stdscr, row, 4, wrapped)
        row += 1
    row += 1

    # Captions
    _safe_addstr(stdscr, row, 2, "Captions:", _color(2))
    row += 1
    for label, caption in output.suggestion.captions.items():
        _safe_addstr(stdscr, row, 4, f"[{label}] ", _color(1))
        _safe_addstr(stdscr, row, 4 + len(f"[{label}] "), caption[:max_x - 20])
        row += 1
    row += 1

    # Image path
    if output.image_path:
        _safe_addstr(stdscr, row, 2, "Image: ", _color(3))
        _safe_addstr(stdscr, row, 9, output.image_path)
        row += 1

    # Critique scores
    if output.critique:
        row += 1
        _safe_addstr(stdscr, row, 2, "Quality Score: ", _color(2))
        score = output.critique.overall_score
        score_color = _color(1) if score >= 3.0 else _color(4)
        _safe_addstr(stdscr, row, 17, f"{score:.1f}/5.0", score_color)
        row += 1

    # Status bar
    if state.status_message:
        _safe_addstr(stdscr, max_y - 1, 0, f" {state.status_message}"[:max_x - 1], curses.A_DIM)


def _draw_hotkey_menu(stdscr: curses.window, registry: HotkeyRegistry) -> None:
    """Draw the hotkey help menu overlay."""
    max_y, max_x = stdscr.getmaxyx()
    menu_text = format_hotkey_menu(registry)
    lines = menu_text.split("\n")

    for i, line in enumerate(lines):
        if i >= max_y - 1:
            break
        _safe_addstr(stdscr, i, 0, line[:max_x - 1])


def _handle_input(
    key: int,
    state: PreviewState,
    registry: HotkeyRegistry,
    meme_db: Optional[MemeDatabase],
) -> None:
    """Process a keypress and update state accordingly."""
    # If hotkey menu is showing, any key dismisses it
    if state.show_hotkey_menu:
        state.show_hotkey_menu = False
        return

    hotkey = registry.find_by_code(key)
    if hotkey is None:
        return

    if key in (ord("q"), ord("Q"), 27):
        state.should_quit = True

    elif key == ord("?"):
        state.show_hotkey_menu = True

    elif key in (ord("t"), ord("T")):
        state.enable_terrain = not state.enable_terrain
        terrain_label = "ON" if state.enable_terrain else "OFF"
        state.status_message = f"Terrain toggled {terrain_label}"
        # Re-render current meme with new terrain setting
        _rerender_current(state, meme_db)

    elif key in (ord("h"), ord("H"), 260):  # Left / H
        if state.current_index > 0:
            state.current_index -= 1
            state.status_message = ""

    elif key in (ord("l"), ord("L"), 261):  # Right / L
        if state.current_index < state.total - 1:
            state.current_index += 1
            state.status_message = ""

    elif key in (ord("r"), ord("R")):
        _rerender_current(state, meme_db)
        state.status_message = "Re-rendered current meme"


def _rerender_current(
    state: PreviewState,
    meme_db: Optional[MemeDatabase],
) -> None:
    """Re-render the current meme with the current terrain setting."""
    output = state.current_output
    if output is None:
        return

    suggestion = output.suggestion
    template = None
    if meme_db:
        template = meme_db.fuzzy_match(suggestion.template_name)

    if template is None:
        template = _make_generic_template(suggestion)

    image_path = render_meme(
        suggestion=suggestion,
        template=template,
        template_dir=state.config.template_dir,
        output_dir=state.config.output_dir,
        index=state.current_index,
        enable_terrain=state.enable_terrain,
    )
    output.image_path = image_path


def _safe_addstr(
    stdscr: curses.window,
    y: int,
    x: int,
    text: str,
    attr: int = 0,
) -> None:
    """Write text to the screen, ignoring out-of-bounds errors."""
    try:
        stdscr.addstr(y, x, text, attr)
    except curses.error:
        pass


def _color(pair: int) -> int:
    """Return a curses color pair attribute, or 0 if colors unavailable."""
    try:
        return curses.color_pair(pair)
    except curses.error:
        return 0
