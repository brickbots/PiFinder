# AP provisioning via SSID tokens: new units ship encrypted (EN 18031)

Fresh images ship their access point pre-configured as `ssid=PiFinder-CHANGEME-ENCRYPTME`. First boot consumes the tokens: `CHANGEME` becomes a random `PiFinder-XXXXX`, `ENCRYPTME` becomes WPA2 with a passphrase generated on that unit and shown nowhere but its own screen. Consuming a token strips it from the SSID. A software upgrade never provisions — units already in the field keep whatever AP they have, open or not.

## Why the default flipped

Issue #179 asked for exactly this in 2024: encrypted AP, random per-unit password. Review on PR #311 talked it down to opt-in, for a reason that was and is real: if the UI fails to start, an encrypted AP is one nobody can join, and the fallback is reading a 20-character password off a 1.5-inch screen — mrosseel called it a support nightmare. The QR code came out of that same thread (brickbots) as the mitigation, and the PR settled on "random name by default, encryption if you ask for it".

EN 18031 — the EU cybersecurity baseline backing the Radio Equipment Directive — takes the choice away for units placed on the EU market: an open-by-default radio configuration with no per-unit credentials is no longer shippable. So the 2025 preference lost to a 2025 regulation, and the objection converts into a mitigation bill rather than a veto: the Connect WiFi screen (QR join) and the recovery reset are now load-bearing, and both get validated on real hardware, on every panel type, before release.

## Why tokens in the SSID

A per-unit secret cannot be baked into a shared image — every builder flashes the same published file, so anything the image contains is by definition not unique. Whatever the mechanism, credentials must be *generated* at first boot, which needs a durable marker for "not yet generated".

The SSID itself is that marker. It lives in the exact file being provisioned, so it survives image flashing by construction and cannot drift out of sync with the thing it describes; there is no sidecar state file to lose or contradict. It is also self-describing in failure: a `PiFinder-CHANGEME` showing up in a phone's WiFi list tells you precisely which step never ran.

Stripping the token on consumption is what makes the boundary work: "tokens present" and "work to do" become the same predicate, provisioning is idempotent, and a field-upgraded unit (no tokens) is untouched with no version arithmetic at all. The #311 draft never stripped `ENCRYPTME` — under this default that means every new unit rewrites its config on every boot, which is why token stripping is the first defect the refresh fixes rather than a nice-to-have.

## Considered options

**A fixed default passphrase in the image** — a universal default credential is the exact thing the regulation exists to forbid.

**Generate credentials at image build time** — gives every copy of a published image the same "unique" secret. The same failure, one step removed.

**Force-encrypt field units on upgrade** — would break every saved phone connection in the installed base, unannounced, for devices the placed-on-market rule was not aimed at. The token mechanism gets us the honest split for free: fresh image provisions, existing config is left alone.

**A sidecar "provisioned" flag file** — duplicate state that can disagree with the config it describes, and one more thing a partial flash or manual edit can strand.

**NetworkManager-based provisioning** — not the Debian runtime today; hostapd's config is the source of truth. Noted for the NixOS future below rather than adopted early.

## Consequences

**The Connect WiFi screen is the primary join path.** A new unit's user cannot reach the web interface without it, so it must render and scan on every panel (128×128, 176×176, 320×240) and its QR payload gets machine-verified in tests.

**The recovery reset must restore an AP that stays open.** If the recovery configuration carried `ENCRYPTME`, the next boot would re-encrypt and lock the user out of the unit they just recovered — so it restores an open AP (random name via `CHANGEME` is fine) and the user re-encrypts from the web interface. Recovery requires physical access; whether that posture fully satisfies EN 18031 is confirmed as part of the refresh, and recorded here when it is.

**The NixOS migration must not undo this.** `nixos_migration_wifi.py` carries client networks into NetworkManager keyfiles; it has no AP-provisioning equivalent, so without deliberate work a migrated new unit could come back with a different AP posture than it shipped with. Tracked in the refresh plan.

**Deliberately not settled here**, expected to resolve during the refresh: whether the web interface may disable encryption on a provisioned unit (leaning no); whether the two tokens collapse into one (leaning no — `ENCRYPTME` alone is the opt-in path for field units); whether first boot should surface the Connect WiFi screen unprompted (#179 asked for the credentials to be reachable from the main screens).
