"""macUSB Win - tạo USB Recovery cho Mac Intel trên Windows (giao diện tkinter)."""
from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import core  # type: ignore
else:
    from . import core

CUSTOM = "Tự nhập board-id của máy Mac…"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{core.APP_NAME} {core.APP_VERSION} — USB Recovery cho Mac Intel")
        self.geometry("760x640")
        self.minsize(680, 560)
        try:
            ttk.Style(self).theme_use("vista")
        except tk.TclError:
            pass
        self.option_add("*Font", ("Segoe UI", 10))

        self.events: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.disks: list[core.Disk] = []

        self._build()
        self.after(100, self._pump)
        self.after(300, self.refresh_disks)

    # ---------------- UI ----------------
    def _build(self) -> None:
        pad = {"padx": 14, "pady": 6}
        head = ttk.Frame(self)
        head.pack(fill="x", **pad)
        ttk.Label(head, text="Tạo USB Recovery cho Mac Intel", font=("Segoe UI Semibold", 15)).pack(anchor="w")
        ttk.Label(head, foreground="#555", wraplength=700, justify="left",
                  text="Ảnh Recovery được tải thẳng từ máy chủ Apple và kiểm tra chữ ký. USB khởi động trên "
                       "Mac Intel (giữ phím Option khi bật máy), rồi cài macOS qua Internet.").pack(anchor="w")

        box1 = ttk.LabelFrame(self, text=" 1. Chọn phiên bản macOS ")
        box1.pack(fill="x", **pad)
        names = [t.name for t in core.RECOVERY_TARGETS] + [CUSTOM]
        self.version = tk.StringVar(value=core.RECOVERY_TARGETS[3].name)  # Ventura
        self.version_cb = ttk.Combobox(box1, textvariable=self.version, values=names, state="readonly", width=60)
        self.version_cb.pack(fill="x", padx=10, pady=(8, 4))
        self.version_cb.bind("<<ComboboxSelected>>", lambda e: self._on_version())
        self.note = ttk.Label(box1, foreground="#555", wraplength=690, justify="left")
        self.note.pack(anchor="w", padx=10, pady=(0, 6))
        self.custom = ttk.Frame(box1)
        ttk.Label(self.custom, text="Board-id:").pack(side="left")
        self.board = tk.StringVar(value="Mac-")
        ttk.Entry(self.custom, textvariable=self.board, width=26).pack(side="left", padx=6)
        self.os_latest = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.custom, text="Bản mới nhất máy này hỗ trợ", variable=self.os_latest).pack(side="left", padx=6)
        ttk.Label(box1, foreground="#777", wraplength=690, justify="left",
                  text="Xem board-id trên Mac: Terminal → ioreg -l | grep board-id").pack(anchor="w", padx=10, pady=(0, 8))
        self._on_version()

        box2 = ttk.LabelFrame(self, text=" 2. Chọn ổ USB (sẽ bị XOÁ SẠCH) ")
        box2.pack(fill="x", **pad)
        row = ttk.Frame(box2)
        row.pack(fill="x", padx=10, pady=8)
        self.disk = tk.StringVar()
        self.disk_cb = ttk.Combobox(row, textvariable=self.disk, state="readonly", width=60)
        self.disk_cb.pack(side="left", fill="x", expand=True)
        self.refresh_btn = ttk.Button(row, text="Làm mới", command=self.refresh_disks)
        self.refresh_btn.pack(side="left", padx=(8, 0))
        ttk.Label(box2, foreground="#777", text="Dùng USB từ 8 GB trở lên. Chỉ hiện ổ USB/thẻ nhớ, không hiện ổ hệ thống.").pack(anchor="w", padx=10, pady=(0, 8))

        act = ttk.Frame(self)
        act.pack(fill="x", **pad)
        self.make_btn = ttk.Button(act, text="Tạo USB Recovery", command=self.start_make)
        self.make_btn.pack(side="left")
        self.dl_btn = ttk.Button(act, text="Chỉ tải về", command=self.start_download)
        self.dl_btn.pack(side="left", padx=8)
        self.cancel_btn = ttk.Button(act, text="Huỷ", command=self.cancel.set, state="disabled")
        self.cancel_btn.pack(side="left")
        ttk.Button(act, text="Hướng dẫn khởi động", command=self.show_help).pack(side="right")
        ttk.Button(act, text="Mở thư mục tải", command=self.open_cache).pack(side="right", padx=8)

        self.bar = ttk.Progressbar(self, mode="determinate", maximum=1000)
        self.bar.pack(fill="x", padx=14, pady=(4, 0))
        self.status = ttk.Label(self, text="Sẵn sàng.")
        self.status.pack(anchor="w", padx=14, pady=(2, 4))

        logf = ttk.Frame(self)
        logf.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self.log_box = tk.Text(logf, height=10, wrap="word", state="disabled", font=("Consolas", 9),
                               background="#fafafa", relief="solid", borderwidth=1)
        sb = ttk.Scrollbar(logf, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=sb.set)
        self.log_box.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _on_version(self) -> None:
        if self.version.get() == CUSTOM:
            self.note.configure(text="Nhập board-id của chính máy Mac cần cài. Apple sẽ trả bản Recovery phù hợp với máy đó.")
            self.custom.pack(anchor="w", padx=10, pady=(0, 6), before=self.note.master.winfo_children()[-1])
        else:
            self.custom.pack_forget()
            t = self._target()
            self.note.configure(text=("Hỗ trợ: " + t.note) if t and t.note else "")

    def _target(self) -> core.RecoveryTarget | None:
        name = self.version.get()
        if name == CUSTOM:
            bid = self.board.get().strip()
            if not (bid.startswith("Mac-") and len(bid) == 20):
                return None
            return core.RecoveryTarget(f"Recovery cho {bid}", bid,
                                       os_type="latest" if self.os_latest.get() else "default")
        return next((t for t in core.RECOVERY_TARGETS if t.name == name), None)

    # ---------------- thread plumbing ----------------
    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._append(payload)
                elif kind == "progress":
                    done, total, text = payload
                    if total:
                        self.bar.configure(mode="determinate", value=done * 1000 / total)
                    self.status.configure(text=text)
                elif kind == "done":
                    self._busy(False)
                    ok, msg = payload
                    self.status.configure(text=msg)
                    self.bar.configure(value=1000 if ok else 0)
                    (messagebox.showinfo if ok else messagebox.showerror)(core.APP_NAME, msg)
                elif kind == "disks":
                    self._set_disks(payload)
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def _append(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _busy(self, busy: bool) -> None:
        st = "disabled" if busy else "normal"
        for w in (self.make_btn, self.dl_btn, self.refresh_btn):
            w.configure(state=st)
        self.version_cb.configure(state="disabled" if busy else "readonly")
        self.disk_cb.configure(state="disabled" if busy else "readonly")
        self.cancel_btn.configure(state="normal" if busy else "disabled")

    def _run(self, job) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.cancel.clear()
        self._busy(True)
        self.bar.configure(value=0)
        log = lambda m: self.events.put(("log", m))
        prog = lambda d, t, x: self.events.put(("progress", (d, t, x)))

        def wrapper():
            try:
                msg = job(log, prog)
                self.events.put(("done", (True, msg)))
            except core.Cancelled:
                self.events.put(("done", (False, "Đã huỷ.")))
            except Exception as e:  # noqa: BLE001
                log(f"LỖI: {e}")
                self.events.put(("done", (False, f"Lỗi: {e}")))

        self.worker = threading.Thread(target=wrapper, daemon=True)
        self.worker.start()

    # ---------------- actions ----------------
    def refresh_disks(self) -> None:
        def job():
            try:
                self.events.put(("disks", core.list_disks()))
            except Exception as e:  # noqa: BLE001
                self.events.put(("log", f"Không đọc được danh sách ổ: {e}"))
                self.events.put(("disks", []))
        threading.Thread(target=job, daemon=True).start()

    def _set_disks(self, disks: list) -> None:
        self.disks = disks
        labels = [d.label() for d in disks]
        self.disk_cb.configure(values=labels)
        if self.disk.get() not in labels:
            self.disk.set(labels[0] if labels else "")
        if not labels:
            self.status.configure(text="Không thấy ổ USB nào. Cắm USB rồi bấm Làm mới.")

    def _selected_disk(self) -> core.Disk | None:
        label = self.disk.get()
        return next((d for d in self.disks if d.label() == label), None)

    def start_download(self) -> None:
        target = self._target()
        if not target:
            messagebox.showwarning(core.APP_NAME, "Board-id không hợp lệ (dạng Mac-XXXXXXXXXXXXXXXX).")
            return

        def job(log, prog):
            dmg, cnk, product = core.download_recovery(target, prog, log, self.cancel)
            return f"Đã tải và kiểm tra xong {target.name} ({product}).\nLưu tại: {dmg.parent}"
        self._run(job)

    def start_make(self) -> None:
        target = self._target()
        disk = self._selected_disk()
        if not target:
            messagebox.showwarning(core.APP_NAME, "Board-id không hợp lệ (dạng Mac-XXXXXXXXXXXXXXXX).")
            return
        if not disk:
            messagebox.showwarning(core.APP_NAME, "Chưa chọn ổ USB. Cắm USB rồi bấm Làm mới.")
            return
        if disk.size < 4 * 1024 ** 3:
            messagebox.showwarning(core.APP_NAME, "USB quá nhỏ. Hãy dùng USB từ 4 GB trở lên (khuyên dùng 8 GB).")
            return
        if not messagebox.askyesno(
                core.APP_NAME,
                f"TOÀN BỘ dữ liệu trên ổ sau sẽ bị XOÁ:\n\n{disk.label()}\n\n"
                f"Phiên bản: {target.name}\n\nTiếp tục?", icon="warning"):
            return

        def job(log, prog):
            dmg, cnk, product = core.download_recovery(target, prog, log, self.cancel)
            root = core.write_recovery_usb(disk, dmg, cnk, product, target.name, prog, log, self.cancel)
            return (f"Xong! USB Recovery ({target.name}) đã sẵn sàng ở ổ {root}\n\n"
                    "Rút USB an toàn, cắm vào Mac Intel, bật máy và giữ phím Option. "
                    "Chọn \"EFI Boot\" → mục macOS Recovery. Xem HUONG-DAN.txt trên USB.")
        self._run(job)

    def open_cache(self) -> None:
        path = core.data_dir() / "recovery"
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))  # type: ignore[attr-defined]

    def show_help(self) -> None:
        win = tk.Toplevel(self)
        win.title("Hướng dẫn khởi động")
        win.geometry("640x480")
        txt = tk.Text(win, wrap="word", font=("Segoe UI", 10), padx=12, pady=12)
        txt.insert("1.0", core.USB_README.format(name="phiên bản đã chọn", product="—"))
        txt.configure(state="disabled")
        txt.pack(fill="both", expand=True)


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "--selftest":
        out = None
        if "--out" in args:
            out = args[args.index("--out") + 1]
            sys.stdout = sys.stderr = open(out, "w", encoding="utf-8", buffering=1)
        full = "--full" in args
        vhd = int(args[args.index("--disk") + 1]) if "--disk" in args else None
        return core.selftest(full=full, vhd_disk=vhd)
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
        try:
            if not ctypes.windll.shell32.IsUserAnAdmin():
                messagebox.showwarning(core.APP_NAME, "Hãy chạy app với quyền Administrator để ghi USB.")
        except Exception:  # noqa: BLE001
            pass
    App().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
