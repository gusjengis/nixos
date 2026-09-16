# Machine roster.
#
# Every machine this configuration is deployed to is listed here, and every
# machine builds `homeConfigurations.<name>`. Nothing about a machine lives in
# an untracked file any more.
#
# `machineId` is the contents of /etc/machine-id. It is unique per install,
# readable offline, needs no daemon, and exists before networking, which makes
# it the only identifier all of these machines actually disagree on: every one
# of them reports the hostname `nixos`, and Tailscale's local `HostName` is
# `nixos` too, since the distinct tailnet name is control-plane state rather
# than anything the machine knows about itself.
#
# `rehome` maps /etc/machine-id back to a name here. A reinstall regenerates
# the id, so after one, run `rehome <name>` explicitly and update the value
# below.
{
  pc = {
    system = "x86_64-linux";
    machineId = "10f140e2392c421688f344d480811453";
    description = "Main desktop. Gaming, game development, 3D printing, Windows VM host.";
  };

  alpha = {
    system = "x86_64-linux";
    machineId = "e2f2e88b69d940289236f4f94cd5ca0e";
    description = "Headless desktop server.";
  };

  omega = {
    system = "x86_64-linux";
    machineId = "fb413463bebc495a99fbc054919df029";
    description = "Headless desktop server.";
  };

  legion = {
    system = "x86_64-linux";
    machineId = "48ba9a9b1d98407d9f5acaf278031404";
    description = "Laptop with the full desktop.";
  };

  mac = {
    system = "aarch64-linux";
    machineId = "7d57a3a0f7874971985e76c02c53f04c";
    description = "Apple Silicon laptop running Asahi, with the full desktop.";
  };

  t480s = {
    system = "x86_64-linux";
    machineId = "87a658853ef94b7fa356ad0a4e4b8314";
    description = "ThinkPad T480s with the full desktop.";
  };

  t470 = {
    system = "x86_64-linux";
    machineId = "a7a69f62a9af4589ad7115acf38e7c6f";
    description = "ThinkPad T470, headless.";
  };

  zombie = {
    system = "x86_64-linux";
    machineId = "6def610e410e44d480b8234c7cd5b671";
    description = "Headless laptop.";
  };
}
