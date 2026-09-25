# The installer, with every program it shells out to pinned.
#
# The old install script was curl-piped into bash and hoped the tools it needed
# were present. This one is a wrapper with an exact PATH, so it behaves the
# same on a stock ISO as it does on a machine that already has half of these
# installed, and a missing dependency is a build failure rather than a failure
# partway through an installation.
{
  lib,
  python3Packages,
  makeWrapper,
  # Partitioning and installation.
  disko,
  nixos-install-tools,
  nixos-facter,
  # Probing, and the small tools the steps use.
  util-linux,
  coreutils,
  git,
  openssh,
  nix,
  shadow,
  systemd,
  repoUrl ? "https://github.com/gusjengis/nixos.git",
}:

let
  runtimeInputs = [
    disko
    nixos-install-tools
    nixos-facter
    util-linux # lsblk, findmnt, runuser
    coreutils
    git
    openssh
    nix
    shadow # chpasswd, used inside nixos-enter
    systemd # systemctl reboot, once the machine is actually installed
  ];
in
python3Packages.buildPythonApplication {
  pname = "nixos-config-install";
  version = "1.0.0";
  pyproject = true;

  src = ./installer;

  build-system = [ python3Packages.setuptools ];

  dependencies = [ python3Packages.textual ];

  nativeBuildInputs = [ makeWrapper ];

  # The decision logic and the interface are unit-tested, and the tests run as
  # part of building the installer. A `nix run .#install` that reaches the
  # point of asking a question has already had them pass.
  nativeCheckInputs = [
    python3Packages.pytestCheckHook
  ];

  pytestFlags = [ "tests" ];

  postFixup = ''
    wrapProgram $out/bin/nixos-config-install \
      --prefix PATH : ${lib.makeBinPath runtimeInputs} \
      --set-default NIXOS_INSTALL_REPO ${lib.escapeShellArg repoUrl}
  '';

  meta = {
    description = "Installer for this NixOS configuration";
    mainProgram = "nixos-config-install";
    platforms = lib.platforms.linux;
  };
}
