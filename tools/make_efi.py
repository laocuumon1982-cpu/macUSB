#!/usr/bin/env python3
"""
Build the minimal OpenCore EFI folder that macUSB Win copies onto a Recovery USB.

The EFI is only a boot loader for *real* Intel Macs: it loads Apple's signed
recovery image (com.apple.recovery.boot/BaseSystem.dmg + .chunklist) from the
FAT32 USB stick. It adds no kexts, no ACPI, no SMBIOS spoofing and never writes
NVRAM, so it does not change anything on the Mac.

Usage: make_efi.py <extracted OpenCore-x.y.z-RELEASE dir> <output dir>
"""
import plistlib
import shutil
import sys
from pathlib import Path


def build_config(sample: dict) -> dict:
    cfg = {k: v for k, v in sample.items() if not k.startswith("#")}

    # Nothing to inject on a genuine Mac.
    cfg["ACPI"]["Add"] = []
    cfg["ACPI"]["Delete"] = []
    cfg["ACPI"]["Patch"] = []
    cfg["Booter"]["MmioWhitelist"] = []
    cfg["Booter"]["Patch"] = []
    cfg["DeviceProperties"]["Add"] = {}
    cfg["DeviceProperties"]["Delete"] = {}
    for key in ("Add", "Block", "Force", "Patch"):
        cfg["Kernel"][key] = []

    # Genuine Apple firmware needs no memory-map workarounds.
    bq = cfg["Booter"]["Quirks"]
    for key, value in list(bq.items()):
        if isinstance(value, bool):
            bq[key] = False
    bq["AvoidRuntimeDefrag"] = True
    bq["FixupAppleEfiImages"] = True

    kq = cfg["Kernel"]["Quirks"]
    for key, value in list(kq.items()):
        if isinstance(value, bool):
            kq[key] = False

    misc = cfg["Misc"]
    misc["Entries"] = []
    misc["Tools"] = []
    misc["Boot"].update({
        "HideAuxiliary": False,   # recovery images are "auxiliary" entries
        "PickerMode": "Builtin",
        "PollAppleHotKeys": True,
        "ShowPicker": True,
        "Timeout": 0,
    })
    misc["Security"].update({
        "AllowSetDefault": True,
        "DmgLoading": "Signed",    # only Apple-signed images with a chunklist
        "ScanPolicy": 0,
        "SecureBootModel": "Disabled",
        "Vault": "Optional",
    })

    # Never touch the Mac's NVRAM or SMBIOS.
    cfg["NVRAM"]["Add"] = {}
    cfg["NVRAM"]["Delete"] = {}
    cfg["NVRAM"]["WriteFlash"] = False
    pi = cfg["PlatformInfo"]
    pi["UpdateDataHub"] = False
    pi["UpdateNVRAM"] = False
    pi["UpdateSMBIOS"] = False

    uefi = cfg["UEFI"]
    uefi["APFS"]["MinDate"] = -1
    uefi["APFS"]["MinVersion"] = -1
    uefi["ReservedMemory"] = []
    template = dict(uefi["Drivers"][0])
    template.update({
        "Arguments": "",
        "Comment": "OpenRuntime",
        "Enabled": True,
        "LoadEarly": False,
        "Path": "OpenRuntime.efi",
    })
    uefi["Drivers"] = [template]
    return cfg


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    oc = Path(sys.argv[1])
    out = Path(sys.argv[2])
    if out.exists():
        shutil.rmtree(out)
    boot = out / "EFI" / "BOOT"
    ocdir = out / "EFI" / "OC"
    for d in (boot, ocdir / "Drivers", ocdir / "ACPI", ocdir / "Kexts",
              ocdir / "Tools", ocdir / "Resources"):
        d.mkdir(parents=True, exist_ok=True)

    shutil.copy2(oc / "X64/EFI/BOOT/BOOTx64.efi", boot / "BOOTx64.efi")
    shutil.copy2(oc / "X64/EFI/OC/OpenCore.efi", ocdir / "OpenCore.efi")
    shutil.copy2(oc / "X64/EFI/OC/Drivers/OpenRuntime.efi", ocdir / "Drivers" / "OpenRuntime.efi")

    with open(oc / "Docs/Sample.plist", "rb") as fh:
        sample = plistlib.load(fh)
    with open(ocdir / "config.plist", "wb") as fh:
        plistlib.dump(build_config(sample), fh)

    lic = oc / "LICENSE.txt"
    (out / "EFI" / "OpenCore-LICENSE.txt").write_text(
        lic.read_text() if lic.exists() else
        "OpenCore (c) Acidanthera, BSD-3-Clause. https://github.com/acidanthera/OpenCorePkg\n"
    )
    print(f"EFI written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
