"""Feature flags controlling text PNG usage.

All text PNG rendering is gated through these flags.
Currently: large-area text PNGs OFF (they have white/opaque backgrounds).
Only small transparent status chips and button labels may remain if clean.
"""

# ── Master switch ──────────────────────────────────────────────
USE_TEXT_PNG = False  # global kill-switch for all text PNG rendering

# ── Per-category switches (only effective if USE_TEXT_PNG is True) ─
USE_TEXT_PNG_FOR_BUTTONS = True        # bottom buttons (DEMO / 今日记录 / 退出)
USE_TEXT_PNG_FOR_STATUS_CHIPS = True   # LOCAL / TOUCH / SAFE / READY / TOUCH TASK / 5 ROUNDS
USE_TEXT_PNG_FOR_GAME_TITLES = False   # game page titles
USE_TEXT_PNG_FOR_CARD_TITLES = False   # module + desc on home cards
USE_TEXT_PNG_FOR_COLOR_LABELS = False  # color CN/EN labels
USE_TEXT_PNG_FOR_SHAPE_LABELS = False  # shape CN/EN labels
USE_TEXT_PNG_FOR_COMPANION_PANEL = False  # companion panel internal labels


def allow(category):
    """Return True if *category* text PNGs are enabled."""
    if not USE_TEXT_PNG:
        return False
    flags = {
        "buttons": USE_TEXT_PNG_FOR_BUTTONS,
        "status_chips": USE_TEXT_PNG_FOR_STATUS_CHIPS,
        "game_titles": USE_TEXT_PNG_FOR_GAME_TITLES,
        "card_titles": USE_TEXT_PNG_FOR_CARD_TITLES,
        "color_labels": USE_TEXT_PNG_FOR_COLOR_LABELS,
        "shape_labels": USE_TEXT_PNG_FOR_SHAPE_LABELS,
        "companion_panel": USE_TEXT_PNG_FOR_COMPANION_PANEL,
    }
    return flags.get(category, False)

