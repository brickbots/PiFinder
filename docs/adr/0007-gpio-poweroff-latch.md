# GPIO14 power-off latch via the `gpio-poweroff` overlay (active-low, ungated)

## Context

Rev4 PiFinder hardware can cut its own power: driving **GPIO14 low** trips the
**LTC2954** power-button controller, which drops **EN** on the **TPS61088** SYS
boost and removes power. We want the OS to assert this only as the *last* step of
shutdown, after filesystems are safely down.

## Decision

Provision the kernel **`gpio-poweroff` device-tree overlay** in
`pifinder_setup.sh`: `dtoverlay=gpio-poweroff,gpiopin=14,active_low`. Its
power-off handler runs in the kernel *after* systemd has stopped services and
unmounted/remounted filesystems read-only — strictly later than any user-space
hook, and only on a real power-off (reboot takes a different kernel path). We
also disable the serial console (remove the `console=serial0` kernel arg and mask
`serial-getty@ttyAMA0`) so the kernel stops driving console bytes onto GPIO14,
its default UART0 TXD function and now our kill line.

## Why active-low + the hardware pull-up

The latch cuts power on a **low**, so the overlay is `active_low`: GPIO14 is held
**high (power on)** during normal operation and only driven low in the power-off
handler. `active_low` normally risks self-power-off during early boot and during
reboot — the pin is undriven in those windows — for which the overlay README
suggests a custom `dt-blob.bin`. We rely instead on the **hardware pull-up
already present on GPIO14**, which holds the pin high (power on) until the kernel
handler explicitly pulls it low. The scheme is fail-safe: nothing but the kernel
power-off handler ever cuts power.

**Acceptance check:** a `reboot` must come back up, not power off — to be verified
on real hardware before this is trusted.

## Ungated across hardware revisions

The overlay is added unconditionally rather than gated on the rev4 BQ25895 probe.
On rev3 (no latch) GPIO14-low does nothing electrically; the only effect is that
`gpio-poweroff` changes the halt path, so `poweroff` logs a kernel WARN and waits
~3 s before halting — cosmetic on a board you power off by unplugging. Gating
would have required an I²C probe at provisioning time, which is unreliable because
the same script enables I²C only on the next boot.

## Consequences

- Loading `gpio-poweroff` disables waking the SoC by pulling GPIO3 low, and
  prevents the kernel's normal SoC reset on power-off — both expected.
- The serial console is no longer available for kernel diagnostics on rev4 units.
- This is the project's **first power-path *write***. It lives in
  firmware/device-tree, not application code, so the Battery context's "the
  Battery code never writes the power path" invariant is preserved — see
  `docs/ax/battery/CONTEXT.md` (term: *Power-off latch*).
