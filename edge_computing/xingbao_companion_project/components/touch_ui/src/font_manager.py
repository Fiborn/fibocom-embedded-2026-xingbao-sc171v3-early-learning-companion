"""Unified font entry points for Chinese UI text.

The concrete font discovery/cache lives in ui_components for backward
compatibility with existing callers. New code should import from this module.
"""

from .ui_components import find_chinese_font_file, fit_font, get_font

__all__ = ["find_chinese_font_file", "fit_font", "get_font"]
