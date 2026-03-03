"""Tests for the hotkey registry and menu."""

import pytest

from memescript.hotkeys import (
    Hotkey,
    HotkeyRegistry,
    build_default_registry,
    format_hotkey_menu,
)


class TestHotkey:
    def test_creation(self):
        hk = Hotkey(
            key="T",
            key_codes=[ord("t"), ord("T")],
            description="Toggle terrain",
            category="Display",
        )
        assert hk.key == "T"
        assert ord("t") in hk.key_codes
        assert hk.category == "Display"


class TestHotkeyRegistry:
    def test_register_and_get_all(self):
        registry = HotkeyRegistry()
        hk = Hotkey(key="A", key_codes=[ord("a")], description="Test", category="Test")
        registry.register(hk)
        assert len(registry.get_all()) == 1
        assert registry.get_all()[0] is hk

    def test_find_by_code(self):
        registry = HotkeyRegistry()
        hk = Hotkey(key="T", key_codes=[ord("t"), ord("T")], description="Test", category="Test")
        registry.register(hk)

        assert registry.find_by_code(ord("t")) is hk
        assert registry.find_by_code(ord("T")) is hk
        assert registry.find_by_code(ord("x")) is None

    def test_get_by_category(self):
        registry = HotkeyRegistry()
        registry.register(Hotkey(key="T", key_codes=[116], description="Terrain", category="Display"))
        registry.register(Hotkey(key="R", key_codes=[114], description="Render", category="Display"))
        registry.register(Hotkey(key="Q", key_codes=[113], description="Quit", category="General"))

        categories = registry.get_by_category()
        assert "Display" in categories
        assert "General" in categories
        assert len(categories["Display"]) == 2
        assert len(categories["General"]) == 1

    def test_empty_registry(self):
        registry = HotkeyRegistry()
        assert registry.get_all() == []
        assert registry.find_by_code(ord("x")) is None
        assert registry.get_by_category() == {}


class TestBuildDefaultRegistry:
    def test_has_terrain_toggle(self):
        registry = build_default_registry()
        hk = registry.find_by_code(ord("t"))
        assert hk is not None
        assert "terrain" in hk.description.lower()

    def test_has_quit_hotkey(self):
        registry = build_default_registry()
        hk = registry.find_by_code(ord("q"))
        assert hk is not None
        assert "quit" in hk.description.lower()

    def test_has_help_hotkey(self):
        registry = build_default_registry()
        hk = registry.find_by_code(ord("?"))
        assert hk is not None
        assert "hotkey menu" in hk.description.lower()

    def test_has_navigation_hotkeys(self):
        registry = build_default_registry()
        left = registry.find_by_code(ord("h"))
        right = registry.find_by_code(ord("l"))
        assert left is not None
        assert right is not None
        assert "previous" in left.description.lower()
        assert "next" in right.description.lower()

    def test_has_rerender_hotkey(self):
        registry = build_default_registry()
        hk = registry.find_by_code(ord("r"))
        assert hk is not None
        assert "render" in hk.description.lower()

    def test_all_standard_hotkeys_present(self):
        registry = build_default_registry()
        all_hotkeys = registry.get_all()
        # T, Left/H, Right/L, R, ?, Q/Esc = 6 hotkeys
        assert len(all_hotkeys) == 6


class TestFormatHotkeyMenu:
    def test_contains_all_hotkeys(self):
        registry = build_default_registry()
        menu = format_hotkey_menu(registry)

        assert "Hotkey Menu" in menu
        assert "terrain" in menu.lower()
        assert "quit" in menu.lower()
        assert "Toggle terrain" in menu

    def test_contains_categories(self):
        registry = build_default_registry()
        menu = format_hotkey_menu(registry)

        assert "[Display]" in menu
        assert "[Navigation]" in menu
        assert "[General]" in menu

    def test_contains_dismiss_instruction(self):
        registry = build_default_registry()
        menu = format_hotkey_menu(registry)

        assert "Press any key to dismiss" in menu
