#!/usr/bin/env python3
"""Exercise shared tint in a private nested compositor (requires Pillow).

Usage: python test-shared-tint.py /nix/store/.../lib/libhyprglass.so
Requires Hyprland, hyprctl, quickshell and grim on PATH. Test processes terminate
on exit; the parent compositor's tint and plugin are never changed.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from PIL import Image, ImageChops, ImageStat

PRESETS = ["apple-control-center", "apple-notification", "apple-menu", "apple-dock",
           "apple-widgets", "apple-sidebar", "apple-toolbar", "apple-toolbar-inactive",
           "fitted-tooltip", "fixed-notification"]


def run(library):
    env = os.environ.copy()
    outer = env.copy()
    def parent(*args):
        return subprocess.check_output(["hyprctl", *args], env=outer, text=True)
    saved_monitors = json.loads(parent("monitors", "-j"))
    output_created = rule_created = False
    compositor = shell = app = None
    with tempfile.TemporaryDirectory(prefix="glass-tint-", dir="/tmp/opencode") as tmp:
        root = Path(tmp)
        (root / "hyprland.lua").write_text('''hl.monitor({output="", mode="1280x900", position="0x0", scale=1})
hl.config({misc={disable_hyprland_logo=true, disable_splash_rendering=true},animations={enabled=false}})
''')
        cells = []
        for i, preset in enumerate(PRESETS):
            x, y = 20 + i % 4 * 310, 20 + i // 4 * 300
            cells.append(f'''PanelWindow {{
                WlrLayershell.namespace: "tint-{i}"
                exclusionMode: ExclusionMode.Ignore
                anchors {{ top: true; left: true }}
                margins.left: {x}; margins.top: {y}
                implicitWidth: 280; implicitHeight: 260; color: "transparent"
            }}''')
        (root / "shell.qml").write_text('''import Quickshell
import Quickshell.Wayland
import QtQuick
ShellRoot {
    PanelWindow {
        WlrLayershell.layer: WlrLayer.Background
        exclusionMode: ExclusionMode.Ignore
        anchors {top:true; bottom:true; left:true; right:true}
        color: "#808080"
        Repeater {
            model: 40 * 29
            Rectangle {
                x: (index % 40) * 32; y: Math.floor(index / 40) * 32
                width: 32; height: 32
                color: (index % 40 + Math.floor(index / 40)) % 2 ? "#eeeeee" : "#222222"
            }
        }
    }
''' + "\n".join(cells) + "\n}\n")
        with (root / "compositor.log").open("w") as log:
            try:
                parent("output", "create", "headless", "TINTVERIFY")
                output_created = True
                parent("eval", 'hl.monitor({output="TINTVERIFY",mode="1280x900",position="10000x0",scale=1})')
                time.sleep(.5)
                monitor = next(m for m in json.loads(parent("monitors", "-j")) if m["name"] == "TINTVERIFY")
                workspace = monitor["activeWorkspace"]["name"]
                parent("eval", f'_G.glassTintTestRule=hl.window_rule({{name="glass-tint-test",match={{class="^Hyprland$"}},workspace="name:{workspace} silent",float=true,no_initial_focus=true}})')
                rule_created = True
                compositor = subprocess.Popen(["Hyprland", "-c", str(root / "hyprland.lua")], env=env, stdout=log, stderr=log)
                for _ in range(100):
                    instances = json.loads(subprocess.check_output(["hyprctl", "instances", "-j"], text=True))
                    instance = next((v for v in instances if v.get("pid") == compositor.pid), None)
                    if instance:
                        break
                    if compositor.poll() is not None:
                        raise RuntimeError(log.name + ": compositor exited")
                    time.sleep(.1)
                else:
                    raise RuntimeError("Nested compositor timed out")
                env.update(HYPRLAND_INSTANCE_SIGNATURE=instance["instance"], WAYLAND_DISPLAY=instance["wl_socket"], QT_QPA_PLATFORM="wayland")

                def ctl(*args):
                    return subprocess.check_output(["hyprctl", *args], env=env, text=True)

                time.sleep(.5)
                clients = json.loads(parent("clients", "-j"))
                client = next(c for c in clients if c["pid"] == compositor.pid)
                parent("eval", f'hl.dispatch(hl.dsp.window.move({{window="address:{client["address"]}",workspace="name:{workspace}",follow=false}}))')
                parent("eval", f'hl.dispatch(hl.dsp.window.float({{window="address:{client["address"]}",action="enable"}}))')
                parent("eval", f'hl.dispatch(hl.dsp.window.resize({{window="address:{client["address"]}",x=1280,y=900,relative=false}}))')
                time.sleep(.5)
                ctl("plugin", "load", str(Path(library).resolve()))
                names = ",".join(f"tint-{i}" for i in range(len(PRESETS)))
                ctl("eval", f'hl.plugin.hyprglass.config({{layers={{enabled=true,namespaces="{names}"}},mac={{tint=1}}}})')
                for i, preset in enumerate(PRESETS):
                    if preset == "fitted-tooltip":
                        material = 'mac_material={lut={.1294,.1578,.1849,.2105,.2347,.2576,.2790,.2990,.3176,.3348,.3507,.3651,.3781,.3897,.3999,.4087,.4144},chroma=1,blur={8.89,17.46,.85}}'
                    elif preset == "fixed-notification":
                        material = 'mac_apple="apple-notification",mac_tint=.375'
                    else:
                        material = f'mac_apple="{preset}"'
                    ctl("eval", f'hl.plugin.hyprglass.layer("tint-{i}",{{mac_inset=30,mac_radius=24,{material}}})')
                shell = subprocess.Popen(["quickshell", "-p", str(root / "shell.qml")], env=env, stdout=log, stderr=log)
                time.sleep(2)
                captures = {}
                for tint in (1, 0, .5, 1):
                    ctl("eval", f"hl.plugin.hyprglass.config({{mac={{tint={tint}}}}})")
                    time.sleep(.5)
                    path = root / f"tint-{tint}.png"
                    subprocess.run([os.environ.get("GRIM_BINARY", "grim"), str(path)], env=env, check=True, timeout=15)
                    image = Image.open(path).convert("RGB")
                    if tint == 1 and 1 in captures:
                        # Returning to full tint must undo clear/half entirely.
                        for i, preset in enumerate(PRESETS):
                            x, y = 20 + i % 4 * 310, 20 + i // 4 * 300
                            box = (x + 45, y + 45, x + 235, y + 215)
                            delta = ImageChops.difference(captures[1].crop(box), image.crop(box))
                            error = max(ImageStat.Stat(delta).mean)
                            print(preset, "full-tint restoration error:", error)
                            assert error < .1, (preset, "Full tint did not restore", error)
                    captures[tint] = image
                for i, preset in enumerate(PRESETS):
                    x, y = 20 + i % 4 * 310, 20 + i // 4 * 300
                    box = (x + 45, y + 45, x + 235, y + 215)
                    clear, half, full = [captures[t].crop(box) for t in (0, .5, 1)]
                    differences = [sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3 for a, b in ((clear, half), (half, full))]
                    print(preset, "clear→half / half→full mean pixel change:", differences)
                    if preset == "fixed-notification":
                        assert max(differences) == 0, (preset, "Per-layer override ignored", differences)
                    else:
                        assert min(differences) > .1, (preset, differences)
                status = json.loads(ctl("-j", "hyprglass", "status"))
                assert status["shaders"] == "ready", status
                errors = ctl("configerrors").strip()
                assert not errors or "no errors" in errors.lower(), errors
                print("PASS: eight Apple materials and fitted tooltip respond; per-layer override holds; full tint restores")
                if "--strata" in sys.argv:
                    shell.terminate()
                    shell.wait(timeout=10)
                    (root / "background.qml").write_text((root / "shell.qml").read_text().split(cells[0])[0] + "\n}\n")
                    shell = subprocess.Popen(["quickshell", "-p", str(root / "background.qml")], env=env, stdout=log, stderr=log)
                    config = root / "app-config"
                    (config / "strata").mkdir(parents=True)
                    (config / "strata/settings.toml").write_text('theme="finder-dark"\nrestore_tabs=false\nsidebar_expanded=true\n')
                    app_env = dict(env, XDG_CONFIG_HOME=str(config), XDG_STATE_HOME=str(root / "state"), XDG_CACHE_HOME=str(root / "cache"), GDK_BACKEND="wayland", GTK_A11Y="none")
                    app = subprocess.Popen(["strata", str(root)], env=app_env, stdout=log, stderr=log)
                    for _ in range(100):
                        client = next((c for c in json.loads(ctl("clients", "-j")) if c["pid"] == app.pid), None)
                        if client:
                            break
                        time.sleep(.1)
                    else:
                        raise RuntimeError("Strata did not map")
                    address = client["address"]
                    ctl("eval", f'hl.dispatch(hl.dsp.window.float({{window="address:{address}",action="enable"}}))')
                    ctl("eval", f'hl.dispatch(hl.dsp.window.resize({{window="address:{address}",x=1150,y=650,relative=false}}))')
                    ctl("eval", f'hl.dispatch(hl.dsp.window.move({{window="address:{address}",x=50,y=100,relative=false}}))')
                    time.sleep(2)
                    shots = []
                    for tint in (0, 1):
                        ctl("eval", f"hl.plugin.hyprglass.config({{mac={{tint={tint}}}}})")
                        time.sleep(.5)
                        path = root / f"strata-{tint}.png"
                        subprocess.run([os.environ.get("GRIM_BINARY", "grim"), str(path)], env=env, check=True, timeout=15)
                        shots.append(Image.open(path).convert("RGB"))
                    for name, box in (("window sidebar", (65, 350, 180, 600)), ("window toolbar", (350, 125, 900, 160))):
                        error = max(ImageStat.Stat(ImageChops.difference(shots[0].crop(box), shots[1].crop(box))).mean)
                        print(name, "clear→full mean pixel change:", error)
                        assert error > .1, (name, "Window item path ignores tint")
            except Exception:
                print((root / "compositor.log").read_text()[-12000:])
                raise
            finally:
                for process in (app, shell, compositor):
                    if process and process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                if rule_created:
                    parent("eval", 'if _G.glassTintTestRule then _G.glassTintTestRule:set_enabled(false);_G.glassTintTestRule=nil end')
                if output_created:
                    parent("output", "remove", "TINTVERIFY")
                for monitor in saved_monitors:
                    current = next((m for m in json.loads(parent("monitors", "-j")) if m["name"] == monitor["name"]), None)
                    if current and current["activeWorkspace"]["name"] != monitor["activeWorkspace"]["name"]:
                        parent("eval", f'hl.get_monitor("{monitor["name"]}"):set_workspace("name:{monitor["activeWorkspace"]["name"]}")')


if __name__ == "__main__":
    run(sys.argv[1])
