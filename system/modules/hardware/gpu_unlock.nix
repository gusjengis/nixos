{
  config,
  pkgs,
  lib,
  ...
}:

let
  cfg = config.gpu-unlock;

  # Zagitta/gpu-unlock, pinned. The module and its firmware extraction scripts
  # must stay in step with each other since both come from this tree.
  rev = "7eb51bccae0a0b7e599e084d971170e9a1e82d0c";
  src = pkgs.fetchFromGitHub {
    owner = "Zagitta";
    repo = "gpu-unlock";
    inherit rev;
    hash = "sha256-1KD/J1S1uyI5GGoTwQ1cU/sXeEKlG54exSvi6U+j73M=";
  };

  # Both the NVIDIA inputs (whose generated boot assets the extraction scripts
  # turn into firmware) and the resulting firmware path the module requests
  # are pinned by the module at 610.43.03. The unlock technique itself is
  # driver-version agnostic; only the extracted firmware depends on this.
  nv = "610.43.03";
  kernelModuleSource = pkgs.fetchurl {
    name = "NVIDIA-kernel-module-source-${nv}.tar.xz";
    url = "https://download.nvidia.com/XFree86/NVIDIA-kernel-module-source/NVIDIA-kernel-module-source-${nv}.tar.xz";
    hash = "sha256-fhGJI8eiPtw2EU1jJzpG4+BOmvmGlaQiA+esLf6fwdw=";
  };
  driverInstaller = pkgs.fetchurl {
    name = "NVIDIA-Linux-x86_64-${nv}-no-compat32.run";
    url = "https://download.nvidia.com/XFree86/Linux-x86_64/${nv}/NVIDIA-Linux-x86_64-${nv}-no-compat32.run";
    hash = "sha256-4IRFHbcwpt8p09dPZVdJxNI248lF99lLUgXoQxj+L5A=";
  };

  # The 16 firmware names the module's recipes.h requests, without the
  # gpu-unlock/610.43.03/ prefix it asks for at runtime.
  firmwareFiles = [
    "gsp_ga10x.bin"
    "gsp_tu10x.bin"
    "falcon_loader.bin"
    "gsp_boot_ga102.bin"
    "gsp_boot_desc_ga102.bin"
    "booter_load_ga102.bin"
    "gsp_boot_ga100.bin"
    "gsp_boot_desc_ga100.bin"
    "booter_load_ga100.bin"
    "gsp_boot_ad102.bin"
    "gsp_boot_desc_ad102.bin"
    "booter_load_ad102.bin"
    "gsp_boot_tu102.bin"
    "gsp_boot_desc_tu102.bin"
    "booter_load_tu102.bin"
    "sec2_bl_tu102.bin"
  ];

  firmwarePack =
    pkgs.runCommand "gpu-unlock-firmware-${nv}"
      {
        # The module requests plain file names and the initramfs builder also
        # just looks for .xz/.zst alternates of those, so keep the real files
        # uncompressed; upstream's firmware is only a few hundred KB total.
        compressFirmware = false;
        nativeBuildInputs = [
          pkgs.python3
          pkgs.zstd
        ];
      }
      ''
        set -eu
        tar -xf ${kernelModuleSource} -C ./
        python ${src}/firmware/extract_gsp.py ${driverInstaller} ./fw
        python ${src}/firmware/extract_boot_assets.py ./NVIDIA-kernel-module-source-${nv} ./fw
        mkdir -p $out/lib/firmware/gpu-unlock/${nv}
        ${lib.concatStrings (map (f: "cp ./fw/${f} $out/lib/firmware/${fwPath f}\n") firmwareFiles)}
        install -Dm644 ./fw/NVIDIA-LICENSE $out/share/licenses/gpu-unlock-firmware/NVIDIA-LICENSE
        install -Dm644 ${src}/firmware/NOTICE.md $out/share/licenses/gpu-unlock-firmware/NOTICE.md
      '';

  fwPath = f: "gpu-unlock/${nv}/${f}";

  modulePack = pkgs.callPackage ./gpu_unlock-module.nix {
    inherit src;
    kernel = config.boot.kernelPackages.kernel;
  };
in
{
  options.gpu-unlock.enable = lib.mkEnableOption ''
    Zagitta gpu-unlock: removes the market-segmentation cap on GeForce 20/30/40
    series tensor cores (up to 2x BF16/TF32 FP32-accumulation throughput). It
    runs as a kernel module loaded in the initramfs, ahead of the NVIDIA
    driver, and records an "unlocked" count per card in dmesg. On suspend or
    resume the unlock is reapplied before the driver wakes each card.
  '';

  config = lib.mkIf cfg.enable {
    # "all" unlocks every supported unbound card on the machine, one each,
    # which is exactly the shape for hosts built with one or two 3090s.
    boot.kernelParams = [ "gpu_unlock.targets=all" ];

    hardware.firmware = [ firmwarePack ];

    # Same tree that stage 2 runs from; lets a manual `modprobe gpu_unlock`
    # test after boot re-request the firmware. The card has been bound by
    # nvidia by then, so the module refuses it instead of touching it.
    boot.extraModulePackages = [ modulePack ];

    boot.initrd.kernelModules = lib.mkBefore [ "gpu_unlock" ];
  };
}
