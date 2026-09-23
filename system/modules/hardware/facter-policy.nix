{
  config,
  lib,
  ...
}:

let
  report = config.hardware.facter.report;
  hardware = report.hardware or { };
  cpus = hardware.cpu or [ ];
  graphicsCards = hardware.graphics_card or [ ];
  usbDevices = hardware.usb or [ ];

  hasVendor =
    vendor: devices: lib.any (device: lib.hasInfix vendor (device.vendor.name or "")) devices;
  hasCpuFeature = feature: lib.any (cpu: lib.elem feature (cpu.features or [ ])) cpus;

  detected = {
    nvidiaGraphics = hasVendor "nVidia" graphicsCards;
    amdGraphics = hasVendor "AMD" graphicsCards || hasVendor "ATI" graphicsCards;
    intelCpu = lib.any (cpu: cpu.vendor_name or "" == "GenuineIntel") cpus;
    amdCpu = lib.any (cpu: cpu.vendor_name or "" == "AuthenticAMD") cpus;
    battery = laptopChassis;
    bluetooth = hardware.bluetooth or [ ] != [ ];
    fingerprint = lib.any (device: device.vendor.hex or "" == "06cb") usbDevices;
    virtualization = hasCpuFeature "vmx" || hasCpuFeature "svm";
  };

  # `hardware.system.form_factor` reports "laptop" on every machine in this
  # fleet, including the desktops, so it cannot distinguish portable hardware.
  # The SMBIOS chassis type does: desktops report 3, the ThinkPads report 10.
  # See system/install/lib/facter.nix for the identical rule used by Home
  # Manager and by the installer, which have no NixOS module system available.
  laptopChassis = lib.any (entry: lib.elem (entry.chassis_type.value or 0) portableChassisTypes) (
    report.smbios.chassis or [ ]
  );

  # SMBIOS 3.7.0 table 17: portable form factors.
  portableChassisTypes = [
    8 # Portable
    9 # Laptop
    10 # Notebook
    11 # Hand Held
    14 # Sub Notebook
    30 # Tablet
    31 # Convertible
    32 # Detachable
  ];
in
{
  options.repo.hardware.detected = lib.mapAttrs (
    _: value:
    lib.mkOption {
      type = lib.types.bool;
      readOnly = true;
      default = value;
    }
  ) detected;

  config = {
    nvidia.enable = lib.mkDefault detected.nvidiaGraphics;
    hardware.amdgpu.initrd.enable = lib.mkDefault detected.amdGraphics;
    hardware.bluetooth.enable = lib.mkDefault detected.bluetooth;
    hardware.cpu.intel.updateMicrocode = lib.mkDefault detected.intelCpu;
    hardware.cpu.amd.updateMicrocode = lib.mkDefault detected.amdCpu;
    services.fprintd.enable = lib.mkDefault detected.fingerprint;
    # This default is currently inert: system/modules/default.nix enables
    # upower unconditionally on every machine. Narrowing that to portable
    # hardware would change already-deployed desktop configurations, so the
    # detection is corrected here without acting on it.
    services.upower.enable = lib.mkDefault detected.battery;
  };
}
