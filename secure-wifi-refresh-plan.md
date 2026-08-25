# PR #311 "More secure WiFi configuration" — release-readiness plan

*Prepared 2026-08-24; revised the same day for EN 18031 (EU RED cybersecurity): new units must ship with an encrypted AP and a per-unit random password. PR: #311 (branch `secure-wifi`, Jens Scheidtmann), implements #179. The vocabulary for this plan is defined in [docs/ax/network/CONTEXT.md](docs/ax/network/CONTEXT.md); the shipped-posture decision is [ADR 0034](docs/adr/0034-ap-provisioning-ssid-tokens-encrypted-default.md).*

## Where the PR stands

- Last commit May 2025; 386 commits behind main; GitHub shows CONFLICTING.
- Feature set as built and hardware-tested by the author (10-point checklist, April 2025):
  - **Boot-time AP provisioning via SSID tokens**: `CHANGEME` in the hostapd SSID → replaced with `PiFinder-XXXXX` (5 random chars); `ENCRYPTME` → WPA2 enabled with a generated 20-char passphrase (`xxxxx-xxxxx-xxxxx-xxxxx`). The PR shipped `ssid=PiFinder-CHANGEME` — random name by default, encryption opt-in. **The refresh changes this default** (see Decisions: EN 18031 requires new units to ship encrypted).
  - **"Connect WiFi" screen** under Start (new `ui/wifi_password.py`, 307 lines): QR-code view (scannable WiFi join code), plain-password view (color-coded chars), client-mode view showing the connected SSID; marking menu with a jump to WiFi Mode; help screens (`help/wifi_connect/1-3.png` + `.xcf`).
  - **Web Network page**: encryption checkbox (when AP is open), AP password field with length validation (8–63), WiFi country field validated against ISO 3166, error display.
  - `main.py` runs `Network.configure_accesspoint()` at startup; `sys_utils_fake` mirrors the API for dev.
  - Docs edits to `user_guide.rst`, `quick_start.rst`, `build_guide.rst`.
- Review history that shaped it: brickbots rejected "recommend ethernet" and suggested the QR code; mrosseel flagged the support burden of forced random passwords → the PR went opt-in. Only a COMMENTED review; never approved.

## What moved under it on main (semantic drift — the real work; textual conflicts are small)

1. **Web server migrated Bottle → Flask/Jinja2 + waitress.** `views/network.tpl` is now `views/network.html`, `request.forms` → `request.form`, rendering via `app.jinja_env`. The PR's server.py + template changes must be **ported, not merged**.
2. **Docs restructured** (rev4 docs plan): WiFi + web-interface prose moved from `user_guide.rst` to **`connectivity.rst`**. The PR's user_guide edits must be rewritten against the new page. `PiFinderAP` is named ~6× in connectivity.rst and once in user_guide.rst.
3. **Three display geometries now** (128×128 OLED/ST7789-128, 176×176 rev4 SSD1333, 320×240 ST7789; titlebar heights 17/20/22). `wifi_password.py` hardcodes 128px geometry (8px char cells, 16-char password wrap, fixed 16px line steps, `len(ssid) > 14` breaks). Help PNGs are fine — base.py normalizes 128×128 help art onto any panel.
4. **i18n**: a `zh` locale now exists (PR predates it). The PR's hand-merged `.po`/`.mo` churn (all conflicting) should be discarded and regenerated via `nox -s babel`; new strings need de/es/fr/zh translations.
5. **Unchanged, so the PR's approach still lands**: hostapd/wpa_supplicant stack in sys_utils (no NetworkManager on the Debian runtime), the Start menu, `__help_name__` help convention, marking-menu `menu_jump`/`label` conventions. Conflict hunks: 1 in sys_utils.py (append position), 3 in server.py (all in the rewritten web layer), 1 import block in menu_structure.py.
6. **NixOS migration touches WiFi config**: `nixos_migration_wifi.py` converts `wpa_supplicant.conf` into NetworkManager keyfiles when a device migrates to NixOS. Client networks the PR writes carry forward fine; the AP provisioning story (runtime hostapd.conf edits) has **no** NixOS equivalent — ADR 0034 records this seam so the migration doesn't silently change a unit's AP posture.

## Defects found reading the diff (fix during refresh)

1. **`ENCRYPTME` is never stripped from the SSID** → `configure_accesspoint` rewrites the config + backup on every boot, and if used without `CHANGEME` the token is broadcast in the SSID forever. Strip tokens after provisioning; make boot a no-op when nothing to do. **Ship-blocking under the EN 18031 posture**: every new unit now ships with `ENCRYPTME` active, so every new unit exercises this path on every boot.
2. **Broken test**: `test_generate_five` asserts a dash at index 12; the dashes in `xxxxx-xxxxx-xxxxx-xxxxx` are at 5/11/17. Fails whenever the module imports (it will on CI Linux). Also typos ("aftger thrid").
3. **Password-field sentinel leak**: the form pre-fills `get_ap_pwd()`, which returns `"<no password defined>"` for open APs — submitting can set the sentinel as the passphrase, and prefilled passwords land in served HTML. Don't prefill; handle the sentinel/None explicitly.
4. **Lint/style**: bare `except:` in `set_ap_wifi_country` (E722), commented-out debug lines, f-string logging; must pass current `nox -s lint` / `type_hints`.
5. **Passphrase staged in world-readable `/tmp/hostapd.conf`** before the sudo copy. Use a 0600 temp file (or sudo tee).
6. Template typo "Acess Point WiFi Name"; web error strings not localized (match main's current Flask i18n convention).
7. A stray `debug()` was added in server.py's port-8080 path — dies with the Flask port; don't reintroduce.
8. QR image is LANCZOS-resized (`resize(..., 1)`); use explicit NEAREST — antialiasing softens QR modules and hurts scanning.
9. **Docs bugs**: invalid `.. stop::` directive (docs build will complain); the "Reset Access Point" recovery section references `pi_config_files/hostapd-open.conf` **which the PR never adds** (add it — critical-path under the new posture, and it must not carry `ENCRYPTME`: a recovered unit has to stay open until the user re-encrypts, see ADR 0034), and a `switch-ap.sh` script name to verify; user_guide claims the AP "will be encrypted using WPA2" — now true for fresh images under the EN 18031 posture, but still wrong for field-upgraded units, so the docs must distinguish the two.
10. **Drive-bys to drop**: `help/object_details/2.xcf`, the quick_start "Observation Session Checklist" (fine idea, separate PR).

## Decisions to settle (grill-with-docs input)

- **Shipped security posture — SETTLED (2026-08-24)**: for **EN 18031 compliance (EU RED cybersecurity regulations), new units must ship encrypted with a per-unit random WiFi password**. The default `pi_config_files/hostapd.conf` ships with both tokens active (`ssid=PiFinder-CHANGEME-ENCRYPTME`), so first boot provisions a random SSID **and** WPA2 with a generated passphrase. This reverses the PR's shipped default. Recorded as ADR 0034.
  - **New vs field-upgraded units**: tokens exist only in fresh images, so a software upgrade never force-encrypts an existing unit's AP — field units keep their config, new units placed on the market start encrypted. This distinction is what makes the token design load-bearing.
  - **Consequences**: the Connect WiFi QR screen and the documented recovery path stop being conveniences and become the mandatory first-boot UX. mrosseel's support-lockout concern is now *mitigated, not avoided* — a unit whose UI fails to start presents an encrypted AP nobody can join, so the recovery procedure and its bench validation move onto the critical path.
- **Token vocabulary under the new posture**: keep both tokens (`ENCRYPTME` alone lets a legacy/open unit opt in; `CHANGEME` alone is no longer a shippable default) or collapse to one? Recommend keeping both, documented as such — grill fodder.
- **May the web UI disable encryption?** Recommend no "disable" affordance on new units (keeps the compliance posture simple); legacy open APs keep the opt-in encrypt checkbox. Grill fodder.
- **Recovery-vs-compliance check**: the documented reset-to-open procedure requires physical access (SSH over ethernet / console + manual file copy). Confirm that's an acceptable posture under EN 18031 and record the outcome in ADR 0034.
- **First-boot discoverability**: with encryption mandatory, should first boot surface the Connect WiFi screen (or a hint) rather than relying on the user finding Start > Connect WiFi? Issue #179 originally asked for the password to be reachable from the main screens. Grill fodder.
- **Vocabulary/naming**: settled in [docs/ax/network/CONTEXT.md](docs/ax/network/CONTEXT.md) — the screen is the **Connect WiFi screen**; rename the module `wifi_connect.py` during the refresh.
- Whether the web page also needs a "regenerate password" affordance. Under the encrypted-by-default posture this gets more attractive (password rotation without SSH), but it's not required to ship — recommend deciding at the grill, defaulting to follow-up.
- Country entry: free-text with validation (as coded) vs dropdown — the author deliberately chose an entry box; keep unless grilling says otherwise.
- **Where provisioning runs**: `main.py` startup (as coded) vs the service unit. Keep, recorded in ADR 0034's scope (needs passwordless sudo, which the pifinder user has).
- **PR mechanics**: we can't push to Jens's fork branch, so refresh = new branch off main + superseding PR crediting Jens (`Co-authored-by`), after a courtesy comment on #311.

## Workstreams

### WS1 — Network bounded context + ADR *(landing via the docs PR that adds this plan)*
- `docs/ax/network/CONTEXT.md`: the Network glossary — WiFi mode, Access Point, provisioning token, new unit vs field-upgraded unit, AP passphrase, Connect WiFi screen, WiFi QR code, recovery reset.
- ADR 0034: "AP provisioning via SSID tokens: new units ship encrypted (EN 18031)" — the compliance trail for the posture decision, the #179/#311 history it supersedes, the token rationale, and the NixOS seam.
- CONTEXT-MAP.md: Network context + relationships (Network → UI, Network → NixOS).
- Grilling continues against these documents; open questions above are marked as such in ADR 0034.
- Side-note found while surveying: CONTEXT-MAP.md references `docs/ax/nixos/CONTEXT.md` + `docs/ax/nixos.md`, but neither exists on main — pre-existing inconsistency, worth a separate tiny fix.
- The architecture companion (`docs/ax/network.md`: provisioning flow, restart semantics, real-vs-fake seam) arrives with the code PR, once the code it describes exists on main.

### WS2 — Mechanical refresh
New branch off main; merge `origin/pr-311`; **change the shipped default to `ssid=PiFinder-CHANGEME-ENCRYPTME`** in `pi_config_files/hostapd.conf`; port the web layer to Flask/Jinja (network.html: encryption checkbox for legacy open APs, password + country fields, inline errors; `network_update` in Flask idiom); drop drive-bys; discard locale churn; add `qrcode` (verify a py3.9-compatible pin) + `types-qrcode`; get `nox -s lint type_hints smoke_tests unit_tests` green.

### WS3 — Correctness + hardening
The defect list above. Refactor the hostapd/wpa paths to injectable constants so provisioning logic is unit-testable with temp files.

### WS4 — Multi-resolution UI
Derive geometry from `display_class.resX/resY` + font metrics. Verify with screenshots of QR view, password view, long-SSID case at 128×128 and 320×240 (and the 176×176 layout if it can be driven off-hardware); machine-verify the QR by decoding the screenshot (pyzbar) and comparing the `WIFI:S:...;T:WPA;P:...;` payload — cheap, strong check. Prefer `image_util.make_red()` for the QR bitmap rather than qrcode's own fill colors, matching how help images are recolored.

### WS5 — i18n
`nox -s babel` extract/update/compile; translate the new strings for de/es/fr/zh (scope to tracked .po diffs).

### WS6 — User docs
- `connectivity.rst`: rewrite the AP story around the new first-boot reality — fresh images come up as `PiFinder-XXXXX`, WPA2, unique password, and **the QR screen (Start > Connect WiFi) is how you join** (`PiFinderAP` → `PiFinder-XXXXX` everywhere); web Network page fields; a section for field-upgraded units (still open unless they opt in via the encrypt checkbox or `ENCRYPTME`); AP reset/recovery appendix promoted to critical-path.
- `quick_start.rst`: the first-connection flow must now lead with the Connect WiFi QR screen — a new user cannot reach the web interface without it.
- `build_guide.rst`: bench-time WiFi setup section (port the PR's; the security rationale now stands on EN 18031 rather than the earlier over-claimed framing; keep proportionate per brickbots' feedback).
- Mention EN 18031 as the reason for the change in the release notes so field users understand why new images behave differently.

### WS7 — Tests
Unit (`@pytest.mark.unit`): provisioning idempotence, token stripping, passphrase generation, password-length + country validation — today none of the AP functions have any coverage. Web (`@pytest.mark.web` / Selenium): extend `test_web_network.py` for the encryption checkbox, error rendering, and country field. Fix the dash-index test.

### WS8 — Hardware validation + ship
- **First-boot validation on a fresh image is the headline test**: flash, boot, confirm the AP comes up as `PiFinder-XXXXX` with WPA2 and a unique passphrase, join via the QR screen with a phone, reach the web interface — with no other setup steps. This is every new builder's first experience; it must be bulletproof.
- **Upgrade validation**: apply the release to a unit with an existing (open or customized) AP config and confirm it is left untouched.
- Re-run Jens's 10-point checklist on real hardware, on **both** rev3 OLED and rev4 LCD; phone-scan the QR on both panels (red-on-black on the LCD is the open risk).
- Walk the documented recovery procedure end-to-end on hardware (it's now the only way back into a failed encrypted unit).
- Comment on #311, open the superseding PR against main crediting Jens, request brickbots/mrosseel review.

## Sequencing & effort

WS1 → WS2 → (WS3 + WS4 + WS5 in parallel) → WS6 + WS7 → WS8.
Rough effort: WS1 ~half-day, WS2 ~half-day, WS3+WS4 ~a day, WS5 small, WS6 ~a day, WS7 ~half-day. Hardware validation is the long pole and the only step that needs a physical unit.

## Risks

- **Lockout is now on the mainline path**: with new units encrypted by default, a unit whose UI fails to start presents an AP nobody can join. Mitigations: the recovery procedure (documented, hardware-walked in WS8) and making the first-boot path bulletproof. This was the maintainers' original objection to default encryption — EN 18031 overrides the preference, so the mitigation quality is what earns the merge.
- **Compliance scope**: this work implements the technical posture and ADR 0034 records EN 18031 as the driver; the broader conformity-assessment paperwork is out of scope here.
- **NixOS/Bookworm futures** (#499, NixOS channels) may replace runtime hostapd editing; contained by documenting the seam in ADR 0034, not blocked on it — but the encrypted-by-default posture must survive any migration.
- **Fork courtesy**: Jens may prefer to update #311 himself — ask before superseding. (Worth telling him the posture he originally wanted — encryption on by default — is now the requirement; EN 18031 vindicates his instinct.)
- **QR scan reliability on the LCD** — validate early in WS4/WS8, before docs promise it; under the new posture the QR screen is the primary join path, not a convenience.
