# Xingbao agent notes

## Display platform

- The production touch UI runs on native Wayland. Treat Wayland as the primary
  platform for design, debugging, and verification.
- The canonical board launcher is `deploy/board_start_wayland_ui.sh`; it clears
  `DISPLAY` and sets `SDL_VIDEODRIVER=wayland`.
- X11 launch paths exist only for compatibility/demo use. Do not infer native
  Wayland behaviour from X11 logs or rely on X11 window-manager semantics.
- In particular, Wayland compositors own minimize, restore, maximize, focus,
  and window geometry. A Pygame/SDL client must not temporarily leave
  fullscreen in order to minimize, nor depend on `WINDOWRESTORED` to restore
  fullscreen. Keep the Wayland surface fullscreen and make compositor requests
  best-effort.
