"""
macUSB Win - core logic (no GUI).

* Intel Macs: download Apple's signed macOS Recovery image from
  osrecovery.apple.com, verify it against Apple's signed chunklist, and write a
  FAT32 USB stick that a real Intel Mac boots through a minimal OpenCore EFI.
  Recovery protocol and chunklist verification follow OpenCorePkg's
  macrecovery.py (Copyright (c) 2019, vit9696, BSD-3-Clause).
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import string
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

APP_NAME = "macUSB Win"
APP_VERSION = "1.0.0"
USER_AGENT_RECOVERY = "InternetRecovery/1.0"
USB_LABEL = "MACRECOVERY"

Progress = Callable[[int, int, str], None]   # done, total, text
Log = Callable[[str], None]


class Cancelled(Exception):
    pass


def _noop_progress(done: int, total: int, text: str) -> None:
    pass


def _noop_log(text: str) -> None:
    pass


def resource_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base)
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    d = Path(root) / "macUSBWin"
    d.mkdir(parents=True, exist_ok=True)
    return d


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# --------------------------------------------------------------------------
# Intel: Apple Internet Recovery
# --------------------------------------------------------------------------

MLB_ZERO = "00000000000000000"


@dataclass(frozen=True)
class RecoveryTarget:
    name: str
    board_id: str
    mlb: str = MLB_ZERO
    os_type: str = "default"
    note: str = ""


# Board-id / MLB pairs documented in OpenCorePkg Utilities/macrecovery/recovery_urls.txt
RECOVERY_TARGETS: list[RecoveryTarget] = [
    RecoveryTarget("macOS Tahoe 26 (bản cuối cho Mac Intel)", "Mac-CFF7D910A743CAAF", os_type="latest",
                   note="Mac Intel 2019-2020: MacBook Pro 16\" 2019, MacBook Pro 13\" 2020 (4 cổng), iMac 2020, Mac Pro 2019."),
    RecoveryTarget("macOS Sequoia 15", "Mac-7BA5B2D9E42DDD94",
                   note="Mac Intel từ 2018 (MacBook Air 2020, MacBook Pro 2018+, iMac 2019+, Mac mini 2018, iMac Pro)."),
    RecoveryTarget("macOS Sonoma 14", "Mac-827FAC58A8FDFA22",
                   note="Mac Intel từ 2018 (MacBook Pro 2018+, MacBook Air 2018+, iMac 2019+, Mac mini 2018)."),
    RecoveryTarget("macOS Ventura 13", "Mac-B4831CEBD52A0C4C",
                   note="Mac Intel từ 2017 (MacBook Pro 2017+, MacBook Air 2018+, iMac 2017+, Mac mini 2018)."),
    RecoveryTarget("macOS Monterey 12", "Mac-E43C1C25D4880AD6",
                   note="MacBook Pro đầu 2015+, MacBook Air đầu 2015+, iMac cuối 2015+, Mac mini 2014+."),
    RecoveryTarget("macOS Big Sur 11", "Mac-2BD1B31983FE1663",
                   note="MacBook Pro cuối 2013+, MacBook Air 2013+, iMac giữa 2014+, Mac mini 2014+."),
    RecoveryTarget("macOS Catalina 10.15", "Mac-00BE6ED71E35EB86",
                   note="MacBook Pro giữa 2012+, MacBook Air giữa 2012+, iMac cuối 2012+, Mac mini cuối 2012+."),
    RecoveryTarget("macOS Mojave 10.14", "Mac-7BA5B2DFE22DDD8C", "00000000000KXPG00",
                   note="Mac giữa 2012+ (Mac Pro 2010-2012 cần card đồ hoạ Metal)."),
    RecoveryTarget("macOS High Sierra 10.13", "Mac-7BA5B2D9E42DDD94", "00000000000J80300",
                   note="MacBook Pro 2010+, MacBook Air 2010+, iMac cuối 2009+, Mac mini 2010+."),
    RecoveryTarget("macOS Sierra 10.12", "Mac-77F17D7DA9285301", "00000000000J0DX00"),
    RecoveryTarget("OS X El Capitan 10.11", "Mac-FFE5EF870D7BA81A", "00000000000GQRX00"),
    RecoveryTarget("OS X Yosemite 10.10", "Mac-E43C1C25D4880AD6", "00000000000GDVW00"),
    RecoveryTarget("OS X Mavericks 10.9", "Mac-F60DEB81FF30ACF6", "00000000000FNN100"),
    RecoveryTarget("OS X Mountain Lion 10.8", "Mac-7DF2A3B5E5D671ED", "00000000000F65100"),
    RecoveryTarget("Mac OS X Lion 10.7", "Mac-2E6FAB96566FE58C", "00000000000F25Y00"),
]

TYPE_SID, TYPE_K, TYPE_FG = 16, 64, 64
INFO_PRODUCT, INFO_IMAGE_LINK, INFO_IMAGE_SESS = "AP", "AU", "AT"
INFO_SIGN_LINK, INFO_SIGN_SESS = "CU", "CT"
INFO_REQUIRED = ["AP", "AU", "AH", "AT", "CU", "CH", "CT"]


def _gen_id(n: int) -> str:
    return "".join(random.choices(string.hexdigits[:16].upper(), k=n))


def _open(req: urllib.request.Request, timeout: float = 60):
    return urllib.request.urlopen(req, timeout=timeout)


def recovery_session() -> str:
    req = urllib.request.Request("http://osrecovery.apple.com/", headers={
        "Host": "osrecovery.apple.com", "Connection": "close", "User-Agent": USER_AGENT_RECOVERY})
    with _open(req, 30) as resp:
        for key, value in resp.headers.items():
            if key.lower() == "set-cookie":
                for cookie in value.split("; "):
                    if cookie.startswith("session="):
                        return cookie
    raise RuntimeError("Máy chủ Apple không trả về phiên làm việc (session).")


def recovery_info(target: RecoveryTarget, session: Optional[str] = None) -> dict:
    session = session or recovery_session()
    post = {"cid": _gen_id(TYPE_SID), "sn": target.mlb, "bid": target.board_id,
            "k": _gen_id(TYPE_K), "fg": _gen_id(TYPE_FG), "os": target.os_type}
    data = "\n".join(f"{k}={v}" for k, v in post.items()).encode()
    req = urllib.request.Request(
        "http://osrecovery.apple.com/InstallationPayload/RecoveryImage", data=data, headers={
            "Host": "osrecovery.apple.com", "Connection": "close", "User-Agent": USER_AGENT_RECOVERY,
            "Cookie": session, "Content-Type": "text/plain"})
    with _open(req, 30) as resp:
        text = resp.read().decode("utf-8", "replace")
    info = {}
    for line in text.split("\n"):
        if ": " in line:
            k, v = line.split(": ", 1)
            info[k.strip()] = v.strip()
    missing = [k for k in INFO_REQUIRED if k not in info]
    if missing:
        raise RuntimeError(f"Phản hồi của Apple thiếu trường {missing}. Board-id có thể không hợp lệ.")
    return info


def _download(url: str, dest: Path, headers: dict, progress: Progress, cancel: threading.Event,
              label: str, resume: bool = False, expected_size: int = 0) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    start = part.stat().st_size if (resume and part.exists()) else 0
    hdrs = dict(headers)
    if start:
        hdrs["Range"] = f"bytes={start}-"
    req = urllib.request.Request(url, headers=hdrs)
    with _open(req, 60) as resp:
        status = getattr(resp, "status", 200)
        if start and status != 206:
            start = 0
        length = int(resp.headers.get("Content-Length") or 0)
        total = (start + length) if length else expected_size
        mode = "ab" if start else "wb"
        done = start
        t0, d0 = time.time(), done
        with open(part, mode) as fh:
            while True:
                if cancel.is_set():
                    raise Cancelled()
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                dt = time.time() - t0
                speed = (done - d0) / dt if dt > 0.5 else 0
                text = f"{label}: {human_size(done)}" + (f" / {human_size(total)}" if total else "")
                if speed:
                    text += f" — {human_size(speed)}/s"
                progress(done, total, text)
    if total and done != total:
        raise RuntimeError(f"Tải chưa đủ dữ liệu ({done} / {total} byte). Hãy thử lại.")
    os.replace(part, dest)
    return dest


# Apple chunklist verification (from macrecovery.py, BSD-3-Clause, vit9696)
_APPLE_EFI_ROM_PUBKEY_1 = int(
    "C3E748CAD9CD384329E10E25A91E43E1A762FF529ADE578C935BDDF9B13F2179D4855E6FC89E9E29CA12517D17DFA1EDCE"
    "0BEBF0EA7B461FFE61D94E2BDF72C196F89ACD3536B644064014DAE25A15DB6BB0852ECBD120916318D1CCDEA3C84C92ED"
    "743FC176D0BACA920D3FCF3158AFF731F88CE0623182A8ED67E650515F75745909F07D415F55FC15A35654D118C55A462D"
    "37A3ACDA08612F3F3F6571761EFCCBCC299AEE99B3A4FD6212CCFFF5EF37A2C334E871191F7E1C31960E010A54E86FA3F6"
    "2E6D6905E1CD57732410A3EB0C6B4DEFDABE9F59BF1618758C751CD56CEF851D1C0EAA1C558E37AC108DA9089863D20E2E"
    "7E4BF475EC66FE6B3EFDCF", 16)
_CNK_HEADER = struct.Struct("<4sIBBBxQQQ")
_CNK_CHUNK = struct.Struct("<I32s")


def read_chunklist(path: Path) -> list[tuple[int, bytes]]:
    chunks = []
    with open(path, "rb") as f:
        ctx = hashlib.sha256()
        data = f.read(_CNK_HEADER.size)
        ctx.update(data)
        magic, hsize, fver, cmethod, smethod, count, coff, soff = _CNK_HEADER.unpack(data)
        if not (magic == b"CNKL" and hsize == 0x24 and fver == 1 and cmethod == 1 and count > 0
                and coff == 0x24 and soff == coff + _CNK_CHUNK.size * count):
            raise RuntimeError("Chunklist không hợp lệ.")
        for _ in range(count):
            data = f.read(_CNK_CHUNK.size)
            ctx.update(data)
            chunks.append(_CNK_CHUNK.unpack(data))
        digest = ctx.digest()
        if smethod == 1:
            sig = int.from_bytes(f.read(256), "little")
            plain = int(f'0x1{"f" * 404}003031300d060960864801650304020105000420{"0" * 64}', 16) | int.from_bytes(digest, "big")
            if pow(sig, 0x10001, _APPLE_EFI_ROM_PUBKEY_1) != plain:
                raise RuntimeError("Chữ ký Apple của chunklist không đúng.")
        else:
            raise RuntimeError("Chunklist không có chữ ký số của Apple.")
        if f.read(1) != b"":
            raise RuntimeError("Chunklist có dữ liệu thừa.")
    return chunks


def verify_image(dmg: Path, chunklist: Path, progress: Progress = _noop_progress,
                 cancel: Optional[threading.Event] = None, label: str = "Kiểm tra") -> None:
    chunks = read_chunklist(chunklist)
    total = sum(c[0] for c in chunks)
    done = 0
    with open(dmg, "rb") as f:
        for i, (size, sha) in enumerate(chunks, 1):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            data = f.read(size)
            if len(data) != size or hashlib.sha256(data).digest() != sha:
                raise RuntimeError(f"Ảnh recovery bị lỗi ở khối {i}. Hãy xoá bộ nhớ đệm và tải lại.")
            done += size
            progress(done, total, f"{label}: {done * 100 // total}%")
        if f.read(1) != b"":
            raise RuntimeError("Ảnh recovery lớn hơn chunklist.")


def download_recovery(target: RecoveryTarget, progress: Progress = _noop_progress,
                      log: Log = _noop_log, cancel: Optional[threading.Event] = None) -> tuple[Path, Path, str]:
    """Returns (dmg_path, chunklist_path, product_id). Uses a verified cache."""
    cancel = cancel or threading.Event()
    log(f"Kết nối máy chủ Apple cho {target.name} (board {target.board_id}, os={target.os_type})…")
    info = recovery_info(target)
    product = info[INFO_PRODUCT]
    folder = data_dir() / "recovery" / product
    dmg_name = os.path.basename(urlparse(info[INFO_IMAGE_LINK]).path) or "BaseSystem.dmg"
    cnk_name = os.path.basename(urlparse(info[INFO_SIGN_LINK]).path) or "BaseSystem.chunklist"
    dmg, cnk = folder / dmg_name, folder / cnk_name
    log(f"Apple trả về gói {product}: {dmg_name}")

    if dmg.exists() and cnk.exists():
        try:
            log("Đã có bản tải trước đó, đang kiểm tra lại…")
            verify_image(dmg, cnk, progress, cancel, "Kiểm tra bản đã tải")
            log("Bản đã tải còn nguyên vẹn, dùng lại.")
            return dmg, cnk, product
        except Cancelled:
            raise
        except Exception as e:
            log(f"Bản cũ hỏng ({e}), tải lại.")

    def headers(url: str, token: str) -> dict:
        return {"Host": urlparse(url).hostname, "Connection": "close",
                "User-Agent": USER_AGENT_RECOVERY, "Cookie": f"AssetToken={token}"}

    _download(info[INFO_SIGN_LINK], cnk, headers(info[INFO_SIGN_LINK], info[INFO_SIGN_SESS]),
              progress, cancel, "Tải chunklist")
    read_chunklist(cnk)  # signature check before the big download
    log("Chunklist có chữ ký hợp lệ của Apple.")
    _download(info[INFO_IMAGE_LINK], dmg, headers(info[INFO_IMAGE_LINK], info[INFO_IMAGE_SESS]),
              progress, cancel, f"Tải {dmg_name}")
    log("Đang kiểm tra toàn vẹn ảnh recovery…")
    verify_image(dmg, cnk, progress, cancel, "Kiểm tra")
    log("Ảnh recovery khớp chunklist của Apple.")
    return dmg, cnk, product


# --------------------------------------------------------------------------
# Windows disks
# --------------------------------------------------------------------------

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


@dataclass
class Disk:
    number: int
    name: str
    size: int
    bus: str
    is_system: bool

    def label(self) -> str:
        return f"Ổ {self.number}: {self.name} — {human_size(self.size)} ({self.bus})"


def _run(cmd: list[str], timeout: int = 300, input_text: Optional[str] = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=input_text,
                          creationflags=CREATE_NO_WINDOW, encoding="utf-8", errors="replace")


def list_disks(include_non_usb: bool = False) -> list[Disk]:
    if os.name != "nt":
        return []
    ps = ("Get-Disk | Select-Object Number,FriendlyName,Size,BusType,IsBoot,IsSystem "
          "| ConvertTo-Json -Compress")
    r = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], 60)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError("Không đọc được danh sách ổ đĩa: " + (r.stderr or r.stdout).strip())
    raw = json.loads(r.stdout)
    if isinstance(raw, dict):
        raw = [raw]
    disks = []
    for d in raw:
        bus = str(d.get("BusType"))
        bus_name = {"7": "USB", "12": "SD", "USB": "USB", "SD": "SD", "15": "File Backed Virtual",
                    "File Backed Virtual": "File Backed Virtual"}.get(bus, bus)
        disk = Disk(int(d["Number"]), str(d.get("FriendlyName") or "?").strip(), int(d.get("Size") or 0),
                    bus_name, bool(d.get("IsBoot")) or bool(d.get("IsSystem")))
        if disk.is_system:
            continue
        if include_non_usb or bus_name in ("USB", "SD"):
            disks.append(disk)
    return sorted(disks, key=lambda x: x.number)


def _free_letter() -> str:
    for letter in "ZYXWVUTSRQPONMLKJIHGFE":
        if not os.path.exists(f"{letter}:\\"):
            return letter
    raise RuntimeError("Không còn ký tự ổ đĩa trống.")


def diskpart_script(disk: Disk, letter: str) -> str:
    size_mb = disk.size // (1024 * 1024)
    lines = [f"select disk {disk.number}", "attributes disk clear readonly noerr", "online disk noerr",
             "clean", "convert mbr"]
    # diskpart only formats FAT32 up to 32 GB; recovery needs < 2 GB.
    lines.append("create partition primary" + (" size=16384" if size_mb > 32000 else ""))
    lines += [f"format fs=fat32 quick label={USB_LABEL}", "active", f"assign letter={letter}", "exit"]
    return "\n".join(lines) + "\n"


def format_usb(disk: Disk, log: Log = _noop_log, allow_non_usb: bool = False) -> str:
    """Erase the disk and create one FAT32 partition. Returns the drive root like 'Z:\\'."""
    current = {d.number: d for d in list_disks(include_non_usb=allow_non_usb)}
    if disk.number not in current:
        raise RuntimeError("Ổ USB đã thay đổi hoặc không còn cắm. Hãy bấm Làm mới.")
    if current[disk.number].size != disk.size:
        raise RuntimeError("Dung lượng ổ USB không khớp với ổ đã chọn. Hãy bấm Làm mới.")
    if disk.size < 2 * 1024 ** 3:
        raise RuntimeError("USB cần tối thiểu 2 GB (nên dùng 8 GB trở lên).")
    letter = _free_letter()
    script = diskpart_script(disk, letter)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="ascii") as fh:
        fh.write(script)
        path = fh.name
    try:
        log(f"Đang xoá và định dạng ổ {disk.number} thành FAT32 (nhãn {USB_LABEL})…")
        r = _run(["diskpart", "/s", path], 600)
    finally:
        os.unlink(path)
    if r.returncode != 0:
        raise RuntimeError("diskpart báo lỗi:\n" + (r.stdout + r.stderr).strip()[-1500:])
    root = f"{letter}:\\"
    for _ in range(60):
        if os.path.exists(root):
            return root
        time.sleep(0.5)
    raise RuntimeError(f"Đã định dạng nhưng không thấy ổ {root}. Hãy rút ra cắm lại USB.")


def _copy_file(src: Path, dst: Path, progress: Progress, cancel: threading.Event, label: str) -> None:
    total = src.stat().st_size
    done = 0
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        while True:
            if cancel.is_set():
                raise Cancelled()
            buf = fi.read(4 << 20)
            if not buf:
                break
            fo.write(buf)
            done += len(buf)
            progress(done, total, f"{label}: {done * 100 // max(total, 1)}%")
        fo.flush()
        os.fsync(fo.fileno())


USB_README = """macUSB Win — USB Recovery cho Mac Intel ({name})

CÁCH KHỞI ĐỘNG
1. Cắm USB vào Mac (Mac Intel), tắt máy.
2. Bật máy và giữ phím Option (⌥) cho đến khi thấy danh sách ổ khởi động.
3. Chọn ổ "EFI Boot" (biểu tượng ổ USB màu vàng).
4. Màn hình OpenCore hiện ra: chọn mục macOS Recovery / "macOS Base System" rồi Enter.
5. Kết nối Wi-Fi trong Recovery, chọn "Reinstall macOS" để cài (cần Internet).

LƯU Ý
- Mac có chip T2 (đa số Mac 2018-2020): vào Recovery của máy (Cmd+R) → Utilities →
  Startup Security Utility → chọn "No Security" và "Allow booting from external media".
  OpenCore không được Apple ký nên ở mức "Medium/Full Security" máy sẽ từ chối.
- Nếu Mac có mật khẩu firmware, cần tắt trước.
- Bộ khởi động OpenCore trên USB không cài kext, không sửa NVRAM/SMBIOS của máy.
- Mac chip M (Apple silicon) KHÔNG khởi động được từ USB này.

Nguồn: ảnh Recovery tải trực tiếp từ máy chủ Apple ({product}), đã kiểm tra chữ ký chunklist.
OpenCore © Acidanthera (BSD-3-Clause).
"""


def write_recovery_usb(disk: Disk, dmg: Path, chunklist: Path, product: str, target_name: str,
                       progress: Progress = _noop_progress, log: Log = _noop_log,
                       cancel: Optional[threading.Event] = None, allow_non_usb: bool = False) -> str:
    cancel = cancel or threading.Event()
    efi_src = resource_dir() / "efi" / "EFI"
    if not (efi_src / "BOOT" / "BOOTx64.efi").exists():
        raise RuntimeError("Thiếu bộ khởi động OpenCore trong app (efi/EFI).")
    root = Path(format_usb(disk, log, allow_non_usb))
    log(f"Đã định dạng: {root}")
    log("Chép bộ khởi động OpenCore (EFI)…")
    shutil.copytree(efi_src, root / "EFI", dirs_exist_ok=True)
    for sub in ("ACPI", "Kexts", "Tools", "Resources", "Drivers"):
        (root / "EFI" / "OC" / sub).mkdir(parents=True, exist_ok=True)
    rec = root / "com.apple.recovery.boot"
    rec.mkdir(exist_ok=True)
    shutil.copy2(chunklist, rec / chunklist.name)
    log(f"Chép {dmg.name} ({human_size(dmg.stat().st_size)}) vào USB…")
    _copy_file(dmg, rec / dmg.name, progress, cancel, f"Ghi {dmg.name}")
    (rec / ".contentDetails").write_text(target_name.split(" (")[0], encoding="utf-8")
    (root / "HUONG-DAN.txt").write_text(USB_README.format(name=target_name, product=product), encoding="utf-8")
    log("Kiểm tra lại dữ liệu trên USB…")
    verify_image(rec / dmg.name, rec / chunklist.name, progress, cancel, "Kiểm tra USB")
    log("USB Recovery đã sẵn sàng.")
    return str(root)


# --------------------------------------------------------------------------
# Self test (used by CI)
# --------------------------------------------------------------------------

def selftest(full: bool = False, vhd_disk: Optional[int] = None) -> int:
    ok = True

    def check(name: str, fn):
        nonlocal ok
        try:
            res = fn()
            print(f"[OK]   {name}: {res}")
            return res
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"[FAIL] {name}: {type(e).__name__}: {e}")
            return None

    check("EFI bundled", lambda: (resource_dir() / "efi/EFI/BOOT/BOOTx64.efi").exists() or (_ for _ in ()).throw(RuntimeError("missing")))
    session = check("Apple recovery session", recovery_session)
    seen = {}
    for t in RECOVERY_TARGETS:
        info = check(f"Recovery info {t.name}", lambda t=t: recovery_info(t, session))
        if info:
            seen[t.name] = info["AP"]
            print(f"       {info['AP']}  {os.path.basename(urlparse(info['AU']).path)}")
    target = next(t for t in RECOVERY_TARGETS if t.name.startswith("macOS Ventura"))
    if full:
        res = check("Download+verify Ventura recovery",
                    lambda: download_recovery(target, log=print))
        if res and vhd_disk is not None:
            disk = next(d for d in list_disks(include_non_usb=True) if d.number == vhd_disk)
            root = check("Write recovery USB to test disk",
                         lambda: write_recovery_usb(disk, res[0], res[1], res[2], target.name,
                                                    log=print, allow_non_usb=True))
            if root:
                for rel in ("EFI/BOOT/BOOTx64.efi", "EFI/OC/OpenCore.efi", "EFI/OC/config.plist",
                            "EFI/OC/Drivers/OpenRuntime.efi", f"com.apple.recovery.boot/{res[0].name}",
                            f"com.apple.recovery.boot/{res[1].name}", "HUONG-DAN.txt"):
                    check(f"USB has {rel}", lambda rel=rel: (Path(root) / rel).exists() or (_ for _ in ()).throw(RuntimeError("missing")))
    print("SELFTEST", "PASSED" if ok else "FAILED")
    return 0 if ok else 1
