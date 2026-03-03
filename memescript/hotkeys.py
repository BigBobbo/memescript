"""Hotkey registry and menu for MemeScript interactive preview mode."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class Hotkey:
    """A single hotkey binding."""
    key: str                    # Display name for the key (e.g., "T", "Q", "?")
    key_codes: list[int]        # curses key codes that trigger this hotkey
    description: str            # Short description shown in the hotkey menu
    category: str = "General"   # Grouping in the menu


@dataclass
class HotkeyRegistry:
    """Registry of all available hotkeys."""
    _hotkeys: list[Hotkey] = field(default_factory=list)

    def register(self, hotkey: Hotkey) -> None:
        self._hotkeys.append(hotkey)

    def get_all(self) -> list[Hotkey]:
        return list(self._hotkeys)

    def get_by_category(self) -> dict[str, list[Hotkey]]:
        categories: dict[str, list[Hotkey]] = {}
        for hk in self._hotkeys:
            categories.setdefault(hk.category, []).append(hk)
        return categories

    def find_by_code(self, code: int) -> Optional[Hotkey]:
        for hk in self._hotkeys:
            if code in hk.key_codes:
                return hk
        return None


def build_default_registry() -> HotkeyRegistry:
    """Build the default hotkey registry with all standard bindings."""
    registry = HotkeyRegistry()

    registry.register(Hotkey(
        key="T",
        key_codes=[ord("t"), ord("T")],
        description="Toggle terrain (template background)",
        category="Display",
    ))
    registry.register(Hotkey(
        key="Left / H",
        key_codes=[ord("h"), ord("H"), 260],  # 260 = curses.KEY_LEFT
        description="Previous meme",
        category="Navigation",
    ))
    registry.register(Hotkey(
        key="Right / L",
        key_codes=[ord("l"), ord("L"), 261],  # 261 = curses.KEY_RIGHT
        description="Next meme",
        category="Navigation",
    ))
    registry.register(Hotkey(
        key="R",
        key_codes=[ord("r"), ord("R")],
        description="Re-render current meme",
        category="Display",
    ))
    registry.register(Hotkey(
        key="?",
        key_codes=[ord("?")],
        description="Show this hotkey menu",
        category="General",
    ))
    registry.register(Hotkey(
        key="Q / Esc",
        key_codes=[ord("q"), ord("Q"), 27],  # 27 = Escape
        description="Quit preview",
        category="General",
    ))

    return registry


def format_hotkey_menu(registry: HotkeyRegistry) -> str:
    """Format the hotkey menu as a displayable string."""
    lines = ["", "  Hotkey Menu", "  " + "=" * 40]
    categories = registry.get_by_category()

    for category, hotkeys in categories.items():
        lines.append(f"  [{category}]")
        for hk in hotkeys:
            lines.append(f"    {hk.key:<14s} {hk.description}")
        lines.append("")

    lines.append("  Press any key to dismiss")
    return "\n".join(lines)
