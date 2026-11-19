# Demo movie style

This guide tells how to make a PiFinder demo movie that looks like the
other demo movies. It has two worked examples:

- **Mount control** (INDI movie, 89 s): GoTo, refine and manual moves on
  the INDI Telescope Simulator. Key script `scripts/indi_mount_tour.pfs`.
- **Satellites** (122 s): the satellite list, the groups, the chart and a
  mount that meets and follows a satellite. Key script
  `scripts/satellite_tour.pfs`.

## 1. How a movie is made

The PiFinder records its own screen. No screen recorder is necessary.

1. Write a key script `scripts/<name>.pfs`. Each line is a key name (`RIGHT`,
   `LNG_SQUARE`, `5` ...) or `wait <seconds>`. Comments start with `#`.
   Each line, a comment too, adds 0.2 s.
2. Start PiFinder with the demo display and the recorder:

   ```bash
   cd python
   scripts/record_demo.sh --script <name> --sky-sim default \
       --record /tmp/<name>.mp4 -x
   ```

   `record_demo.sh` runs `PiFinder.main -fh --camera debug --keyboard local
   --display pg_demo`. The `pg_demo` display puts the UI into a photo of the
   device (1184x864) and shows a glow on each pressed key. `--record` writes
   that window to an MP4 file at 30 fps. Run it in the Nix dev shell, with
   `cedar-detect-server -p 50551` and ffmpeg on the `PATH`.
   The window has the UI at 1.19 times its size, with smoothing. For a sharp
   screen, record the bare 128x128 UI frames too, with the same frame clock
   (`Recorder` in `PiFinder/demo_display.py`, `start=` of the window
   recorder) to a lossless file (`-c:v ffv1`). The satellite movie did this
   with a small launcher that patches `DemoDevice.draw`. An option such as
   `--record-screen` would make this a normal step.
3. Use a separate HOME with its own `PiFinder_data/config.json`. Do not use
   your own PiFinder data: the frames then show no personal data.
4. For mount control, run your own `indiserver` with a FIFO and set
   `INDI_FIFO` and `INDI_DATA_DIR`. In the config, set `mount_control` to
   `true` and `mount_control_model` to `Telescope Simulator`.
5. `--sky-sim default` takes the plate solves from the sky simulator. The
   simulator follows the INDI mount, so a GoTo, a sync or a follow has a
   real effect on the chart and the arrows.
6. Stop PiFinder with Ctrl+C (SIGINT). The MP4 file is complete when ffmpeg
   ends.

### Location and time

- The fake GPS (`-fh`) puts the PiFinder at 34.22 N, 118.22 W and gives the
  system time.
- For a satellite or another event at a fixed time, shift the clock of all
  processes with libfaketime: `LD_PRELOAD=<libfaketime.so.1>`,
  `FAKETIME="+<seconds>"` and `FAKETIME_DONT_FAKE_MONOTONIC=1`. Use the
  libfaketime of the same nixpkgs as the dev shell, else glibc does not
  load. Compute the offset just before PiFinder starts, not before the Nix
  shell starts: the start-up time of the shell changes from run to run.
- Give `indiserver` and the driver the same clock and a HOME with a
  `Telescope Simulator_config.xml` that has the same latitude and longitude
  as the fake GPS. Connect the driver and set `GEOGRAPHIC_COORD` before
  PiFinder starts. If the mount gets its longitude after PiFinder starts,
  the sky simulator takes the jump of the RA for a sync, and every solve is
  off by the longitude.

### Data that the movie needs

- Put the catalog files in the HOME before the start (for satellites:
  `PiFinder_data/satellites/<group>.tle` and `selection.json`).
- Give the files a time a few hours before the movie time. A file that is
  too old starts a download at start-up. A file that is too new makes
  "Update now" say "Wait 2h00".
- The recording machine may have no network. Then a download must come
  from a local file. Say this on the end card.

## 2. The look

| Item | Rule | Reason |
|---|---|---|
| Frame | 1920x1080, 30 fps, H.264, yuv420p, `+faststart` | Plays in every browser and on GitHub. |
| Background | flat `#101010` | The red UI stays the brightest thing in the frame. |
| Main view | one large screen, 128 px x 7 = 896 px, nearest neighbour, at x 72, y 92 | Sharp pixels. The viewer reads the UI here. |
| Screen source | the bare 128x128 UI frames, not a crop of the photo | The photo scales the UI by 1.19 with smoothing, so a crop is blurred. |
| Device | the device photo with its own small screen and the keypad, 818 px wide, top right, as an illustration | It shows the real device in use and the glow of the pressed key. |
| Section title | Roboto Mono Bold 46 px, red `#ff3030`, numbered ("5  Follow with the mount") | The viewer knows where the story is. |
| Caption | Roboto Mono Regular 38 px, white, 34 characters a line, under the device photo, never on the large screen | Text on the screen hides the UI. |
| Caption text | Simplified Technical English: short sentences, key names in capitals (RIGHT, SQUARE, hold LEFT) | The viewer can do the same steps. |
| Title card | 4 s, title Bold 72 px red, two lines Regular 40 px white | Says what the feature does. |
| End card | 6 s, "Experimental", what is simulated, the pull request URLs | No viewer takes a simulation for a real sky. |
| Fades | 0.5 s at the start and the end of each card and of the body | Soft cuts, no flash. |

The fonts are in `fonts/` (`RobotoMono-Regular.ttf`, `RobotoMono-Bold.ttf`).

## 3. Pacing

- Wait 1 s after a menu key, 2 to 3 s after a key that opens a new screen,
  and 4 s on a screen that the caption explains.
- A caption stays at least 1 s for each 15 characters, and never less than
  5 s.
- Fast scrolling is fine (keys without a wait): the caption tells what
  happens.
- Cut the start-up and long waits (a slew, a countdown). Show the cut: a
  section title such as "Two minutes later".
- Total length: 60 to 120 s of body. Make two movies if the story is longer.

## 4. Editing

The edit is one ffmpeg `filter_complex`, made by a small Python script:

1. List the segments as (start, end) seconds of the take, with the section
   title and the captions of each segment.
2. For each segment, trim the bare screen and the photo with the same times,
   scale the screen with `flags=neighbor`, crop the device photo (screen and
   keypad, `crop=545:290:325:212`), put both on the
   background and draw the texts with `drawtext` (`textfile=`, so no quoting
   problems).
3. Concatenate the title card, the segments and the end card.
4. Make a contact sheet: one frame every 4 s, 6 columns
   (`fps=1/4,scale=480:-1,tile=6x6`). Look at it and at full frames.

No speed-up of the recording: the PiFinder reacts in real time, and the
movie shows that.

## 5. Checklist before publishing

- [ ] The movie was made with the code of the branch that the pull request
      has. Write the change ID or commit in the description of the upload.
- [ ] Every caption fits in the frame. No line is cut.
- [ ] Each caption tells what the screen shows at that time.
- [ ] No dead time: no screen stays more than 5 s without a caption that
      explains it.
- [ ] No error message that the story does not explain ("Download busy",
      "No location").
- [ ] No personal data: no home location, no Wi-Fi name, no observation
      log. Use the fake GPS and a separate HOME.
- [ ] The end card says what is simulated.
- [ ] The screen is sharp at full size (look at one full frame).

## 6. Worked example: the satellite movie

- Time: the clock starts at 13:29:10 UTC on 19 Nov 2026. CSS (TIANHE)
  rises at 13:30:30 and meets the mount at 13:33:39, 20 degrees high in the
  SW. The element sets come from the `stations`, `visual` and `amateur`
  groups of 14 Nov 2026.
- Story: the list (altitudes), Sat groups with Update now, the rise times,
  the ID marking menu, key 5 on CSS (TIANHE), the countdown to the meet
  point, the chart with the satellite and its track line, the description,
  an arrow ("Seen") and the follow.
- Take: 300 s. Movie: 122 s (4 s title, 112 s body in 8 segments, 6 s end
  card).
- Notes: the key script opens the satellite list once before Sat groups. The
  catalog then makes its first age check of the files, and Update now does
  not meet it ("Download busy"). The list sorts by the next pass, so the
  position of a satellite in the list changes with the time: run the take
  with the same clock each time.
