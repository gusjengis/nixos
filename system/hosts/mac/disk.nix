{
  disko.enableConfig = false;

  # Asahi owns this mixed APFS/Linux partition map. Never apply generic Disko
  # partitioning to this host; these boundaries are recovery documentation.
  disko.devices.disk.system = {
    type = "disk";
    device = "/dev/nvme0n1";
    content = {
      type = "gpt";
      partitions = {
        iBootSystemContainer = {
          start = "6s";
          end = "128005s";
          type = "69646961-6700-11AA-AA11-00306543ECAC";
          label = "iBootSystemContainer";
          uuid = "27dbb4cc-f56f-48ab-a50d-6df1e61806d8";
        };
        Container = {
          start = "128006s";
          end = "125715461s";
          type = "7C3457EF-0000-11AA-AA11-00306543ECAC";
          label = "Container";
          uuid = "e07c33c4-fca3-4a15-878f-0cfa84420cbc";
        };
        apfs-reserved-1 = {
          start = "125715462s";
          end = "134896645s";
          type = "7C3457EF-0000-11AA-AA11-00306543ECAC";
          label = "";
          uuid = "8d05507f-0582-4811-8709-0313099ba9d5";
        };
        apfs-reserved-2 = {
          start = "134896646s";
          end = "135506949s";
          type = "7C3457EF-0000-11AA-AA11-00306543ECAC";
          label = "";
          uuid = "0a71e457-fd05-4bd3-956a-3671d6c1a40a";
        };
        ESP = {
          start = "135506950s";
          end = "135629061s";
          type = "EF00";
          label = "";
          uuid = "5b5dbb66-dcbd-427d-8e4b-ea3adc0f0154";
          content = {
            type = "filesystem";
            format = "vfat";
            extraArgs = [ "-i" "4512161F" ];
            mountpoint = "/boot";
            mountOptions = [ "umask=0022" ];
          };
        };
        root = {
          start = "135629062s";
          end = "242965550s";
          type = "8300";
          label = "";
          uuid = "d3c3f0a5-4503-4c90-8d7a-554ea8ff1da5";
          content = {
            type = "filesystem";
            format = "ext4";
            extraArgs = [ "-U" "28a1d3d2-d96d-41f9-b7df-d3a81933ea68" ];
            mountpoint = "/";
          };
        };
        RecoveryOSContainer = {
          start = "242965551s";
          end = "244276259s";
          type = "52637672-7900-11AA-AA11-00306543ECAC";
          label = "RecoveryOSContainer";
          uuid = "39151a23-2da8-4005-9552-72623e74918b";
        };
      };
    };
  };
}
