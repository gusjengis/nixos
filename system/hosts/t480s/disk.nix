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
          uuid = "4c1cf59c-7060-45f3-8b3e-7385e028ca7f";
          content = {
            type = "filesystem";
            format = "vfat";
            extraArgs = [ "-i" "78C5D225" ];
            mountpoint = "/boot";
            mountOptions = [ "umask=0077" ];
          };
        };
        root = {
          start = "2101248s";
          end = "1000215149s";
          label = "root";
          uuid = "c798f2f1-bf08-45ce-b5ba-767df1b6f8a1";
          content = {
            type = "filesystem";
            format = "ext4";
            extraArgs = [ "-U" "bbb7f520-98ab-4396-8e88-1f68348c669c" ];
            mountpoint = "/";
          };
        };
      };
    };
  };
}
