# Giving brickbots/PiFinder access to the Attic cache

The NixOS CI builds substitute from the self-hosted Attic cache
`cache.pifinder.eu/pifinder` (ADR 0004). There are two levels of access:

| Access | Needs a token? | Who | Status |
| ------ | -------------- | --- | ------ |
| **Pull** (download prebuilt paths) | No — public, via the cache's public key | everyone, incl. fork PRs | ✅ already wired in the workflows |
| **Push** (upload build results) | **Yes** — `ATTIC_TOKEN` secret | trusted (non-fork) runs only | ⬇️ optional, set up below |

**Pull already works with no setup.** The workflows configure the public
substituter directly:

```
extra-substituters = https://cache.pifinder.eu/pifinder
extra-trusted-public-keys = pifinder:8UU/O3oLkaJHHUyqEcPGl+9F1m4MqDca39Ewl49jBmE=
```

So brickbots PR builds (and the hosted `ubuntu-24.04-arm` runner) download from
the cache without any secret. GitHub never exposes secrets to **fork** PRs, which
is why push is gated and pull must be tokenless.

You only need the steps below if you want **brickbots' own CI builds** (pushes to
its `main`/branches, or maintainer-triggered runs) to **upload** their results so
the shared cache stays warm.

## 1. Mint a push token (mrosseel — cache admin)

On the Attic server (the cache lives in `nixos-config`,
`machines/general-server/attic-service.nix`):

```bash
# Scope the token to the `pifinder` cache: pull + push, 1-year validity.
atticd-atticadm make-token \
  --sub "brickbots-ci" \
  --validity "1y" \
  --pull "pifinder" \
  --push "pifinder"
```

This prints a JWT. Treat it as a secret. Scope it to **only** the `pifinder`
cache (not `pifinder-release`) so a leak can't poison release closures.

## 2. Add it as a repo secret (brickbots — maintainer)

In **github.com/brickbots/PiFinder**:

1. **Settings → Secrets and variables → Actions → New repository secret**
2. Name: `ATTIC_TOKEN`
3. Value: the JWT from step 1
4. Save.

(Use an **organization** secret instead if more than one repo needs it.)

## 3. That's it

The workflows already do the right thing once the secret exists:

- **With `ATTIC_TOKEN`** (brickbots' own branch pushes / trusted runs): the
  `Attic login for push` step logs in and the `Push to Attic` step uploads.
- **Without it** (fork PRs): those steps no-op; the build still pulls from the
  public cache and is verify-only.

No workflow edits are required on the brickbots side — the logic keys off whether
the secret is present.

## Security notes

- The token is exposed only to non-fork runs, so external contributors' fork PRs
  can never push, even after this is set up.
- Rotate by minting a new token and updating the secret; revoke the old one on
  the Attic server.
- Keep push scoped to `pifinder` (dev cache). Release closures go to
  `pifinder-release` via the separate, mrosseel-only release workflow.
