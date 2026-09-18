# System Configuration

`system/hosts/default.nix` is the fleet roster. Each `system/hosts/<host>`
directory contains that machine's NixOS and hardware configuration, while
`system/modules` contains shared modules.

`flake.nix` exposes `nixosConfigurations.<host>` for every roster entry whose
`systemManaged` value is not false.

```bash
nix eval --raw ".#nixosConfigurations.pc.config.system.build.toplevel.drvPath"
```

Use `rebuild` for normal activation. Roll back through an older NixOS generation
from the boot menu or with `nixos-rebuild switch --rollback`.
