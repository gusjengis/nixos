# The installer's role list, derived from the module systems themselves.
#
# The old install script discovered installable modules by running awk over
# `.nix` source text looking for `mkEnableOption`. That could not tell a real
# option from a commented-out one, could not see an option's effective default,
# and silently offered options that had been renamed away. This walks the
# evaluated option trees instead, so the list is the truth the build uses and
# cannot drift from it.
#
# Two filters do the important work:
#
#   * an option must be *declared inside this repository*, which removes the
#     roughly sixteen thousand upstream nixpkgs and Home Manager options;
#   * an option must not be declared under `system/hosts/` or `home/hosts/`,
#     which removes machine-specific modules. `immich.enable` belongs to alpha
#     and `hostShare.enable` belongs to pc, so neither is a question to ask
#     while installing some other machine.
#
# The reported value for each role is the *effective* value of that option for
# the host being catalogued, not the option's declared default. For a new
# machine that is what the shared modules default to. For a machine already on
# the roster it is that machine's current configuration, which is how
# reinstalling an existing host offers its existing choices back without any
# special case in the installer.
{
  lib,
  sourceRoot,
  roles,
}:
let
  prefix = toString sourceRoot + "/";

  # Option metadata records absolute store paths. Everything downstream wants
  # repository-relative paths, which are also stable across evaluations.
  relative = path: lib.removePrefix prefix (toString path);
  inRepo = path: lib.hasPrefix prefix (toString path);

  hostLocal =
    path:
    let
      rel = relative path;
    in
    lib.hasPrefix "system/hosts/" rel || lib.hasPrefix "home/hosts/" rel;

  # Walk an option tree collecting leaves. Deliberately does not descend into
  # option leaves: expanding submodule sub-options is what makes generating the
  # NixOS manual slow, and none of it is relevant here. Walking both trees this
  # way costs about two seconds.
  collect =
    path: attrs:
    lib.concatLists (
      lib.mapAttrsToList (
        name: value:
        let
          here = path ++ [ name ];
        in
        if lib.isOption value then
          [
            {
              path = here;
              option = value;
            }
          ]
        else if lib.isAttrs value && !(lib.hasPrefix "_" name) then
          collect here value
        else
          [ ]
      ) attrs
    );

  isRole =
    { path, option }:
    lib.last path == "enable"
    && (option.type.name or "") == "bool"
    && !(option.readOnly or false)
    && (option.visible or true) == true
    && option.declarations != [ ]
    && lib.all inRepo option.declarations
    && !(lib.any hostLocal option.declarations);

  # A role whose value is decided by a committed Facter report.
  #
  # `option.files` lists only the definitions that survived priority
  # resolution, so a host that sets one of these explicitly hides the policy
  # default that would otherwise identify it. The explicit list in roles.nix is
  # therefore what makes this answer the same for every host, and the file
  # check only adds options that policy has taken over but nobody has listed.
  isHardwareDerived =
    name: option:
    lib.elem name roles.hardwareDerived
    || lib.any (file: lib.elem (relative file) roles.hardwarePolicyFiles) (option.files or [ ]);

  defaultId =
    name: lib.toLower (builtins.replaceStrings [ "." ] [ "-" ] (lib.removeSuffix ".enable" name));

  mkRole =
    scope:
    { path, option }:
    let
      name = lib.concatStringsSep "." path;
    in
    {
      inherit name scope;
      id = roles.aliases.${name} or (defaultId name);
      value = option.value;
      derived = isHardwareDerived name option;
      category = roles.categoryOf.${name} or "other";
      summary = roles.summaries.${name} or (option.description or name);
      declaredIn = map relative option.declarations;
      definedIn = map relative (option.files or [ ]);
    };

  gather = scope: options: map (mkRole scope) (lib.filter isRole (collect [ ] options));
in
{
  # `nixosOptions` and `homeOptions` are the `options` attrsets of an evaluated
  # NixOS configuration and an evaluated Home Manager configuration for the
  # same host.
  forHost =
    {
      hostName,
      meta,
      nixosOptions,
      homeOptions,
    }:
    let
      discovered = gather "system" nixosOptions ++ gather "home" homeOptions;

      byName = lib.listToAttrs (map (role: lib.nameValuePair role.name role) discovered);
      names = lib.attrNames byName;

      ids = map (role: role.id) discovered;

      # Two roles sharing an identifier would mean one of them silently has no
      # command-line flag, so this has to be an error rather than a warning.
      duplicateIds = lib.unique (lib.filter (id: lib.count (other: other == id) ids > 1) ids);

      categoryIds = map (category: category.id) roles.categories;

      # Metadata that names an option which no longer exists is a bug, not a
      # harmless leftover: it means a module was renamed and the installer is
      # now describing something that is gone. Fail loudly at evaluation.
      stale = lib.subtractLists names (
        lib.attrNames roles.categoryOf
        ++ lib.attrNames roles.aliases
        ++ lib.attrNames roles.summaries
        ++ roles.hardwareDerived
      );

      badCategories = lib.filter (name: !(lib.elem roles.categoryOf.${name} categoryIds)) (
        lib.attrNames roles.categoryOf
      );

      errors =
        lib.optional (
          stale != [ ]
        ) "system/install/roles.nix describes options that do not exist: ${lib.concatStringsSep ", " stale}"
        ++ lib.optional (
          duplicateIds != [ ]
        ) "role identifiers collide: ${lib.concatStringsSep ", " (lib.unique duplicateIds)}"
        ++ lib.optional (
          badCategories != [ ]
        ) "roles assigned to unknown categories: ${lib.concatStringsSep ", " badCategories}";

      # Roles the installer asks about, sorted for a stable screen order.
      selectable = lib.sort (a: b: a.id < b.id) (lib.filter (role: !role.derived) discovered);
      derived = lib.sort (a: b: a.id < b.id) (lib.filter (role: role.derived) discovered);

      usedCategories = lib.unique (map (role: role.category) selectable);
    in
    if errors != [ ] then
      throw ("installer role catalog is inconsistent:\n  - " + lib.concatStringsSep "\n  - " errors)
    else
      {
        host = hostName;
        system = meta.system;
        description = meta.description or "";
        roles = selectable;
        derivedRoles = derived;
        categories =
          lib.filter (category: lib.elem category.id usedCategories) roles.categories
          ++ lib.optional (lib.elem "other" usedCategories) {
            id = "other";
            label = "Other";
            description = "Roles with no category assigned in system/install/roles.nix.";
          };
      };
}
