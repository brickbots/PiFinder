# The `gpio-poweroff` overlay loads only on CM4 boards

## Context

[ADR 0007](0007-gpio-poweroff-latch.md) provisions
`dtoverlay=gpio-poweroff,gpiopin=14,active_low` unconditionally, judging the
rev3 side effect "cosmetic". Field experience says otherwise. Registering the
overlay **replaces** the firmware power-off handler rather than adding to it.
On boards with no latch on GPIO14 — v3 and earlier, all Raspberry Pi 4B —
the handler drives the pin low, nothing cuts power, the driver WARNs after
its ~3 s timeout (a backtrace easily read as a kernel panic), and the kernel
parks with rails and GPIO state frozen. The firmware halt never runs, so the
display keeps its last frame ("Shutting Down") indefinitely and the unit
never reaches its power-off state.

## Decision

Wrap the overlay in a `[cm4]` conditional section in `config.txt`:

```
[cm4]
dtoverlay=gpio-poweroff,gpiopin=14,active_low
[all]
```

The rev4 is the only CM4-based PiFinder; every earlier revision is a
Pi 4B, which never matches `[cm4]`. Note the asymmetry: `[cm4]` matches only
the Compute Module 4, while `[pi4]` would match the whole BCM2711 family —
Pi 4B included — and must not be used here. The firmware evaluates the
filter from the board revision code on every boot.

## Why this gate, and why gating is now acceptable

ADR 0007 went ungated because gating seemed to require a BQ25895 I²C probe
at provisioning time, before I²C is even enabled. The model filter removes
that premise: the *firmware* decides, on every boot, with no probe and no
provisioning-time knowledge. One image and one setup script still serve both
boards, and a card moved between units self-corrects at the next boot.

Considered and rejected:

- **`[gpio14=1]` strap** — rev4's hardware pull-up on GPIO14 doubles as a
  revision strap (v3 leaves the pin unconnected; the BCM default pull is
  down). It keys on the latch hardware itself, so it would extend to a
  future non-CM4 latched board unchanged — but it depends on default-pull
  behaviour and misreads if anything drives GPIO14 high at firmware time
  (e.g. a bootloader EEPROM with `BOOT_UART=1`). The model filter has no
  such failure mode.
- **Runtime self-heal** (rewrite `config.txt` from the BQ25895 probe at
  startup) — needs a boot to converge, so a freshly flashed v3 still hangs
  on its first shutdown.
- **systemd-shutdown hook instead of the overlay** — gives up ADR 0007's
  strictly-last, kernel-owned ordering, the property the overlay was chosen
  for.

## Consequences

- v3 and earlier regain the stock firmware power-off: the screen goes dark
  and the halt path completes, as before ADR 0007.
- Rev4 behaviour is unchanged once the overlay loads. ADR 0007's acceptance
  check (`reboot` comes back up, `poweroff` cuts power) must be re-run on
  rev4 hardware, plus the new v3 check: overlay absent from
  `/proc/device-tree`, shutdown ends fully dark.
- The gate is a **model proxy** for "has the power-off latch". A bare CM4
  booted outside a rev4 carrier (a bench IO board) loads the overlay and its
  `poweroff` parks exactly as v3 used to — visible during bring-up, and a
  usable signal that the latch path is dead. A future latched board that is
  not a CM4 needs its own filter section.
- ADR 0007's serial-console strip (`console=serial0` removal, masked getty)
  stays unconditional; it is independent of the overlay and harmless on the
  Pi 4B revisions.
- **No migration for deployed cards.** `pifinder_setup.sh` provisions the
  gated form, so it reaches the field only on newly built images; cards
  already carrying the ungated line sit in existing units, where reprovisioning
  isn't needed — on a rev4 the ungated and gated forms behave identically. The
  section is kept closed with `[all]` so later appends (camera overlays) stay
  unconditional.
- Amends [ADR 0007](0007-gpio-poweroff-latch.md): its "Ungated across
  hardware revisions" section is superseded.
