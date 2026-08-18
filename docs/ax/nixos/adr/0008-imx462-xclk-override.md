# The imx462 camera gets an explicit 74.25 MHz xclk overlay because fdtoverlay drops overlay parameters

**Status: proposed — pending a build on pi5 and a camera test on a device.**

PiFinder's imx462 camera module has a 74.25 MHz oscillator. The kernel's `imx290`/`imx462` DT overlays default the sensor xclk to 37.125 MHz; on Raspbian, PiFinder corrects this with an overlay *parameter* (`switch_camera.py` writes `dtoverlay=imx290,clock-frequency=74250000` to `config.txt`, applied by the RPi firmware loader). The NixOS image applies overlays with `fdtoverlay`, which **cannot apply overlay parameters** (`__overrides__`) — so the 37.125 MHz default silently survived. The driver (`imx290.c`) reads the sensor node's `clock-frequency` property and programs a per-frequency INCKSEL/PLL register set; with the wrong xclk the sensor enumerates on I2C but never delivers frames, and libcamera reports `Camera frontend has timed out` with an empty kernel log.

The image therefore compiles a small additional overlay, applied after the camera overlay, that sets `clock-frequency = 74250000` in both places the Raspbian parameter writes: the `cam1_clk` fixed-clock node (the driver `clk_set_rate`s it and errors on mismatch) and the sensor node property (selects the INCKSEL register set).

This supersedes an earlier draft of this ADR that blamed the kernel: the hypothesis was that the mainline `imx290` driver's lack of an imx462 model caused the failure, to be fixed by switching to `pkgs.linuxPackages_rpi4`. That was wrong on both ends — the image already runs the Raspberry Pi vendor kernel (the `nixos-hardware` `raspberry-pi-4` module pins the downstream tree, `stable_20250916` / 6.12.47, whose `imx290` driver does carry imx462 support), and the mr2 diagnosis that "verified" the DT clock at 37.125 MHz was in fact confirming the bug: 37.125 MHz matches the overlay default, not the hardware.

## Considered options

- **Compiled xclk-override overlay applied after the camera overlay (chosen).** Reproduces Raspbian's field-proven configuration (`sony,imx290lqr` compatible + 74.25 MHz xclk) exactly, using the overlay machinery `hardware.nix` already has. Relies on `fdtoverlay` merging the camera overlay's `__symbols__` so `&cam_node` resolves — same mechanism the existing custom overlays use against base-DT labels.
- **Switch to the vendor kernel via `boot.kernelPackages = pkgs.linuxPackages_rpi4`, rejected.** The earlier draft's fix. Redundant — nixos-hardware already pins the same vendor tree at the same tag — and actively harmful: it swaps in an equivalent-but-different kernel derivation, forcing a full kernel rebuild on pi5 and re-opening the u-boot/extlinux boot-chain question for zero functional change.
- **Use the kernel's `imx462.dtbo` (compatible `sony,imx462lqr`, dedicated init registers), deferred.** Arguably the "more correct" driver model, but it is not what PiFinder runs on Raspbian, it still needs the same xclk override, and it changes the libcamera tuning file (sensor name `imx462` vs `imx290`). Not worth the untested variables while getting the camera working; worth revisiting once streaming is confirmed.
- **Patch the camera overlay source and compile it ourselves, rejected.** Duplicates kernel dtsi includes into the flake for something a two-property override achieves.

## Consequences

- imx296 and imx477 are unaffected: on Raspbian PiFinder configures them without a clock parameter, so the overlay defaults are already correct and the override is gated on `cameraType == "imx462"`.
- No kernel change, so no new boot-chain risk and no kernel rebuild on pi5; the DTB derivation is the only thing that changes.
- The override must stay ordered after the camera overlay in the `fdtoverlay` invocation — `&cam_node` only exists in the merged symbol table at that point. A future refactor that reorders the overlay list will break it at DTB build time (fdtoverlay fails to resolve the symbol), not silently.
- If the sensor still does not stream with the correct xclk, the next suspects are the `imx462.dtbo` model path above and the libcamera/IPA tuning — not the kernel.
