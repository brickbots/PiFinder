# The imx462 camera gets an explicit 74.25 MHz xclk overlay, because fdtoverlay drops overlay parameters

**Status: proposed.** It waits for a build on pi5 and a camera test on a Pi.

The PiFinder imx462 camera module has a 74.25 MHz oscillator. The kernel's `imx290` and `imx462` overlays set the sensor xclk to 37.125 MHz by default. On Raspbian, PiFinder corrects this with an overlay parameter: `switch_camera.py` writes `dtoverlay=imx290,clock-frequency=74250000` to `config.txt`, and the firmware applies it.

The NixOS image applies overlays with `fdtoverlay`, which cannot apply overlay parameters (`__overrides__`). So the 37.125 MHz default stayed. The driver (`imx290.c`) reads the sensor node's `clock-frequency` and programs INCKSEL and PLL registers for that frequency. With the wrong xclk, the sensor answers on I2C but sends no frames, and libcamera reports `Camera frontend has timed out` with an empty kernel log.

So the image compiles a small overlay, applied after the camera overlay, that sets `clock-frequency = 74250000` in the two places the Raspbian parameter sets:

- the `cam1_clk` fixed-clock node, which the driver sets with `clk_set_rate` and checks;
- the sensor node, which selects the INCKSEL register set.

An earlier draft blamed the kernel and proposed `pkgs.linuxPackages_rpi4`. That was wrong. The image already runs the Raspberry Pi vendor kernel (`nixos-hardware` `raspberry-pi-4`, `stable_20250916`, 6.12.47), and its `imx290` driver supports the imx462. A test on mr2 that "confirmed" 37.125 MHz in the DT confirmed the fault: that is the overlay default, not the hardware.

## Considered options

- **A compiled xclk overlay after the camera overlay (chosen).** It gives the configuration that works on Raspbian (`sony,imx290lqr` and 74.25 MHz), with the overlay code `hardware.nix` already has. It needs `fdtoverlay` to merge the camera overlay's `__symbols__`, so `&cam_node` resolves.
- **The vendor kernel through `boot.kernelPackages = pkgs.linuxPackages_rpi4`, rejected.** `nixos-hardware` already uses the same vendor tree, and the change would force a full kernel rebuild on pi5 for no change in function.
- **The kernel's `imx462.dtbo` (`sony,imx462lqr`), deferred.** It needs the same xclk override, it is not what Raspbian runs, and it changes the libcamera tuning file. It can be tried when the camera streams.
- **Patch and compile the camera overlay ourselves, rejected.** It copies kernel dtsi files into the flake for a change of two properties.

## Consequences

- imx296 and imx477 do not change. Raspbian sets no clock parameter for them, and the override applies only when `cameraType == "imx462"`.
- There is no kernel change and no kernel rebuild. Only the DTB derivation changes.
- The override must stay after the camera overlay in the `fdtoverlay` call, because `&cam_node` exists only then. If a later change moves it, the DTB build fails; it does not fail silently.
- If the sensor still sends no frames with the right xclk, the next steps are the `imx462.dtbo` model and the libcamera tuning, not the kernel.

Replaces NixOS ADR 0008.
