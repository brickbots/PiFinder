# Network (WiFi & Connectivity)

The Network context owns the device's WiFi identity and connections: whether the PiFinder broadcasts its own network or joins someone else's, how a fresh unit acquires a unique name and credentials at first boot, and how a phone or laptop gets connected to it. It is the vocabulary for the network half of `sys_utils`, the Connect WiFi screen, and the web interface's Network page.

## Language

### Modes

**WiFi mode**:
Which of two roles the device's radio plays: **AP** (the PiFinder broadcasts its own network) or **Client** (it joins an existing one). Exactly one is active at a time.
_Avoid_: "hotspot mode" (say AP), "station mode" (say Client).

**Access Point (AP)**:
The network the PiFinder itself broadcasts, named by its **SSID**. The hostapd configuration is the single source of truth for its identity: SSID, encryption, AP passphrase, country code.
_Avoid_: "hotspot".

**Client network**:
A saved network the PiFinder can join in Client mode (SSID plus credentials). The user manages the list from the web interface.
_Avoid_: "saved WiFi"; "home network" (a client network need not be at home).

### Provisioning

**Provisioning token**:
A marker embedded in a fresh image's AP SSID that first boot consumes: `CHANGEME` (generate a random SSID) and `ENCRYPTME` (enable WPA2 with a generated passphrase). Consuming a token strips it from the SSID — a token present at boot means work to do; no tokens means the unit is provisioned. Fresh images ship with both.
_Avoid_: "magic SSID"; leaving a token in the SSID after acting on it (that is the bug, not the design).

**New unit** vs **field-upgraded unit**:
The compliance boundary (EN 18031, see [ADR 0034](../../adr/0034-ap-provisioning-ssid-tokens-encrypted-default.md)). A **new unit** first-boots a fresh image, finds provisioning tokens, and provisions itself: random SSID, WPA2, unique AP passphrase. A **field-upgraded unit** took a software update over an existing configuration; its AP is left exactly as it was — an upgrade never provisions and never force-encrypts.
_Avoid_: reasoning from software version (the predicate is "tokens present", not "release N or later").

**AP passphrase**:
The WPA2 credential for an encrypted AP, generated on the unit itself at provisioning and shown nowhere but its own screen. User-facing surfaces display it as "Password".
_Avoid_: "PSK", "key" (implementation words); any shared or image-baked default value (per-unit uniqueness is the point).

**Country code**:
The regulatory domain the AP radio operates under (ISO 3166 two-letter code), set from the web interface.

### Connecting

**Connect WiFi screen**:
The on-device screen that gets another device onto the PiFinder: in AP mode a **WiFi QR code** or the SSID and AP passphrase in the clear; in Client mode the name of the network the PiFinder joined. For a new unit this is the primary join path, not a convenience view.
_Avoid_: "WiFi password screen" (it shows more than a password — see Flagged ambiguities).

**WiFi QR code**:
A QR encoding of the AP's SSID, security type, and AP passphrase in the standard `WIFI:` join format, which phone cameras turn into a one-tap connection.
_Avoid_: describing it as a link or URL (it is a credential payload, not a web address).

**Recovery reset**:
The documented physical-access procedure (console, or SSH over a network cable) that restores the AP to an open default so the user can get back in — the way into a unit whose encrypted AP cannot be joined because the screen cannot be read. The restored configuration must stay open until the user re-encrypts; deliberately not possible remotely.
_Avoid_: "factory reset" (nothing else is reset).

## Flagged ambiguities

- One screen, four names: the menu says "Connect WiFi", the module is `wifi_password.py`, the help folder is `wifi_connect`, the title bar says "WIFI". Canonical: **Connect WiFi screen**. The refresh should rename the module to match (`wifi_connect.py`).
- "Password" vs "passphrase": hostapd and the code say passphrase; screens and user docs say password. Canonical in code and internal docs: **AP passphrase**. User-facing text stays "password".

## Example dialogue

Dev: A user upgraded to the new release and their AP is still open. Bug?
Expert: No — field-upgraded unit. An upgrade must not touch their AP. Only a new unit provisions, and only because its image still carries the tokens.
Dev: And if they reflash that same device?
Expert: Then it first-boots a fresh image, finds `CHANGEME-ENCRYPTME` in the SSID, and comes up as a new unit: random SSID, WPA2, unique passphrase. Reflashing is how an old device becomes a new unit.
Dev: Screen is dead, AP is encrypted, they never wrote the passphrase down. Now what?
Expert: Recovery reset. Physical access, restore the open default, join it, re-encrypt from the web interface. If the recovery config carried `ENCRYPTME`, the next boot would lock them out again — which is why it must not.
