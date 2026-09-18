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
          uuid = "762ea26a-0902-4df3-85f1-3eeac7529367";
          content = {
            type = "filesystem";
            format = "vfat";
            extraArgs = [ "-i" "28F54137" ];
            mountpoint = "/boot";
            mountOptions = [ "umask=0077" ];
          };
        };
        root = {
          start = "2101248s";
          end = "3907029101s";
          label = "root";
          uuid = "812fdb64-9867-4903-8ff5-f44af7831a24";
          content = {
            type = "filesystem";
            format = "ext4";
            extraArgs = [ "-U" "4663dd71-b8e6-400c-a6b9-7c0944371ef8" ];
            mountpoint = "/";
          };
        };
      };
    };
  };
}
