# Recovery mode is the update screen in isolation, with a blind-rollback fallback — not a separate minimal tool

The recovery hold boots a stripped app entry running only the update screen (display + keypad; no camera/solver/positioning), so rescue gets the generation overview and the internet channels from the same code, screen, and install path users already know — one machinery, one set of bugs. Because that screen runs inside the possibly-broken generation, it is a *rung*, not the ladder: if recovery mode fails its own health check, the device falls back to a blind generation rollback to the newest confirmed generation with an on-screen message ([0005](./0005-self-arming-watchdog-confirmed-generations.md)).

## Considered options

- **Standalone minimal recovery tool (own renderer, own generation lister), rejected.** Smaller failure domain, but duplicates the generation list, manifest fetch, install trigger, and keypad/display handling — a second UI that rots separately from the real one, for a rung the blind fallback already backstops.
- **Blind rollback only (no interactive mode), rejected.** Works when everything is broken, but forces the newest-confirmed choice on the user; the "it's broken" scenario often wants *a specific* known-good version or a fresh install from a channel.

## Consequences

- Selection semantics are **sticky**: choosing a generation sets the boot default (a telescope user in recovery means "go back until I say otherwise"), never a one-shot boot. Internet picks go through the ordinary upgrade flow and face a normal trial.
- Recovery mode inherits the update screen's offline behavior: no network degrades to "rollback only".
- The app's readiness signal (health check) pulls double duty: it is also what decides whether recovery mode itself is alive or the blind fallback fires.
