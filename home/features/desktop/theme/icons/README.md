# Repository-owned icon themes

`MacOS-Native/` is the writable icon pack installed by Home Manager with an
out-of-store directory symlink. Native artwork, Linux aliases, and generated app
icons all live here. Generated additions update this repository directly.

Original native inputs live beside this directory in `../icon-source/`.

The pack also retains original generated-app artwork in `MacOS-Native/app-sources/`.
Installed application paths in `generated-apps.json` are provenance/watch hints;
the installed pixels and captured artwork are repository files. Icons remain in
the library when an application is absent on another machine.

`icon-theme.cache` is derived and ignored by Git. Home Manager activation and the
watcher rebuild it. Raw native assets use relative links to `../icon-source/`
instead of duplicating their PNG contents.
