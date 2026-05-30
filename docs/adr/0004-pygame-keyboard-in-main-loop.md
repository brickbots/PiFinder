# Pygame keyboard input is handled in the main loop, not a keyboard process

When a pygame display is active (`--display pg_*`, e.g. `-fh`), keyboard input is
polled directly in `main.py`'s primary event loop, and the spawned keyboard
process is the no-op `keyboard_none`. We do this because pygame can only read
keyboard events from the process that owns the display window, and the
pynput/PyHotKey backend used by `keyboard_local` cannot access the keyboard under
Wayland.

## Considered Options

- **A `keyboard_pygame` `run_keyboard` subprocess**, parallel to `keyboard_local` /
  `keyboard_pi`. Rejected: event capture must happen in the window-owning (main)
  process, so a child process would see no events. This is the obvious-looking
  "fix" a future reader will reach for — it does not work.

## Consequences

- The pygame key map (`pygame_key_map` / `pygame_ctrl_key_map`) lives in `main.py`
  rather than in a `keyboard_*` module.
- `--keyboard local` with a pygame display routes to `keyboard_none` only to
  satisfy the unconditional keyboard-process spawn; the real key capture is the
  main loop. Ctrl+key emulates the hardware keypad's SQUARE-modifier chord (the
  `ALT_*` keycodes).
