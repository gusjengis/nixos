"""Reading the machine the installer is standing on.

Two things get probed: the block devices, so a disk can be chosen and
described accurately before it is destroyed, and the hardware, so the
configuration this machine ends up with is derived from what is actually
present rather than from answers someone typed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .model import Disk
from .proc import Reporter, run

# Whole disks only. Partitions, loop devices, ROM devices, and the ISO's own
# squashfs are never installation targets, and offering them is how someone
# ends up installing onto the medium they booted from.
_DISK_TYPES = {"disk"}


def list_disks(*, reporter: Reporter, include_removable: bool = False) -> list[Disk]:
    """Every whole disk on the machine, largest first."""

    completed = run(
        [
            "lsblk",
            "--json",
            "--bytes",
            "--output",
            "NAME,PATH,SIZE,TYPE,MODEL,TRAN,RM,MOUNTPOINT,MOUNTPOINTS",
        ],
        reporter=reporter,
    )
    payload = json.loads(completed.stdout or "{}")

    disks: list[Disk] = []
    for node in payload.get("blockdevices", []):
        if node.get("type") not in _DISK_TYPES:
            continue

        removable = bool(node.get("rm"))
        if removable and not include_removable:
            continue

        children = node.get("children") or []
        partitions = []
        mounted = _is_mounted(node)
        for child in children:
            mounted = mounted or _is_mounted(child)
            size = child.get("size")
            described = child.get("path") or child.get("name") or "?"
            if isinstance(size, int):
                described = f"{described} ({_human(size)})"
            partitions.append(described)

        disks.append(
            Disk(
                path=str(node.get("path") or f"/dev/{node.get('name')}"),
                size_bytes=int(node.get("size") or 0),
                model=str(node.get("model") or "").strip(),
                transport=str(node.get("tran") or "").strip(),
                removable=removable,
                partitions=tuple(partitions),
                mounted=mounted,
            )
        )

    disks.sort(key=lambda disk: disk.size_bytes, reverse=True)
    return disks


def _is_mounted(node: dict[str, object]) -> bool:
    if node.get("mountpoint"):
        return True
    points = node.get("mountpoints") or []
    return any(point for point in points if point)  # type: ignore[union-attr]


def _human(size: int) -> str:
    value = float(size)
    for unit in ("B", "K", "M", "G", "T"):
        if value < 1024 or unit == "T":
            return f"{value:.0f}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}T"


def synthetic_report(system: str) -> dict[str, object]:
    """A report describing no hardware at all.

    Used only when the installer is answering a question rather than
    installing: listing modules needs a host that evaluates, and evaluating a
    host needs a report, but probing real hardware needs root. Every
    hardware-derived value comes out false, which is correct for "nothing was
    detected" and is never written to a disk.
    """

    return {"version": 1, "system": system, "hardware": {}, "smbios": {}}


def probe_existing(path: Path) -> dict[str, object]:
    """Reuse a report from an earlier run.

    Only used by --dry-run, so that rehearsing an installation does not need
    root to re-probe hardware that has not changed.
    """

    return json.loads(path.read_text())


def probe_hardware(destination: Path, *, reporter: Reporter) -> dict[str, object]:
    """Write a Facter report for this machine and return it.

    This is the same probe `refresh-hardware` runs on an installed machine, and
    it produces the file the host's configuration reads from then on. Running
    it here rather than asking questions about hardware is the reason the
    installer has no graphics, CPU, or firmware questions.
    """

    reporter.step("Probing hardware with nixos-facter")

    destination.parent.mkdir(parents=True, exist_ok=True)

    # nixos-facter refuses to overwrite a file it did not create, so it must
    # not be pre-created. Remove any leftover from an earlier attempt.
    if destination.exists():
        destination.unlink()

    run(
        ["nixos-facter", "-o", str(destination)],
        reporter=reporter,
        stream=True,
    )
    os.chmod(destination, 0o644)

    report: dict[str, object] = json.loads(destination.read_text())
    _describe(report, reporter=reporter)
    return report


# SMBIOS 3.7.0 table 17. Kept in step with system/install/lib/facter.nix, which
# is the definition the configuration itself uses.
PORTABLE_CHASSIS_TYPES = frozenset({8, 9, 10, 11, 14, 30, 31, 32})


def is_portable(report: dict[str, object]) -> bool:
    """Whether this machine is a laptop.

    `hardware.system.form_factor` reports "laptop" for every machine in this
    fleet, desktops included, so it cannot be used. The SMBIOS chassis type
    can.
    """

    smbios = report.get("smbios") or {}
    chassis = smbios.get("chassis") or []  # type: ignore[union-attr]
    for entry in chassis:
        chassis_type = (entry or {}).get("chassis_type") or {}
        if chassis_type.get("value") in PORTABLE_CHASSIS_TYPES:
            return True
    return False


def _describe(report: dict[str, object], *, reporter: Reporter) -> None:
    hardware = report.get("hardware") or {}
    cards = hardware.get("graphics_card") or []  # type: ignore[union-attr]
    cpus = hardware.get("cpu") or []  # type: ignore[union-attr]

    if cpus:
        model = (cpus[0] or {}).get("model_name") or (cpus[0] or {}).get("vendor_name")
        if model:
            reporter.info(f"CPU: {model}")
    for card in cards:
        vendor = ((card or {}).get("vendor") or {}).get("name") or ""
        device = ((card or {}).get("device") or {}).get("name") or ""
        if vendor or device:
            reporter.info(f"Graphics: {vendor} {device}".strip())

    reporter.info(f"Chassis: {'portable' if is_portable(report) else 'not portable'}")
