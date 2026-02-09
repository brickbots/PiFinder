# NixOS Migration Status

## What Works
- **PWM LEDs** - Fixed with proper pinctrl overlay routing PWM0_1 to GPIO 13
- **Boot splash** - Static red splash screen on OLED during boot
- **PAM authentication** - Fixed /etc symlinks using /etc/static
- **Netboot** - TFTP/NFS working with u-boot → extlinux chain
- **CI/CD** - Pi5 native builds on self-hosted runner with ubuntu-latest fallback
- **Cachix** - pifinder.cachix.org for binary cache

## Recent Fixes (this session)
1. PWM overlay: added pinctrl to route PWM signal to GPIO 13
2. Boot splash: changed to static mode (no animation)
3. PAM symlinks: use `/etc/static/pam.d` not direct closure paths
4. CI workflow: use Pi5 `[self-hosted, aarch64]` runner, fallback to ubuntu-latest
5. pifinder service: `Type=simple` instead of `Type=idle` (was causing ~2min delay)
6. Deploy script: `rm -rf pam.d` before symlink (can't overwrite directory)

## Commits Pushed (nixos branch)
- `957b55e` - fix: PWM overlay pinctrl and boot splash improvements
- `f00b041` - ci: use Pi5 native runner with ubuntu-latest fallback
- `78c1eb9` - fix(ci): use correct flake output names
- `721e59b` - fix: use /etc/static for symlinks in deploy script
- `258a367` - fix: use Type=simple for pifinder service
- `bf4d561` - fix: remove pam.d before symlink in deploy script

## Known Issues / TODO
1. ~~**WiFi kernel oops**~~ - CLOSED: Just a harmless FORTIFY_SOURCE warning in brcmfmac driver (struct flexible array declared as 1-byte field). WiFi hardware works fine. Using ethernet for netboot anyway.
2. **Python startup slow** - 1m46s between systemd starting service and Python first log. Not systemd delay - it's Python import/NFS latency. Consider:
   - Lazy imports
   - Local caching of Python bytecode
   - Profiling import time with `python -X importtime`
3. **IP changes** - Pi getting different DHCP IPs (146, 150) - consider static IP
4. **Samba** - Taking 10.7s at boot, do we need it?
5. **firewall.service** - Taking 16s, could optimize or disable if not needed

## Files Changed
- `nixos/hardware.nix` - PWM overlay with pinctrl
- `nixos/services.nix` - boot-splash static, pifinder Type=simple
- `nixos/pkgs/boot-splash.c` - static mode, red color fix
- `flake.nix` - initrd splash changes
- `deploy-image-to-nfs.sh` - /etc/static symlinks, rm before ln
- `.github/workflows/build.yml` - Pi5 runner, fallback, correct flake outputs

## Deploy Command
```bash
./deploy-image-to-nfs.sh
```

## Test After Reboot
```bash
ssh pifinder@192.168.5.146 "systemd-analyze blame | head -10"
ssh pifinder@192.168.5.146 "journalctl -u pifinder --no-pager | head -20"
```
