# Disk layouts the installer can create.
#
# Existing machines do not use these. Their `system/hosts/<host>/disk.nix`
# files are sector-exact transcriptions of layouts that already exist on disk
# and carry `disko.enableConfig = false`, so they document a recovery layout
# without touching the running `fileSystems`. Only freshly installed machines
# get a layout from this file, with Disko in charge.
#
# Adding a layout here is how encryption or a hibernation-sized swap partition
# would arrive later; see notes/INSTALLATION_TODO.md. Nothing else in the
# repository needs to change to support one, which is the point of keeping the
# layout behind a name instead of inlining it into the installer.
{ lib }:
let
  layouts = {
    # GPT, an EFI system partition, and ext4 for everything else. This is what
    # every x86 machine in the fleet already runs.
    plain =
      {
        device,
        espSize ? "1G",
      }:
      {
        disko.devices.disk.system = {
          type = "disk";
          inherit device;
          content = {
            type = "gpt";
            partitions = {
              ESP = {
                size = espSize;
                type = "EF00";
                label = "EFI";
                priority = 1;
                content = {
                  type = "filesystem";
                  format = "vfat";
                  mountpoint = "/boot";
                  mountOptions = [ "umask=0022" ];
                };
              };
              root = {
                size = "100%";
                label = "root";
                content = {
                  type = "filesystem";
                  format = "ext4";
                  mountpoint = "/";
                };
              };
            };
          };
        };
      };
  };
in
{
  inherit layouts;

  names = lib.attrNames layouts;

  # Installer-facing entry point. Fails on an unknown name rather than
  # silently installing a layout nobody asked for.
  build =
    {
      layout,
      device,
      espSize ? "1G",
    }:
    if !(layouts ? ${layout}) then
      throw "unknown disk layout ${layout}; known layouts: ${lib.concatStringsSep ", " (lib.attrNames layouts)}"
    else
      layouts.${layout} { inherit device espSize; };
}
