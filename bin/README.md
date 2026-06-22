# Cedar Detect binaries

This directory contains prebuilt **Cedar Detect** server binaries that the
PiFinder uses for star detection during plate solving:

| File | Platform |
|------|----------|
| `cedar-detect-server-aarch64` | 64-bit ARM (`aarch64`) |
| `cedar-detect-server-arm64`   | 64-bit ARM (`arm64`)   |

At runtime PiFinder launches the binary matching the host architecture as a
local gRPC server (see the application startup notes in the project `CLAUDE.md`).

## Source

Cedar Detect is developed by Steven Rosenthal (**[smroid](https://github.com/smroid)**):

- Repository: <https://github.com/smroid/cedar-detect>

These binaries are built from that source and bundled here for convenience so
that PiFinder runs out of the box without a separate build step.

## License

Cedar Detect is published under the **Functional Source License, Version 1.1,
MIT Future License (`FSL-1.1-MIT`)**. A verbatim copy of that license, including
the upstream copyright notice, is kept alongside the binaries in
[`LICENSE-cedar-detect.md`](./LICENSE-cedar-detect.md).

In summary, the FSL grants broad rights to use, modify, and redistribute the
software for any *Permitted Purpose* — which includes internal use, and
non-commercial education and research — but **excludes a "Competing Use"**: making
the software available in a commercial product or service that substitutes for, or
offers substantially similar functionality to, Cedar Detect. (The license also
converts to the permissive MIT license five years after each version is released.)

> **Note:** This `FSL-1.1-MIT` license applies to **Cedar Detect** (the binaries in
> this directory). It is **separate from the GPL-3.0 license** that covers the
> PiFinder project itself (see the [`LICENSE`](../LICENSE) file in the repository
> root).

## PiFinder's commercial use is by express, separate permission

Because PiFinder is also offered as a commercial product, bundling and
distributing Cedar Detect with it falls outside the FSL's Permitted Purpose. The
PiFinder project does this under a **separate license granted expressly by the
copyright holder**, Steven Rosenthal — not under the public FSL-1.1-MIT terms.

The FSL itself anticipates this: *"The Software is available to be licensed under
different terms; please contact the copyright holder (Steven Rosenthal
smr@dt3.org) to discuss."* This separate grant covers the PiFinder project's use
only; it does not extend the right to commercial/competing use to anyone else
redistributing these binaries.

If you fork or redistribute PiFinder commercially, you are responsible for your
own compliance with the FSL-1.1-MIT terms or for arranging your own license with
the copyright holder.

Our thanks to [smroid](https://github.com/smroid) for supporting the PiFinder
project.
