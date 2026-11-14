# Reboot into Windows

PC-only launcher, deployed with the NixOS configuration. No Home Manager change
is needed: Vicinae discovers the system desktop entry.

The launcher asks for confirmation, defaulting to Cancel. Its only passwordless
sudo permission is an immutable, argument-free helper. The helper locates exactly
one active Windows Boot Manager pointing to Microsoft's EFI loader, sets and
verifies `BootNext`, then requests a normal reboot. It never writes `BootOrder`.
If firmware verification or reboot fails, it restores the previous `BootNext`
(or removes the new override if none existed).

Windows independently enforces the user's bedtime lockout, as confirmed by the
user. This feature does not change either OS's policy.

Safe regression tests (all firmware and reboot calls are mocked):

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s system/hosts/pc/windows-reboot -v
```

Deployment validation must not invoke the privileged helper: it really reboots.
The first actual Windows boot remains a user acceptance check.
