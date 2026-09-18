{
  disko.enableConfig = false;

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
          uuid = "0cc6367c-c8ff-4639-8aee-cb10d7d9ce06";
          content = {
            type = "filesystem";
            format = "vfat";
            extraArgs = [ "-i" "F2FCC0B5" ];
            mountpoint = "/boot";
            mountOptions = [ "umask=0077" ];
          };
        };
        root = {
          start = "2101248s";
          end = "1953525101s";
          label = "root";
          uuid = "292a2dcc-c98d-440e-8392-aaec4edc9f84";
          content = {
            type = "filesystem";
            format = "ext4";
            extraArgs = [ "-U" "d2341c2e-194a-4b20-ba3a-06793c17f843" ];
            mountpoint = "/";
          };
        };
      };
    };
  };
}
