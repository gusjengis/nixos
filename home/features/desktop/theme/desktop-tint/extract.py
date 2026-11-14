#!/usr/bin/env python3
"""Record the native desktop-tint implementation and execute its mean-color oracle."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="macos")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    version = subprocess.check_output(["ssh", args.host, "sw_vers"], text=True)
    # Synthetic CGXWindow/Payload layout was checked against this build before
    # invoking the native function. Do not silently execute it on another ABI.
    if "26A434" not in version:
        raise SystemExit("Recheck the native Payload layout before using this oracle on a different OS build")
    oracle = Path(__file__).with_name("average-oracle.expr").read_text()
    commands = [
        'disassemble -n "CGXWindow::resolved_chameleon_color()"',
        'disassemble -n DesktopEffectsGetAverageColor',
        'disassemble -n "Payload::average_color(CGRect) const"',
        'disassemble -n "Payload::resize()"',
        'disassemble -n "CGXWindow::evaluate_tag_bit_change(WSWindowTagBitMask const&, WSWindowTagBitMask const&)"',
        'disassemble -n "desktop_window_effects_update(CGXWindow*, bool)"',
        'disassemble -n "CA::OGL::render_subclass(CA::OGL::Renderer&, CA::OGL::Layer const*)::visitor::visit_subclass(CA::Render::ChameleonLayer const*) const"',
        'disassemble -n "-[NSVisualEffectViewCoreUIImpl _makeSolariumUnderPageBackgroundLayer]"',
    ]
    script = '''
import json, lldb
target = lldb.debugger.GetSelectedTarget()
report = {"frameworks": {}, "disassembly": {}}
for name in ["AppKit", "CoreUI", "SkyLight", "QuartzCore"]:
    module = target.FindModule(lldb.SBFileSpec(name))
    report["frameworks"][name] = module.GetUUIDString()
for command in COMMANDS:
    result = lldb.SBCommandReturnObject()
    lldb.debugger.GetCommandInterpreter().HandleCommand(command, result)
    if not result.Succeeded():
        raise RuntimeError(result.GetError())
    report["disassembly"][command] = result.GetOutput()
symbols = target.FindSymbols("_ZNK7Payload13average_colorE6CGRect")
if symbols.GetSize() != 1:
    raise RuntimeError("Native average_color symbol is not unique")
address = symbols.GetContextAtIndex(0).GetSymbol().GetStartAddress().GetLoadAddress(target)
expression = ORACLE.replace("__AVERAGE_FUNCTION__", hex(address))
options = lldb.SBExpressionOptions()
options.SetLanguage(lldb.eLanguageTypeObjC_plus_plus)
value = target.EvaluateExpression(" ".join(expression.splitlines()), options)
if value.GetError().Fail():
    raise RuntimeError(str(value.GetError()))
report["oracle"] = json.loads(value.GetObjectDescription())
print("DESKTOP_TINT_JSON_BEGIN")
print(json.dumps(report))
print("DESKTOP_TINT_JSON_END")
'''.replace("COMMANDS", repr(commands)).replace("ORACLE", repr(oracle))
    command = ["xcrun", "lldb", "--batch", "-o", "process attach --name Finder",
        "-o", "expression -l objc++ -- @import AppKit; @import QuartzCore; @import ObjectiveC;",
        "-o", "script exec(" + repr(script) + ")", "-o", "process detach"]
    result = subprocess.run(["ssh", args.host, shlex.join(command)], text=True, capture_output=True, timeout=180)
    if result.returncode or "DESKTOP_TINT_JSON_BEGIN\n" not in result.stdout:
        raise SystemExit(result.stdout + result.stderr)
    text = result.stdout.split("DESKTOP_TINT_JSON_BEGIN\n", 1)[1].split("\nDESKTOP_TINT_JSON_END", 1)[0]
    report = json.loads(text)
    report["os"] = version
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Saved native code and {len(report['oracle'])} oracle cases to {args.output}")


if __name__ == "__main__":
    main()
