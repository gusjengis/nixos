{
  config,
  lib,
  ...
}:

# Shared network data drive client.
{
  options.dataDrive.client.enable = lib.mkEnableOption "mount the shared data drive at /data";

  config = lib.mkIf config.dataDrive.client.enable {
    boot.supportedFilesystems = [ "nfs" ];

    fileSystems."/data" = {
      device = "alpha:/data";
      fsType = "nfs";
      options = [
        "nfsvers=4.2"
        # hard: operations block until the server returns rather than
        # erroring out; no silent data corruption on flaky links.
        "hard"
        "noatime"
        "_netdev"
        "nofail"
        # Mount lazily on first access instead of at boot, and unmount
        # again after 10 minutes idle. Combined with nofail this keeps
        # boot and shutdown from hanging when alpha is unreachable.
        "noauto"
        "x-systemd.automount"
        "x-systemd.idle-timeout=600"
        "x-systemd.mount-timeout=30s"
      ];
    };
  };
}
