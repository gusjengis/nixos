{
  disko.enableConfig = false;

  # /dev/sda contains Windows data and is intentionally outside Disko.
  disko.devices.disk.system = {
    type = "disk";
    device = "/dev/nvme0n1";
    content = {
      type = "gpt";
      partitions = {
        ESP = {
          start = "4096s";
          end = "2101247s";
          type = "EF00";
          label = "EFI";
          uuid = "3caadd19-b7db-4272-9e18-420dba725fd9";
          content = {
            type = "filesystem";
            format = "vfat";
            extraArgs = [ "-i" "93AAC4BE" ];
            mountpoint = "/boot";
            mountOptions = [ "umask=0077" ];
          };
        };
        root = {
          start = "2101248s";
          end = "1000206833s";
          label = "root";
          uuid = "6805ac1e-78bb-4300-a11f-d06cccef6a9a";
          content = {
            type = "filesystem";
            format = "ext4";
            extraArgs = [ "-U" "e4e6ae8a-f05f-48b3-9ac6-79c80c22cadc" ];
            mountpoint = "/";
          };
        };
      };
    };
  };
}
