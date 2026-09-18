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
    battery = hardware.system.form_factor or "" == "laptop";
    bluetooth = hardware.bluetooth or [ ] != [ ];
    fingerprint = lib.any (device: device.vendor.hex or "" == "06cb") usbDevices;
    virtualization = hasCpuFeature "vmx" || hasCpuFeature "svm";
  };
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
    services.upower.enable = lib.mkDefault detected.battery;
  };
}
