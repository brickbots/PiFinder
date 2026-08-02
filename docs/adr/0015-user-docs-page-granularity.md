# User docs page granularity: arrival + separability

The user-facing doc set (`docs/source/`, the "Using your PiFinder" toctree group) needs a rule for whether a topic lives as a **section inside `user_guide.rst`** or as a **standalone page**. The historical split was accidental — `equipment` and `skysafari` were standalone while WiFi/Web Interface/Shared Data sat inside the user guide — and every reorganization re-litigated it. Decision: a topic gets a standalone page when **both** hold:

1. **Direct arrival** — readers land on it with a task in hand (from search, a Discord answer, or a cross-page link) rather than encountering it by reading the guide through. "How do I connect SkySafari?", "why is the image flipped?", "what catalogs are included?" are arrival questions.
2. **Separability** — cutting it leaves no gap in the user guide's operate-and-observe storyline; a one-sentence summary plus a link suffices in its place.

Everything else stays in `user_guide.rst`, whose charter is correspondingly narrowed: it is the **workflow reference** for operating and observing with the device — deeper than the Quick Start, deliberately not exhaustive (per-item enumeration belongs to `menu_map`), and **printable**: someone who prints only the user guide should get through a night of observing, so field-critical facts (power, shutdown, the WiFi-mode switch, `pifinder.local`) must at least be summarized there even when their full treatment lives elsewhere.

Applying the rule (June 2026): `equipment`, `skysafari`, `catalogs`, `menu_map`, `troubleshooting` stay standalone — each passes both tests. The connectivity block (WiFi modes, PiFinder address, Web Interface, Shared Data Access) **moves out** of the user guide into `connectivity.rst` ("Connecting to Your PiFinder"); the guide keeps a short Connectivity at-a-glance. `Power & Charging` and `Update Software` stay in-guide — both fail separability (core to operating; the update runs from the on-device Tools menu).

## Considered Options

- **Fold `equipment` and `skysafari` into the user guide** (the consolidation instinct that prompted this ADR). Rejected: both pass the arrival test, the merged guide would grow past 7k words against its printable-workflow charter, and `equipment.html` / `skysafari.html` URLs have been pasted into Discord answers for years — merging breaks them unless Read the Docs redirects are added and maintained.
- **External-boundary rule** ("standalone = the PiFinder's relationship to things outside itself"). Rejected: it splits the connectivity story mid-topic — the Web Interface is the device's own feature and would stay in-guide while SkySafari leaves, though both serve the same "reach the device from my phone" moment.
- **Content-type rule** (workflows in-guide; lookups and recipes standalone). Rejected: it cuts pages in half instead of placing them — `equipment`'s conceptual halves (magnification, flip/flop) would land in-guide while its CRUD steps went standalone.

## Consequences

- Standalone page URLs are treated as stable, linked-from-the-wild artifacts; merging a standalone page back into the guide carries a redirect cost and should be a deliberate, ADR-revising act.
- Moving a *section* between pages changes its anchor (`user_guide.html#wifi` → `connectivity.html#...`); old deep links degrade to page-top loads. Acceptable for sections, which is why the rule is applied at page grain.
- The docs skill's page table (`.claude/skills/docs/SKILL.md`) carries the operational one-liner of this rule and the per-page charters; keep the two in sync.
