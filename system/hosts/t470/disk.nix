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
          uuid = "8f23064d-d144-48e5-9b28-ae7373333634";
          content = {
            type = "filesystem";
            format = "vfat";
            extraArgs = [ "-i" "6ED9A2F0" ];
            mountpoint = "/boot";
            mountOptions = [ "umask=0077" ];
          };
        };
        root = {
          start = "2101248s";
          end = "500118125s";
          label = "root";
          uuid = "531f23a7-5cfb-438c-94f7-7a25f4c63e52";
          content = {
            type = "filesystem";
            format = "ext4";
            extraArgs = [ "-U" "594937ce-2d92-4653-a366-392fb7907d08" ];
            mountpoint = "/";
          };
        };
      };
    };
  };
}
