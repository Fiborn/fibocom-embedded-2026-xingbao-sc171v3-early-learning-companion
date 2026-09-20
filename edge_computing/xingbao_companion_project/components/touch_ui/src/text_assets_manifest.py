"""Central aliases for split static text PNG assets.

All text PNGs are pre-rendered Chinese/English labels — no font rendering needed
for static UI text.  Dynamic numbers, timestamps, and fallback text still use
pygame fonts via FontManager.
"""

# ═══════════════════════════════════════════════════════════════
#  TEXT ASSET ALIASES
# ═══════════════════════════════════════════════════════════════

TEXT_ASSETS = {
    # ── 01  titles & game names ──────────────────────────────
    "main_title": "01_titles_and_game_names/main_title_xingbao_companion_desk.png",
    "subtitle": "01_titles_and_game_names/subtitle_ai_star_partner_touch_exploration_system.png",
    "system_console": "01_titles_and_game_names/sc171v3_aiot_companion_console.png",

    "module_color": "01_titles_and_game_names/module_color_energy_cabin.png",
    "module_geometry": "01_titles_and_game_names/module_geometry_starmap_cabin.png",
    "module_memory": "01_titles_and_game_names/module_memory_route_cabin.png",

    "game_find_color": "01_titles_and_game_names/game_find_color.png",
    "game_recognize_shape": "01_titles_and_game_names/game_recognize_shape.png",
    "game_memory_route": "01_titles_and_game_names/game_memory_route.png",

    # ── 02  status chips & buttons ───────────────────────────
    "status_local_small": "02_status_chips_and_buttons/status_local_small.png",
    "status_touch_small": "02_status_chips_and_buttons/status_touch_small.png",
    "status_safe_small": "02_status_chips_and_buttons/status_safe_small.png",
    "status_local_mode": "02_status_chips_and_buttons/status_local_mode.png",
    "status_touch_ready": "02_status_chips_and_buttons/status_touch_ready.png",
    "status_session_active": "02_status_chips_and_buttons/status_session_active.png",
    "status_ready": "02_status_chips_and_buttons/status_ready.png",
    "status_companion_core": "02_status_chips_and_buttons/status_companion_core.png",
    "status_mission_deck": "02_status_chips_and_buttons/status_mission_deck.png",
    "status_touch_task": "02_status_chips_and_buttons/status_touch_task.png",
    "status_5_rounds": "02_status_chips_and_buttons/status_5_rounds.png",
    "status_target_locked": "02_status_chips_and_buttons/status_target_locked.png",
    "status_auto_save": "02_status_chips_and_buttons/status_auto_save.png",

    "button_select": "02_status_chips_and_buttons/button_select.png",
    "button_demo_mode": "02_status_chips_and_buttons/button_demo_mode.png",

    # ── 03  color labels ────────────────────────────────────
    "color_red_cn": "03_color_labels/color_red_cn.png",
    "color_yellow_cn": "03_color_labels/color_yellow_cn.png",
    "color_blue_cn": "03_color_labels/color_blue_cn.png",
    "color_green_cn": "03_color_labels/color_green_cn.png",
    "color_purple_cn": "03_color_labels/color_purple_cn.png",
    "color_orange_cn": "03_color_labels/color_orange_cn.png",

    "color_red_en": "03_color_labels/color_red_en.png",
    "color_yellow_en": "03_color_labels/color_yellow_en.png",
    "color_blue_en": "03_color_labels/color_blue_en.png",
    "color_green_en": "03_color_labels/color_green_en.png",
    "color_purple_en": "03_color_labels/color_purple_en.png",
    "color_orange_en": "03_color_labels/color_orange_en.png",

    "prompt_lock_target": "03_color_labels/prompt_lock_target.png",
    "prompt_please_find": "03_color_labels/prompt_please_find.png",
    "prompt_choose_matching_color": "03_color_labels/prompt_choose_matching_color_energy.png",
    "banner_target_blue": "03_color_labels/banner_target_blue.png",

    # ── 04  shape labels ────────────────────────────────────
    "shape_circle_cn": "04_shape_labels/shape_circle_cn.png",
    "shape_square_cn": "04_shape_labels/shape_square_cn.png",
    "shape_triangle_cn": "04_shape_labels/shape_triangle_cn.png",
    "shape_star_cn": "04_shape_labels/shape_star_cn.png",
    "shape_heart_cn": "04_shape_labels/shape_heart_cn.png",

    "shape_circle_en": "04_shape_labels/shape_circle_en.png",
    "shape_square_en": "04_shape_labels/shape_square_en.png",
    "shape_triangle_en": "04_shape_labels/shape_triangle_en.png",
    "shape_star_en": "04_shape_labels/shape_star_en.png",
    "shape_heart_en": "04_shape_labels/shape_heart_en.png",

    "prompt_target_shape": "04_shape_labels/prompt_target_shape.png",
    "prompt_observe_shape_signal": "04_shape_labels/prompt_observe_shape_signal.png",
    "banner_target_square": "04_shape_labels/banner_target_square.png",

    # ── 05  report panels ───────────────────────────────────
    "title_report": "05_report_panels/title_interstellar_task_report.png",
    "title_today_data": "05_report_panels/title_today_companion_data.png",
    "label_current_level": "05_report_panels/label_current_level.png",
    "label_today_stars": "05_report_panels/label_today_stars.png",
    "label_energy_value": "05_report_panels/label_energy_value.png",
    "label_rounds_completed": "05_report_panels/label_rounds_completed.png",
    "label_success_count": "05_report_panels/label_success_count.png",
    "label_total_attempts": "05_report_panels/label_total_attempts.png",
    "label_recent_game": "05_report_panels/label_recent_game.png",
    "label_starcore_stable": "05_report_panels/label_starcore_stable.png",
    "label_energy_increase": "05_report_panels/label_energy_increase.png",
    "label_stars_gained_this_round": "05_report_panels/label_stars_gained_this_round.png",
    "feedback_success": "05_report_panels/feedback_success.png",
    "feedback_try_again": "05_report_panels/feedback_try_again.png",

    # ── 06  lightweight line labels ─────────────────────────
    "round_1_of_5": "06_lightweight_line_labels/light_round_1_of_5.png",
    "round_2_of_5": "06_lightweight_line_labels/light_round_2_of_5.png",
    "round_3_of_5": "06_lightweight_line_labels/light_round_3_of_5.png",
    "round_4_of_5": "06_lightweight_line_labels/light_round_4_of_5.png",
    "round_5_of_5": "06_lightweight_line_labels/light_round_5_of_5.png",

    # ── 07  flat label sheet ────────────────────────────────
    "flat_button_today_records": "07_flat_label_sheet/flat_button_today_records.png",
    "flat_button_system_exit": "07_flat_label_sheet/flat_button_system_exit.png",
    "flat_button_demo_mode": "07_flat_label_sheet/flat_button_demo_mode.png",
    "flat_main_title": "07_flat_label_sheet/flat_main_title_xingbao.png",
    "flat_subtitle": "07_flat_label_sheet/flat_subtitle_ai_partner_touch_system.png",
    "flat_console": "07_flat_label_sheet/flat_sc171v3_aiot_console.png",
    "flat_module_color": "07_flat_label_sheet/flat_module_color_energy_cabin.png",
    "flat_module_geometry": "07_flat_label_sheet/flat_module_geometry_cabin.png",
    "flat_module_memory": "07_flat_label_sheet/flat_module_memory_route_cabin.png",
    "flat_game_color": "07_flat_label_sheet/flat_game_recognize_color_energy.png",
    "flat_game_geometry": "07_flat_label_sheet/flat_game_discover_geometry.png",
    "flat_game_memory": "07_flat_label_sheet/flat_game_light_route.png",
    "flat_local": "07_flat_label_sheet/flat_local.png",
    "flat_touch_ready": "07_flat_label_sheet/flat_touch_ready.png",
    "flat_session_active": "07_flat_label_sheet/flat_session_active.png",
    "flat_companion_core": "07_flat_label_sheet/flat_companion_core.png",
    "flat_mission_deck": "07_flat_label_sheet/flat_mission_deck.png",
    "flat_ready": "07_flat_label_sheet/flat_ready.png",
    "flat_local_mode": "07_flat_label_sheet/flat_local_mode.png",
    "flat_safe": "07_flat_label_sheet/flat_safe.png",
    "flat_touch_task": "07_flat_label_sheet/flat_touch_task.png",
    "flat_5_rounds": "07_flat_label_sheet/flat_5_rounds.png",

    # ── 08  mixed element sheet ─────────────────────────────
    "mix_prompt_choose_module": "08_mixed_element_sheet/mix_prompt_choose_module.png",
    "mix_prompt_hello_xingbao": "08_mixed_element_sheet/mix_prompt_hello_xingbao.png",
    "mix_level_lv1": "08_mixed_element_sheet/mix_level_lv1.png",
    "mix_starcore_stable": "08_mixed_element_sheet/mix_starcore_stable.png",
    "mix_today_stars": "08_mixed_element_sheet/mix_today_stars.png",
    "mix_energy_value": "08_mixed_element_sheet/mix_energy_value.png",
    "mix_button_return_console": "08_mixed_element_sheet/mix_button_return_console.png",
}

# ═══════════════════════════════════════════════════════════════
#  COLOR / SHAPE text PNG helpers
# ═══════════════════════════════════════════════════════════════

COLOR_TEXT_ASSETS = {
    color: {
        "cn": "03_color_labels/color_{}_cn.png".format(color),
        "en": "03_color_labels/color_{}_en.png".format(color),
        "mix_cn": "08_mixed_element_sheet/mix_color_{}_cn.png".format(color),
        "mix_en": "08_mixed_element_sheet/mix_color_{}_en.png".format(color),
    }
    for color in ("red", "yellow", "blue", "green", "purple", "orange")
}

SHAPE_TEXT_ASSETS = {
    shape: {
        "cn": "04_shape_labels/shape_{}_cn.png".format(shape),
        "en": "04_shape_labels/shape_{}_en.png".format(shape),
        "mix_cn": "08_mixed_element_sheet/mix_shape_{}_cn.png".format(shape),
        "mix_en": "08_mixed_element_sheet/mix_shape_{}_en.png".format(shape),
    }
    for shape in ("circle", "square", "triangle", "star", "heart")
}

# ═══════════════════════════════════════════════════════════════
#  STATUS CHIP SEMANTICS
# ═══════════════════════════════════════════════════════════════

STATUS_MEANINGS = {
    "LOCAL": (
        "本地运行模式：游戏在本机/SC171V3本地运行，不依赖云端；"
        "自动存档保存在本地 saves/；不上传儿童数据。"
    ),
    "TOUCH": (
        "触控就绪：当前交互方式是触控屏点击；电脑调试时鼠标点击等价于触控；"
        "不使用摄像头识别纸片；不使用实体卡片识别。"
    ),
    "SAFE": (
        "儿童安全演示模式：不采集人脸；不上传云端；"
        "不保存敏感个人信息；只保存本地成长数值和游戏记录。"
    ),
    "SESSION ACTIVE": (
        "当前会话运行中：程序已启动；session_id 已生成；"
        "日志系统运行中；自动存档可用。"
    ),
    "READY": (
        "任务模块可进入：该小游戏模块可以点击进入；"
        "不是完成状态；不是存档状态。"
    ),
    "TOUCH TASK": (
        "任务通过触控完成：当前小游戏适配触控交互。"
    ),
    "5 ROUNDS": (
        "本局默认五轮：每个小游戏包含5轮挑战。"
    ),
}
