# ═══════════════════════════════════════════════════════════════
# 星宝陪伴桌 V5 — 竞赛级 AIoT 智能终端色彩系统
# ═══════════════════════════════════════════════════════════════

# ── Space background ──────────────────────────────────────────
SPACE_DEEP  = (6, 20, 40)       # #061428  深空底色
SPACE_MID   = (17, 29, 63)      # #111D3F  中间过渡
SPACE_HIGH  = (22, 38, 78)      # #16264E  上部亮区

# ── Primary accents ───────────────────────────────────────────
ELECTRIC    = (55, 232, 255)    # #37E8FF  电光蓝 — 主要强调色
CRYSTAL     = (158, 123, 255)   # #9E7BFF  晶体紫 — 星宝主色
STAR_GOLD   = (255, 215, 106)   # #FFD76A  星光金 — 高亮/成功
SUCCESS     = (95, 242, 160)    # #5FF2A0  成功绿
WARNING     = (255, 179, 92)    # #FFB35C  提示橙
SOFT_RED    = (255, 111, 145)   # #FF6F91  柔和红

# ── Text ──────────────────────────────────────────────────────
TEXT_MAIN   = (243, 247, 255)   # #F3F7FF  主文字
TEXT_SUB    = (184, 199, 232)   # #B8C7E8  副文字
TEXT_MUTED  = (127, 144, 196)   # #7F90C4  弱文字

# ── Panels / surfaces ─────────────────────────────────────────
PANEL_BG    = (18, 36, 80, 195)     # 深蓝半透明面板
PANEL_GLASS = (28, 48, 100, 175)    # 玻璃面板
PANEL_ALT   = (20, 56, 72, 195)     # 备用深青面板
CARD_BG     = (22, 42, 90, 210)     # 卡片底色
CARD_HOVER  = (30, 55, 110, 230)    # 卡片悬浮

# ── Borders / glows ───────────────────────────────────────────
BORDER_DIM     = (55, 232, 255, 55)   # 暗边框
BORDER_ACTIVE  = (55, 232, 255, 120)  # 激活边框
GLOW_SOFT      = (158, 123, 255, 45)  # 柔和紫光

# ── Layout (base: 1280×720) ───────────────────────────────────
BASE_W      = 1280
BASE_H      = 720
PAGE_MARGIN = 32
TITLE_H     = 80
FOOTER_H    = 90
GAP         = 14

# ── Font sizes (scaled by layout.font()) ─────────────────────
F_TITLE     = 46   # 页面标题
F_SUBTITLE  = 30   # 副标题
F_BODY      = 26   # 正文
F_BUTTON    = 28   # 按钮文字
F_SMALL     = 22   # 小字/注释
F_MICRO     = 18   # 微字

# ── Animation ─────────────────────────────────────────────────
FLOAT_SPEED   = 1.4   # 星宝浮动频率
PULSE_SPEED   = 1.8   # 辉光脉冲频率
STAR_SPEED    = 1.2   # 星点闪烁频率
GRID_DRIFT_X  = 2.5   # 网格 X 漂移
GRID_DRIFT_Y  = 1.2   # 网格 Y 漂移
SCAN_SPEED    = 22    # 扫描线速度

# ── Growth system ─────────────────────────────────────────────
ENERGY_PER_CORRECT = 8
ENERGY_PER_ROUND   = 15
ENERGY_MAX         = 100
START_LEVEL        = 1

# Alias for compatibility
BACKGROUND_TOP    = SPACE_DEEP
BACKGROUND_BOTTOM = SPACE_MID
BACKGROUND_DEEP   = SPACE_DEEP
CYAN      = ELECTRIC
PURPLE    = CRYSTAL
YELLOW    = STAR_GOLD
GREEN     = SUCCESS
ORANGE    = WARNING
CORAL     = SOFT_RED
TEXT_PRIMARY   = TEXT_MAIN
TEXT_SECONDARY = TEXT_SUB
TEXT_MUTED_LOCAL = TEXT_MUTED
TEXT_HIGHLIGHT = ELECTRIC
PANEL_BG_LOCAL       = PANEL_BG
PANEL_BG_LIGHT = PANEL_GLASS
PANEL_BORDER         = BORDER_DIM
PANEL_BORDER_ACTIVE  = BORDER_ACTIVE
PANEL_SHADOW = (3, 9, 26, 130)
INFO     = ELECTRIC
ERROR    = SOFT_RED
WHITE    = (255, 255, 255)
BASE_WIDTH  = 1280
BASE_HEIGHT = 720
TITLE_SIZE   = F_TITLE
SUBTITLE_SIZE = F_SUBTITLE
BODY_SIZE    = F_BODY
BUTTON_SIZE  = F_BUTTON
SMALL_SIZE   = F_SMALL
TITLE_HEIGHT   = TITLE_H
FOOTER_HEIGHT  = FOOTER_H
BACKGROUND     = SPACE_DEEP
SURFACE        = PANEL_BG
SURFACE_BLUE   = (31, 72, 125, 210)
SURFACE_YELLOW = (90, 72, 42, 215)
SURFACE_GREEN  = (26, 86, 80, 210)
SURFACE_ORANGE = (88, 55, 65, 210)
PRIMARY        = ELECTRIC
PRIMARY_DARK   = TEXT_MAIN
ACCENT         = STAR_GOLD
TEXT           = TEXT_MAIN
BORDER         = BORDER_DIM
SHADOW         = PANEL_SHADOW
GAME_CARD_COLORS = (SURFACE_YELLOW, SURFACE_BLUE, SURFACE_GREEN)
