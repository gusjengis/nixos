{
  disko.enableConfig = false;

  # Only nvme1n1 contains NixOS. nvme0n1 and sd[a-c] are Windows/data disks.
  disko.devices.disk.system = {
    type = "disk";
    device = "/dev/nvme1n1";
    content = {
      type = "gpt";
      partitions = {
        ESP = {
          start = "4096s";
          end = "1052671s";
          type = "EF00";
          label = "EFI";
          uuid = "8953b0ee-478a-4330-8e43-6af5a90250d0";
          content = {
            type = "filesystem";
            format = "vfat";
            extraArgs = [ "-i" "3216E304" ];
            mountpoint = "/boot";
            mountOptions = [ "umask=0022" ];
          };
        };
        root = {
          start = "1052672s";
          end = "7814031998s";
          label = "root";
          uuid = "3a8c467b-2835-4836-bb83-6eb7013f75a0";
          content = {
            type = "filesystem";
            format = "ext4";
            extraArgs = [ "-U" "a5290059-a27d-42bb-9ce7-10ef7f746400" ];
            mountpoint = "/";
          };
        };
      };
    };
  };
}
