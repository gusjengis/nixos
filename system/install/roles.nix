# Presentation metadata for the installer's role list.
#
# The roles themselves are NOT listed here. They are discovered from the NixOS
# and Home Manager option trees by system/install/catalog.nix, so a module that
# gains or loses an `enable` option changes the installer with no edit to this
# file. What lives here is only the information the module system has no place
# to store: which category a role belongs under, what short flag name it gets,
# and a one-line summary written for a human choosing at install time.
#
# Everything here is checked against the discovered roles. An entry naming an
# option that no longer exists fails evaluation instead of being ignored, so a
# renamed module cannot leave stale metadata behind.
{
  # Categories are the installer's presets. In the TUI each one is a toggleable
  # header with its roles nested underneath; toggling the header sets every
  # role inside it, and the roles stay individually toggleable. On the command
  # line the same thing is `--group-<id>=true|false`, applied before individual
  # `--<role>=` flags so a single role can still dissent from its group.
  #
  # Order here is the order they appear on screen.
  categories = [
    {
      id = "core";
      label = "Core";
      description = "Fleet membership and the tools every machine is expected to have.";
    }
    {
      id = "desktop";
      label = "Desktop";
      description = "Hyprland and the graphical session. Leave off for a headless machine.";
    }
    {
      id = "development";
      label = "Development";
      description = "Editors, toolchains, language servers, and local virtual machines.";
    }
    {
      id = "gaming";
      label = "Gaming";
      description = "Steam and friends.";
    }
    {
      id = "printing";
      label = "3D printing";
      description = "Slicer and printer tooling.";
    }
    {
      id = "remote";
      label = "Remote access";
      description = "Reaching other machines and network shares from this one.";
    }
    {
      id = "services";
      label = "Hosted services";
      description = "Workloads this machine would serve to the rest of the fleet.";
    }
  ];

  # option path -> category id. An option with no entry lands in "other", which
  # the installer shows last; that is a nudge to categorise it here, not an
  # error, so adding a module never breaks an install.
  categoryOf = {
    "bedtimeLockout.enable" = "core";
    "dataDrive.client.enable" = "core";
    "git.enable" = "core";
    "grub.enable" = "core";
    "nvim.enable" = "core";
    "repo.networkmanager.enable" = "core";
    "tailscale.enable" = "core";
    "vial.enable" = "core";

    "desktopEnv.enable" = "desktop";
    "hyprland.enable" = "desktop";

    "dev.enable" = "development";
    "gameDev.enable" = "development";
    "virtual-machines.enable" = "development";

    "gaming.enable" = "gaming";

    "bambu.enable" = "printing";

    "officeNetworkDrives.enable" = "remote";
    "windowsVm.enable" = "remote";
    "windowsVm.og.enable" = "remote";

    "fleetMonitor.enable" = "services";
    "fleetMonitor.server.enable" = "services";
    "ollama.enable" = "services";
  };

  # Shorter command-line names. Without an entry a role's flag is its option
  # path lowercased with dots turned into dashes, which is unambiguous but ugly
  # for the nested ones.
  aliases = {
    "bedtimeLockout.enable" = "bedtime-lockout";
    "dataDrive.client.enable" = "data-drive";
    "desktopEnv.enable" = "desktop";
    "fleetMonitor.enable" = "fleet-monitor";
    "fleetMonitor.server.enable" = "fleet-monitor-server";
    "gameDev.enable" = "game-dev";
    "officeNetworkDrives.enable" = "office-drives";
    "repo.networkmanager.enable" = "networkmanager";
    "virtual-machines.enable" = "vms";
    "windowsVm.enable" = "windows-vm";
    "windowsVm.og.enable" = "windows-vm-og";
  };

  # `mkEnableOption` descriptions read as "Whether to enable enables git.",
  # which is fine in the manual and poor in a chooser. These replace them on
  # screen. Anything without an entry falls back to the module's own
  # description, so this is optional polish rather than required metadata.
  summaries = {
    "bambu.enable" = "Bambu Studio slicer, as a Flatpak.";
    "bedtimeLockout.enable" = "Scheduled lockout of input and the graphical session.";
    "dataDrive.client.enable" = "Mount the fleet's shared data drive at /data.";
    "dev.enable" = "Development tooling and the repositories that go with it.";
    "desktopEnv.enable" = "Desktop applications, fonts, and user-level graphical setup.";
    "fleetMonitor.enable" = "Report this machine's hardware and workloads to the fleet dashboard.";
    "fleetMonitor.server.enable" = "Host the fleet dashboard itself. One machine only.";
    "gameDev.enable" = "Game development toolchains.";
    "gaming.enable" = "Steam, Proton, and gaming peripherals.";
    "git.enable" = "System-wide Git configuration.";
    "grub.enable" = "GRUB as the bootloader, in EFI mode.";
    "hyprland.enable" = "The Hyprland compositor and its graphical session.";
    "nvim.enable" = "Neovim as the system editor.";
    "officeNetworkDrives.enable" =
      "Mount the office SMB shares. Needs credentials from the secrets repository.";
    "ollama.enable" = "Local model inference, reachable over the tailnet.";
    "repo.networkmanager.enable" = "NetworkManager with this fleet's shared defaults.";
    "tailscale.enable" =
      "Join the tailnet, and enable SSH. Effectively required for a headless machine.";
    "vial.enable" = "udev access for Vial keyboard configuration.";
    "virtual-machines.enable" = "libvirt and QEMU for running local virtual machines.";
    "windowsVm.enable" = "Launcher that opens a remote desktop into the Windows VM.";
    "windowsVm.og.enable" = "On-demand launcher for the older Windows VM.";
  };

  # Roles the committed Facter report decides. These are never presented as a
  # question and never written into a generated host file, because asking would
  # only create a way for the answer to outlive the hardware that justified it.
  #
  # Listed explicitly as well as detected, because detection alone is not
  # stable: an option's `files` records only the definitions that won, so a
  # machine that overrides one of these in its own host file stops looking
  # derived exactly when consistency matters most. Every name here is checked
  # against the discovered roles, so a rename fails evaluation.
  hardwareDerived = [
    "nvidia.enable" # graphics vendor, from the Facter report
    "laptop.enable" # SMBIOS chassis type, from the same report
  ];

  # Files whose definitions also mark a role as hardware-derived. This catches
  # a new option added to hardware policy before anyone remembers to list it
  # above, which is the common case on a machine being installed fresh.
  hardwarePolicyFiles = [
    "system/modules/hardware/facter-policy.nix"
    "home/policy/hardware.nix"
  ];
}
