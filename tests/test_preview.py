"""Tests for the interactive preview mode."""

import pytest
from unittest.mock import MagicMock, patch

from memescript.hotkeys import build_default_registry
from memescript.models import (
    MemeableMoment,
    MemeOutput,
    MemeSuggestion,
    PipelineConfig,
    PipelineResult,
    ScriptLine,
)
from memescript.preview import PreviewState, _handle_input


def _make_moment():
    return MemeableMoment(
        line="Test line",
        timestamp="00:15",
        line_index=0,
        comedy_mechanism="irony",
        emotional_beat="smugness",
        subtext="test",
        confidence=0.9,
    )


def _make_output(index=0):
    moment = _make_moment()
    suggestion = MemeSuggestion(
        moment=moment,
        template_name="Drake Preference",
        captions={"rejected": "Old stuff", "preferred": "New stuff"},
        reasoning="Test",
    )
    return MemeOutput(
        moment=moment,
        suggestion=suggestion,
        critique=None,
        image_path=f"/tmp/meme_{index:03d}.png",
        timestamp_start="00:15",
        timestamp_end=None,
    )


def _make_result(count=3):
    outputs = [_make_output(i) for i in range(count)]
    return PipelineResult(
        script_lines=[ScriptLine(text="test", index=0)],
        moments=[o.moment for o in outputs],
        suggestions=[o.suggestion for o in outputs],
        critiques=[],
        outputs=outputs,
        config=PipelineConfig(),
    )


class TestPreviewState:
    def test_initial_state(self):
        result = _make_result(3)
        config = PipelineConfig()
        state = PreviewState(result, config)

        assert state.current_index == 0
        assert state.enable_terrain is True
        assert state.show_hotkey_menu is False
        assert state.should_quit is False
        assert state.total == 3

    def test_current_output(self):
        result = _make_result(3)
        state = PreviewState(result, PipelineConfig())

        assert state.current_output is result.outputs[0]
        state.current_index = 2
        assert state.current_output is result.outputs[2]

    def test_current_output_out_of_bounds(self):
        result = _make_result(1)
        state = PreviewState(result, PipelineConfig())

        state.current_index = 5
        assert state.current_output is None

    def test_terrain_default_from_config(self):
        config = PipelineConfig(enable_terrain=False)
        result = _make_result(1)
        state = PreviewState(result, config)
        assert state.enable_terrain is False


class TestHandleInput:
    def _make_state(self, count=3):
        result = _make_result(count)
        return PreviewState(result, PipelineConfig())

    def test_quit_with_q(self):
        state = self._make_state()
        registry = build_default_registry()
        _handle_input(ord("q"), state, registry, None)
        assert state.should_quit is True

    def test_quit_with_escape(self):
        state = self._make_state()
        registry = build_default_registry()
        _handle_input(27, state, registry, None)
        assert state.should_quit is True

    def test_show_hotkey_menu(self):
        state = self._make_state()
        registry = build_default_registry()
        _handle_input(ord("?"), state, registry, None)
        assert state.show_hotkey_menu is True

    def test_dismiss_hotkey_menu(self):
        state = self._make_state()
        state.show_hotkey_menu = True
        registry = build_default_registry()
        # Any key dismisses the menu
        _handle_input(ord("x"), state, registry, None)
        assert state.show_hotkey_menu is False

    @patch("memescript.preview._rerender_current")
    def test_toggle_terrain_on_to_off(self, mock_rerender):
        state = self._make_state()
        registry = build_default_registry()
        assert state.enable_terrain is True

        _handle_input(ord("t"), state, registry, None)
        assert state.enable_terrain is False
        assert "OFF" in state.status_message
        mock_rerender.assert_called_once()

    @patch("memescript.preview._rerender_current")
    def test_toggle_terrain_off_to_on(self, mock_rerender):
        state = self._make_state()
        state.enable_terrain = False
        registry = build_default_registry()

        _handle_input(ord("T"), state, registry, None)
        assert state.enable_terrain is True
        assert "ON" in state.status_message

    def test_navigate_right(self):
        state = self._make_state(3)
        registry = build_default_registry()

        _handle_input(ord("l"), state, registry, None)
        assert state.current_index == 1

        _handle_input(ord("l"), state, registry, None)
        assert state.current_index == 2

    def test_navigate_right_stops_at_end(self):
        state = self._make_state(2)
        state.current_index = 1
        registry = build_default_registry()

        _handle_input(ord("l"), state, registry, None)
        assert state.current_index == 1  # stays at last

    def test_navigate_left(self):
        state = self._make_state(3)
        state.current_index = 2
        registry = build_default_registry()

        _handle_input(ord("h"), state, registry, None)
        assert state.current_index == 1

    def test_navigate_left_stops_at_start(self):
        state = self._make_state(3)
        state.current_index = 0
        registry = build_default_registry()

        _handle_input(ord("h"), state, registry, None)
        assert state.current_index == 0

    @patch("memescript.preview._rerender_current")
    def test_rerender(self, mock_rerender):
        state = self._make_state()
        registry = build_default_registry()

        _handle_input(ord("r"), state, registry, None)
        assert "Re-rendered" in state.status_message
        mock_rerender.assert_called_once()

    def test_unknown_key_does_nothing(self):
        state = self._make_state()
        registry = build_default_registry()
        initial_index = state.current_index

        _handle_input(ord("z"), state, registry, None)
        assert state.current_index == initial_index
        assert state.should_quit is False
        assert state.show_hotkey_menu is False
