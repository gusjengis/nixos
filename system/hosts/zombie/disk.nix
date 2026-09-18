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
          uuid = "5c8f3f2d-0943-4f3f-b6fd-5436b6bad4cb";
          content = {
            type = "filesystem";
            format = "vfat";
            extraArgs = [ "-i" "1D554442" ];
            mountpoint = "/boot";
            mountOptions = [ "umask=0077" ];
          };
        };
        root = {
          start = "2101248s";
          end = "1000215149s";
          label = "root";
          uuid = "144001a9-faa2-4fb6-89c7-fcd6d5ad10ab";
          content = {
            type = "filesystem";
            format = "ext4";
            extraArgs = [ "-U" "0e72e23a-5a69-4596-81ca-5915d16d40cf" ];
            mountpoint = "/";
          };
        };
      };
    };
  };
}
