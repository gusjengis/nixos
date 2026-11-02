# Builds the Zagitta gpu-unlock kernel module for the host kernel. Upstream's
# firmware_610.c already declares its firmware paths with MODULE_FIRMWARE, so
# the NixOS initramfs builder copies them in with the module automatically.
{
  stdenv,
  lib,
  kernel,
  src,
}:

stdenv.mkDerivation {
  pname = "gpu-unlock-module";
  version = "2.0.0";
  inherit src;

  sourceRoot = "source/kernel/gpu_unlock";

  nativeBuildInputs = kernel.moduleBuildDependencies;

  makeFlags = [
    "KDIR=${kernel.dev}/lib/modules/${kernel.modDirVersion}/build"
  ];

  installPhase = ''
    runHook preInstall
    install -Dm644 gpu_unlock.ko \
      $out/lib/modules/${kernel.modDirVersion}/gpu_unlock.ko
    runHook postInstall
  '';

  enableParallelBuilding = true;

  meta = {
    description = "gpu-unlock: full-rate tensor cores for GeForce 20/30/40 series";
    homepage = "https://github.com/Zagitta/gpu-unlock";
    license = lib.licenses.gpl2Only;
    platforms = [ "x86_64-linux" ];
  };
}
