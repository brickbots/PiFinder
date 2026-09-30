# The demo display draws the device photo, the key glows and the recording in the PiFinder process

**Status: accepted.**

Instruction videos must show the screen and the key presses together. The demo display (`--display pg_demo`, `pg_demo_176`) is a pygame window that shows a photo of the PiFinder. It puts the live UI into the screen area of the photo and makes each pressed button glow. With `--record FILE`, it sends the window to ffmpeg and writes an MP4 file.

All of this runs in the main PiFinder process. `DemoDevice` is a luma device, so the UI draws into it like into any other display. The main loop tells it about each key it reads from the keyboard queue (`show_key`) and calls `tick()` once per pass, so that the glows fade and the video keeps its rate while the UI sends no new frame. The glow comes from the keyboard queue, not from the keyboard, so keys from the pygame window, a click on the photo, a `--script` file and the web keypad all glow.

## Considered options

- **A separate overlay window with a key socket and OBS (rejected).** This was the first version. A separate program showed the photo and the glows. It read the keys with evdev from one fixed keyboard, and from a Unix socket that PiFinder wrote to. The emulator window had to be put on top of the photo in OBS by hand. It needed three programs, a fixed keyboard device path and a patch to `main.py` that was never committed. It could not show keys from a script or from the web keypad.
- **A screen recorder of the pygame window (rejected).** It needs a Wayland or X11 capture tool per desktop, and the video length follows the capture tool, not the key script.
- **In-process drawing and ffmpeg (chosen).** One command starts it. It works with the SDL dummy video driver, so a key script can make a video with no visible window.

## Consequences

- `DisplayBase` has five hooks (`show_key`, `keycode_for_event`, `tick`, `start_recording`, `stop_recording`). They do nothing on the other displays.
- `demo_display` imports pygame. `displays.py` imports it in a `try` block, because the Pi image has no pygame. On the Pi, `pg_demo` fails with a clear error.
- The recording starts just before the main loop, after the last child process is forked. PiFinder forks its children, and a child forked after ffmpeg starts keeps the pipe open, so the file does not end. The boot screens are not in the video.
- The recorder repeats a frame until the frame count agrees with the wall clock. The video length is the real time, so a sound track from `--record-audio` stays in step.
- The Nix dev shell does not include ffmpeg. Its closure is about 1 GB (300 MB for `ffmpeg-headless`), and few developers record videos. The recorder stops with an error that names `nix shell nixpkgs#ffmpeg-headless`.
- ffmpeg runs in its own session, so Ctrl+C in the terminal does not stop it before PiFinder closes the pipe.
- The photo and the layout are in `images/demo_display/`. `python/tools/demo_layout_editor.py` edits the layout.
