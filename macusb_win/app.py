"""macUSB Win — tạo USB Recovery cho Mac Intel trên Windows (giao diện tkinter, dạng từng bước)."""
from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import core  # type: ignore
else:
    from . import core

CUSTOM = "Tự nhập board-id của máy Mac…"
USB_STAGES = [("download", "Tải ảnh Recovery từ Apple"), ("verify", "Kiểm tra chữ ký Apple"),
              ("format", "Xoá và định dạng USB (FAT32)"), ("efi", "Chép bộ khởi động OpenCore"),
              ("copy", "Chép ảnh Recovery vào USB"), ("check", "Kiểm tra dữ liệu trên USB")]
LOCAL_STAGES = [("verify", "Kiểm tra file nguồn")] + USB_STAGES[2:]
OFFLINE_STAGES = [("download", "Tải ảnh Recovery từ Apple"), ("verify", "Kiểm tra chữ ký Recovery"),
                  ("pkgdownload", "Tải bộ cài đầy đủ từ Apple"), ("pkgverify", "Kiểm tra bộ cài (chunklist)"),
                  ("format", "Xoá USB, tạo 2 phân vùng (FAT32 + exFAT)"), ("efi", "Chép bộ khởi động OpenCore"),
                  ("copy", "Chép ảnh Recovery"), ("pkgcopy", "Chép bộ cài đầy đủ + script cài"),
                  ("check", "Kiểm tra dữ liệu trên USB")]
PKG_STAGES = [("download", "Tải bộ cài đầy đủ từ Apple"), ("verify", "Kiểm tra toàn vẹn (chunklist)")]
GREY, OK, ERR = "#666", "#1a7f37", "#cf222e"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{core.APP_NAME} {core.APP_VERSION} — USB Recovery cho Mac Intel")
        self.geometry("820x660")
        self.minsize(720, 600)
        try:
            ttk.Style(self).theme_use("vista")
        except tk.TclError:
            pass
        self.option_add("*Font", ("Segoe UI", 10))
        st = ttk.Style(self)
        st.configure("H.TLabel", font=("Segoe UI Semibold", 15))
        st.configure("Sub.TLabel", foreground=GREY)
        st.configure("Big.TButton", font=("Segoe UI Semibold", 10), padding=(14, 6))

        self.events: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.disks: list[core.Disk] = []
        self.installers: list[core.Installer] = []
        self.result_root: str | None = None
        self.stage_rows: dict[str, ttk.Label] = {}
        self.stage_order: list[str] = []

        self.container = ttk.Frame(self)
        self.container.pack(fill="both", expand=True, padx=16, pady=12)
        self.pages: dict[str, ttk.Frame] = {}
        self._page_source()
        self._page_target()
        self._page_review()
        self._page_progress()
        self._page_finish()
        self.show("source")
        self.after(100, self._pump)
        self.after(300, self.refresh_disks)

    # ------------------------------------------------------------------ pages
    def _new_page(self, name: str, title: str, subtitle: str) -> ttk.Frame:
        f = ttk.Frame(self.container)
        ttk.Label(f, text=title, style="H.TLabel").pack(anchor="w")
        ttk.Label(f, text=subtitle, style="Sub.TLabel", wraplength=760, justify="left").pack(anchor="w", pady=(0, 8))
        self.pages[name] = f
        return f

    def _nav(self, page: ttk.Frame, back=None, next_text=None, next_cmd=None) -> ttk.Button | None:
        bar = ttk.Frame(page)
        bar.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Separator(page).pack(side="bottom", fill="x", pady=(8, 0))
        if back:
            ttk.Button(bar, text="← Quay lại", command=back).pack(side="left")
        btn = None
        if next_text:
            btn = ttk.Button(bar, text=next_text, command=next_cmd, style="Big.TButton")
            btn.pack(side="right")
        return btn

    def show(self, name: str) -> None:
        for p in self.pages.values():
            p.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        self.current = name

    # 1. Source
    def _page_source(self) -> None:
        p = self._new_page("source", "Bước 1 — Chọn nguồn",
                           "Tải ảnh Recovery chính thức từ Apple, chọn từ trình tải bộ cài macOS, "
                           "hoặc dùng file Recovery có sẵn trên máy.")
        self._nav(p, next_text="Tiếp tục →", next_cmd=self.go_target)
        self.src_tabs = ttk.Notebook(p)
        self.src_tabs.pack(fill="both", expand=True)

        # A. Recovery from Apple
        a = ttk.Frame(self.src_tabs, padding=12)
        self.src_tabs.add(a, text="  Recovery từ Apple  ")
        ttk.Label(a, text="Phiên bản macOS:").pack(anchor="w")
        self.version = tk.StringVar(value=core.RECOVERY_TARGETS[3].name)
        self.version_cb = ttk.Combobox(a, textvariable=self.version, state="readonly", width=64,
                                       values=[t.name for t in core.RECOVERY_TARGETS] + [CUSTOM])
        self.version_cb.pack(fill="x", pady=(2, 6))
        self.version_cb.bind("<<ComboboxSelected>>", lambda e: self._on_version())
        self.note = ttk.Label(a, style="Sub.TLabel", wraplength=740, justify="left")
        self.note.pack(anchor="w")
        self.custom = ttk.Frame(a)
        ttk.Label(self.custom, text="Board-id:").pack(side="left")
        self.board = tk.StringVar(value="Mac-")
        ttk.Entry(self.custom, textvariable=self.board, width=26).pack(side="left", padx=6)
        self.os_latest = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.custom, text="Bản mới nhất máy này hỗ trợ", variable=self.os_latest).pack(side="left")
        self.custom_hint = ttk.Label(a, style="Sub.TLabel", text="Xem board-id trên Mac: Terminal → ioreg -l | grep board-id")
        self._on_version()

        # B. Downloader
        b = ttk.Frame(self.src_tabs, padding=12)
        self.src_tabs.add(b, text="  Trình tải bộ cài macOS  ")
        top = ttk.Frame(b)
        top.pack(fill="x")
        self.show_beta = tk.BooleanVar(value=True)
        ttk.Button(top, text="Tải danh sách từ Apple", command=self.load_installers).pack(side="left")
        ttk.Checkbutton(top, text="Hiện bản Public Beta", variable=self.show_beta,
                        command=self._fill_installers).pack(side="left", padx=10)
        self.dl_status = ttk.Label(top, style="Sub.TLabel")
        self.dl_status.pack(side="left", padx=6)
        cols = ("ver", "build", "date", "size", "chan", "intel")
        self.tree = ttk.Treeview(b, columns=cols, show="headings", height=9, selectmode="browse")
        for c, t, w in zip(cols, ("Phiên bản", "Build", "Ngày phát hành", "Dung lượng", "Kênh", "Mac Intel"),
                           (250, 80, 110, 90, 90, 80)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=6)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_installer())
        act = ttk.Frame(b)
        act.pack(fill="x")
        self.btn_offline = ttk.Button(act, text="Tạo USB cài đặt offline (thử nghiệm)…",
                                      command=self.go_offline, state="disabled", style="Big.TButton")
        self.btn_offline.pack(side="left")
        self.btn_pkg = ttk.Button(act, text="Chỉ tải bộ cài (.pkg)…", command=self.start_pkg, state="disabled")
        self.btn_pkg.pack(side="left", padx=8)
        self.inst_note = ttk.Label(b, style="Sub.TLabel", wraplength=740, justify="left", text=(
            "• USB cài đặt offline: chứa bộ cài đầy đủ 12–17 GB + macOS Recovery, cài lại máy KHÔNG cần "
            "Internet (cần USB 32 GB). Chế độ thử nghiệm.\n"
            "• \"Tiếp tục →\": tạo USB Recovery cùng phiên bản (nhỏ, cài qua Internet).\n"
            "• Bản Public Beta và macOS 27 chỉ tải được file .pkg. Danh sách gồm Big Sur 11 trở lên."))
        self.inst_note.pack(anchor="w", pady=(6, 0))

        # C. Local
        c = ttk.Frame(self.src_tabs, padding=12)
        self.src_tabs.add(c, text="  Nguồn trên máy  ")
        ttk.Label(c, text="File BaseSystem.dmg / RecoveryImage.dmg (kèm file .chunklist cùng thư mục), "
                          "hoặc thư mục com.apple.recovery.boot:", wraplength=740, justify="left").pack(anchor="w")
        row = ttk.Frame(c)
        row.pack(fill="x", pady=6)
        self.local_path = tk.StringVar()
        ttk.Entry(row, textvariable=self.local_path).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Chọn file…", command=self.browse_file).pack(side="left", padx=(6, 0))
        ttk.Button(row, text="Chọn thư mục…", command=self.browse_dir).pack(side="left", padx=(6, 0))
        self.local_info = ttk.Label(c, style="Sub.TLabel", wraplength=740, justify="left", text=(
            "Ví dụ: ảnh Recovery tải bằng app này trước đó (nút \"Mở thư mục tải\"), hoặc tải bằng "
            "macrecovery/gibMacOS. File .pkg bộ cài đầy đủ không dùng được trên Windows."))
        self.local_info.pack(anchor="w")
        ttk.Button(c, text="Mở thư mục tải của app", command=self.open_cache).pack(anchor="w", pady=10)

    def _on_version(self) -> None:
        if self.version.get() == CUSTOM:
            self.note.configure(text="Nhập board-id của chính máy Mac cần cài; Apple trả bản Recovery phù hợp với máy đó.")
            self.custom.pack(anchor="w", pady=6)
            self.custom_hint.pack(anchor="w")
        else:
            self.custom.pack_forget()
            self.custom_hint.pack_forget()
            t = self._preset()
            self.note.configure(text=("Hỗ trợ: " + t.note) if t and t.note else "")

    def _preset(self) -> core.RecoveryTarget | None:
        return next((t for t in core.RECOVERY_TARGETS if t.name == self.version.get()), None)

    # 2. Target
    def _page_target(self) -> None:
        p = self._new_page("target", "Bước 2 — Chọn ổ USB",
                           "Chỉ hiện ổ USB và thẻ nhớ; ổ hệ thống bị ẩn. Ổ được chọn sẽ bị xoá sạch.")
        self.btn_review = self._nav(p, back=lambda: self.show("source"), next_text="Xem lại →", next_cmd=self.go_review)
        row = ttk.Frame(p)
        row.pack(fill="x", pady=8)
        self.disk = tk.StringVar()
        self.disk_cb = ttk.Combobox(row, textvariable=self.disk, state="readonly")
        self.disk_cb.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Làm mới", command=self.refresh_disks).pack(side="left", padx=(8, 0))
        self.disk_info = ttk.Label(p, style="Sub.TLabel", wraplength=760, justify="left",
                                   text="Dùng USB từ 4 GB trở lên (khuyên dùng 8 GB). App tạo 1 phân vùng FAT32 "
                                        "(tối đa 16 GB) tên MACRECOVERY.")
        self.disk_info.pack(anchor="w")

    # 3. Review
    def _page_review(self) -> None:
        p = self._new_page("review", "Bước 3 — Xem lại thông tin",
                           "Kiểm tra kỹ trước khi bắt đầu. Toàn bộ dữ liệu trên ổ USB sẽ bị xoá.")
        self._nav(p, back=lambda: self.show("target"), next_text="Bắt đầu tạo USB", next_cmd=self.start_make)
        self.review = tk.Text(p, height=16, wrap="word", relief="solid", borderwidth=1, padx=12, pady=10,
                              font=("Segoe UI", 10), background="#fbfbfb")
        self.review.pack(fill="both", expand=True)
        self.review.tag_configure("b", font=("Segoe UI Semibold", 10))
        self.review.tag_configure("warn", foreground=ERR, font=("Segoe UI Semibold", 10))
        self.confirm = tk.BooleanVar(value=False)
        ttk.Checkbutton(p, text="Tôi hiểu dữ liệu trên ổ USB sẽ bị xoá vĩnh viễn", variable=self.confirm).pack(anchor="w", pady=(8, 0))

    # 4. Progress
    def _page_progress(self) -> None:
        p = self._new_page("progress", "Đang thực hiện…", "Không rút USB và không tắt máy trong lúc làm.")
        bar = ttk.Frame(p)
        bar.pack(side="bottom", fill="x", pady=(8, 0))
        self.cancel_btn = ttk.Button(bar, text="Huỷ", command=self.cancel.set)
        self.cancel_btn.pack(side="right")
        self.stage_box = ttk.Frame(p)
        self.stage_box.pack(fill="x", pady=(0, 8))
        self.bar = ttk.Progressbar(p, mode="determinate", maximum=1000)
        self.bar.pack(fill="x")
        self.status = ttk.Label(p, text="")
        self.status.pack(anchor="w", pady=(2, 6))
        logf = ttk.Frame(p)
        logf.pack(fill="both", expand=True)
        self.log_box = tk.Text(logf, height=8, wrap="word", state="disabled", font=("Consolas", 9),
                               background="#fafafa", relief="solid", borderwidth=1)
        sb = ttk.Scrollbar(logf, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=sb.set)
        self.log_box.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _setup_stages(self, stages: list[tuple[str, str]]) -> None:
        for w in self.stage_box.winfo_children():
            w.destroy()
        self.stage_rows, self.stage_order = {}, [k for k, _ in stages]
        for i, (key, text) in enumerate(stages, 1):
            lbl = ttk.Label(self.stage_box, text=f"○  {i}. {text}", foreground=GREY)
            lbl.pack(anchor="w")
            self.stage_rows[key] = lbl
        self.active_stage = None

    def _set_stage(self, key: str) -> None:
        if key not in self.stage_rows:
            return
        idx = self.stage_order.index(key)
        for i, k in enumerate(self.stage_order):
            lbl = self.stage_rows[k]
            text = lbl.cget("text")[3:]
            if i < idx:
                lbl.configure(text="✔  " + text, foreground=OK)
            elif i == idx:
                lbl.configure(text="▶  " + text, foreground="#0969da", font=("Segoe UI Semibold", 10))
            else:
                lbl.configure(text="○  " + text, foreground=GREY, font=("Segoe UI", 10))
        self.active_stage = key

    def _finish_stages(self, ok: bool) -> None:
        for i, k in enumerate(self.stage_order):
            lbl = self.stage_rows[k]
            text = lbl.cget("text")[3:]
            if ok:
                lbl.configure(text="✔  " + text, foreground=OK, font=("Segoe UI", 10))
            elif k == self.active_stage:
                lbl.configure(text="✖  " + text, foreground=ERR)

    # 5. Finish
    def _page_finish(self) -> None:
        p = self._new_page("finish", "Kết quả", "")
        self.fin_title = p.winfo_children()[0]
        self.fin_sub = p.winfo_children()[1]
        bar = ttk.Frame(p)
        bar.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(bar, text="Làm lại từ đầu", command=self.restart).pack(side="left")
        self.btn_eject = ttk.Button(bar, text="Tháo USB an toàn", command=self.eject, style="Big.TButton")
        self.btn_open = ttk.Button(bar, text="Mở", command=self.open_result)
        self.fin_text = tk.Text(p, height=14, wrap="word", relief="flat", padx=4, pady=8,
                                font=("Segoe UI", 10), background=self.cget("background"))
        self.fin_text.pack(fill="both", expand=True)

    # -------------------------------------------------------- thread plumbing
    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self.log_box.configure(state="normal")
                    self.log_box.insert("end", payload + "\n")
                    self.log_box.see("end")
                    self.log_box.configure(state="disabled")
                elif kind == "progress":
                    done, total, text = payload
                    if total:
                        self.bar.configure(value=done * 1000 / total)
                    self.status.configure(text=text)
                elif kind == "stage":
                    self._set_stage(payload)
                    self.bar.configure(value=0)
                elif kind == "done":
                    self._on_done(*payload)
                elif kind == "disks":
                    self._set_disks(payload)
                elif kind == "installers":
                    self.installers = payload
                    self._fill_installers()
                elif kind == "dlstatus":
                    self.dl_status.configure(text=payload)
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def _run(self, title: str, stages, job, finish) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.cancel.clear()
        self.pages["progress"].winfo_children()[0].configure(text=title)
        self._setup_stages(stages)
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.bar.configure(value=0)
        self.cancel_btn.configure(state="normal")
        self.show("progress")
        self._finish_cb = finish
        log = lambda m: self.events.put(("log", m))
        prog = lambda d, t, x: self.events.put(("progress", (d, t, x)))
        stage = lambda k: self.events.put(("stage", k))

        def wrapper():
            try:
                res = job(log, prog, stage)
                self.events.put(("done", (True, res)))
            except core.Cancelled:
                self.events.put(("done", (False, "Đã huỷ theo yêu cầu.")))
            except Exception as e:  # noqa: BLE001
                log(f"LỖI: {e}")
                self.events.put(("done", (False, str(e))))

        self.worker = threading.Thread(target=wrapper, daemon=True)
        self.worker.start()

    def _on_done(self, ok: bool, res) -> None:
        self._finish_stages(ok)
        self.cancel_btn.configure(state="disabled")
        self._finish_cb(ok, res)

    # --------------------------------------------------------------- actions
    def refresh_disks(self) -> None:
        def job():
            try:
                self.events.put(("disks", core.list_disks()))
            except Exception as e:  # noqa: BLE001
                self.events.put(("disks", []))
                self.events.put(("log", f"Không đọc được danh sách ổ: {e}"))
        threading.Thread(target=job, daemon=True).start()

    def _set_disks(self, disks) -> None:
        self.disks = disks
        labels = [d.label() for d in disks]
        self.disk_cb.configure(values=labels)
        if self.disk.get() not in labels:
            self.disk.set(labels[0] if labels else "")
        if not labels:
            self.disk.set("")
            self.disk_cb.set("Không thấy ổ USB — cắm USB rồi bấm Làm mới")

    def _selected_disk(self) -> core.Disk | None:
        return next((d for d in self.disks if d.label() == self.disk.get()), None)

    def load_installers(self) -> None:
        self.events.put(("dlstatus", "Đang đọc danh mục Apple…"))

        def job():
            try:
                items = core.list_installers(True, lambda m: self.events.put(("dlstatus", m)))
                self.events.put(("installers", items))
                self.events.put(("dlstatus", f"{len(items)} bộ cài"))
            except Exception as e:  # noqa: BLE001
                self.events.put(("dlstatus", f"Lỗi: {e}"))
        threading.Thread(target=job, daemon=True).start()

    def _fill_installers(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for i, inst in enumerate(self.installers):
            if inst.channel == "beta" and not self.show_beta.get():
                continue
            self.tree.insert("", "end", iid=str(i), values=(
                f"{inst.title} {inst.version}", inst.build, inst.post_date, core.human_size(inst.size),
                "Public Beta" if inst.channel == "beta" else "Chính thức",
                "Có" if inst.intel_ok else "Không (chỉ chip M)"))
        self._on_installer()

    def _installer(self) -> core.Installer | None:
        sel = self.tree.selection()
        return self.installers[int(sel[0])] if sel else None

    def _on_installer(self) -> None:
        inst = self._installer()
        self.btn_pkg.configure(state="normal" if inst else "disabled")
        self.btn_offline.configure(state="normal" if inst and inst.recovery_target() else "disabled")

    def go_offline(self) -> None:
        inst = self._installer()
        if not inst or not inst.recovery_target():
            return
        self._src = ("offline", inst, f"Bộ cài đầy đủ {inst.label()} ({core.human_size(inst.size)}) "
                                      f"+ {inst.recovery_target().name} — USB cài đặt OFFLINE (thử nghiệm)")
        self.refresh_disks()
        self.show("target")

    def browse_file(self) -> None:
        f = filedialog.askopenfilename(title="Chọn ảnh Recovery", filetypes=[
            ("Ảnh Recovery", "*.dmg *.chunklist"), ("Bộ cài macOS", "*.pkg"), ("Tất cả", "*.*")])
        if f:
            self.local_path.set(f)

    def browse_dir(self) -> None:
        d = filedialog.askdirectory(title="Chọn thư mục com.apple.recovery.boot")
        if d:
            self.local_path.set(d)

    def open_cache(self) -> None:
        path = core.data_dir() / "recovery"
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))  # type: ignore[attr-defined]

    # source resolution -----------------------------------------------------
    def _source(self):
        """Returns ('apple', RecoveryTarget, description) or ('local', path, description)."""
        tab = self.src_tabs.index(self.src_tabs.select())
        if tab == 0:
            if self.version.get() == CUSTOM:
                bid = self.board.get().strip()
                if not (bid.startswith("Mac-") and len(bid) == 20):
                    raise ValueError("Board-id không hợp lệ (dạng Mac-XXXXXXXXXXXXXXXX).")
                t = core.RecoveryTarget(f"Recovery cho {bid}", bid,
                                        os_type="latest" if self.os_latest.get() else "default")
            else:
                t = self._preset()
            return "apple", t, f"Ảnh Recovery từ máy chủ Apple — {t.name}"
        if tab == 1:
            inst = self._installer()
            if not inst:
                raise ValueError("Hãy bấm \"Tải danh sách từ Apple\" và chọn một phiên bản.")
            t = inst.recovery_target()
            if not t:
                why = ("bản Public Beta không có ảnh Recovery công khai" if inst.channel == "beta"
                       else "phiên bản này chỉ chạy trên Mac chip M")
                raise ValueError(f"Không tạo được USB Recovery cho {inst.label()}: {why}. "
                                 "Bạn vẫn có thể tải bộ cài đầy đủ (.pkg) để dùng trên Mac.")
            return "apple", t, f"Ảnh Recovery từ Apple — {t.name} (chọn từ trình tải: {inst.label()})"
        path = self.local_path.get().strip()
        if not path:
            raise ValueError("Hãy chọn file hoặc thư mục Recovery.")
        dmg, _ = core.find_local_recovery(path)
        return "local", path, f"File trên máy — {dmg}"

    def go_target(self) -> None:
        try:
            self._src = self._source()
        except (ValueError, RuntimeError) as e:
            messagebox.showwarning(core.APP_NAME, str(e))
            return
        self.refresh_disks()
        self.show("target")

    def go_review(self) -> None:
        disk = self._selected_disk()
        if not disk:
            messagebox.showwarning(core.APP_NAME, "Chưa chọn ổ USB. Cắm USB rồi bấm Làm mới.")
            return
        kind, val, desc = self._src
        need = core.offline_min_size(val.size) if kind == "offline" else 4 * 1024 ** 3
        if disk.size < need:
            messagebox.showwarning(core.APP_NAME, f"USB quá nhỏ. Cần ít nhất {core.human_size(need)}"
                                   + (" (khuyên dùng USB 32 GB)." if kind == "offline" else "."))
            return
        self._disk = disk
        part = "16 GB" if disk.size > 32000 * 1024 ** 2 else "toàn bộ ổ"
        r = self.review
        r.configure(state="normal")
        r.delete("1.0", "end")
        r.insert("end", "Nguồn\n", "b")
        r.insert("end", f"  {desc}\n")
        if kind == "apple" and val.note:
            r.insert("end", f"  Máy hỗ trợ: {val.note}\n")
        r.insert("end", "\nỔ đích\n", "b")
        r.insert("end", f"  {disk.label()}\n")
        r.insert("end", "\nCác việc sẽ làm\n", "b")
        steps = {"apple": USB_STAGES, "local": LOCAL_STAGES, "offline": OFFLINE_STAGES}[kind]
        for i, (_, t) in enumerate(steps, 1):
            r.insert("end", f"  {i}. {t}\n")
        if kind == "offline":
            r.insert("end", f"\n  Phân vùng: MBR — {core.USB_LABEL} (FAT32, {core.BOOT_PART_MB} MB, khởi động) + "
                            f"{core.INSTALL_LABEL} (exFAT, phần còn lại, chứa bộ cài)\n")
            r.insert("end", "  Cần tải khoảng " + core.human_size(val.size + 900 * 1024 ** 2)
                     + " (bỏ qua nếu đã tải trước đó). Ổ C: cần đủ chỗ trống.\n")
        else:
            r.insert("end", f"\n  Phân vùng: MBR, 1 phân vùng FAT32 ({part}), nhãn {core.USB_LABEL}\n")
        r.insert("end", "  Bộ khởi động: OpenCore tối giản (không kext, không sửa NVRAM/SMBIOS)\n")
        r.insert("end", "\nCẢNH BÁO: toàn bộ dữ liệu trên ổ USB này sẽ bị xoá vĩnh viễn.\n", "warn")
        if kind == "offline":
            r.insert("end", "Chế độ THỬ NGHIỆM: cài offline bằng script trong Terminal của Recovery. Nếu không chạy, "
                            "USB vẫn dùng được như USB Recovery (cài qua Internet).")
        else:
            r.insert("end", "USB này dành cho Mac Intel; cài macOS qua Internet trong Recovery.")
        r.configure(state="disabled")
        self.confirm.set(False)
        self.show("review")

    def start_make(self) -> None:
        if not self.confirm.get():
            messagebox.showwarning(core.APP_NAME, "Hãy tích ô xác nhận xoá dữ liệu trên USB.")
            return
        kind, val, desc = self._src
        disk = self._disk
        if kind == "offline":
            self._start_offline(val, disk)
            return
        name = val.name if kind == "apple" else f"Recovery từ file {Path(val).name}"

        def job(log, prog, stage):
            if kind == "apple":
                dmg, cnk, product = core.download_recovery(val, prog, log, self.cancel, stage)
            else:
                dmg, cnk, product = core.use_local_recovery(val, prog, log, self.cancel, stage)
            root = core.write_recovery_usb(disk, dmg, cnk, product, name, prog, log, self.cancel, stage=stage)
            return {"root": root, "name": name, "product": product, "disk": disk.label()}

        self._run("Đang tạo USB Recovery…", USB_STAGES if kind == "apple" else LOCAL_STAGES, job, self._finish_usb)

    def _start_offline(self, inst, disk) -> None:
        name = f"{inst.title} {inst.version} ({inst.build})"

        def job(log, prog, stage):
            dmg, cnk, product, pkg, pcnk = core.prepare_offline_sources(inst, prog, log, self.cancel, stage)
            boot, data = core.write_offline_usb(disk, dmg, cnk, product, name, pkg, pcnk, prog, log,
                                                self.cancel, stage=stage)
            return {"root": boot, "data": data, "name": name, "product": product, "disk": disk.label(),
                    "offline": True}

        self._run("Đang tạo USB cài đặt offline…", OFFLINE_STAGES, job, self._finish_usb)

    def _finish_usb(self, ok: bool, res) -> None:
        t = self.fin_text
        t.configure(state="normal")
        t.delete("1.0", "end")
        self.btn_eject.pack_forget()
        self.btn_open.pack_forget()
        if ok:
            self.result_root = res["root"]
            off = res.get("offline")
            self.fin_title.configure(text="✔  USB cài đặt offline đã sẵn sàng" if off else "✔  USB Recovery đã sẵn sàng",
                                     foreground=OK)
            self.fin_sub.configure(text=f"{res['name']} — ổ {res['root']}" + (f" + {res['data']}" if off else ""))
            if off:
                t.insert("end", "Cài lại macOS không cần Internet:\n"
                                "1. Bấm \"Tháo USB an toàn\", cắm USB vào Mac, bật máy và giữ phím Option (⌥).\n"
                                "2. Chọn \"EFI Boot\" → mục macOS Recovery.\n"
                                "3. (Muốn xoá sạch máy) Disk Utility → Erase ổ trong: APFS, tên \"Macintosh HD\".\n"
                                "4. Utilities → Terminal, gõ:   sh /Volumes/MACINSTALL/cai-macos.sh\n"
                                "5. Nhập tên ổ (Enter = Macintosh HD) và chờ máy tự cài, tự khởi động lại.\n\n"
                                "Chế độ thử nghiệm: nếu script báo lỗi, chụp màn hình gửi lại; vẫn có thể chọn "
                                "\"Reinstall macOS\" để cài qua Internet.\n\n"
                                f"Ổ đích: {res['disk']}\nGói Recovery: {res['product']}\n"
                                "Hướng dẫn chi tiết: HUONG-DAN.txt trên USB.")
            else:
                t.insert("end", "Bước tiếp theo trên Mac Intel:\n"
                            "1. Bấm \"Tháo USB an toàn\" bên dưới rồi rút USB.\n"
                            "2. Cắm USB vào Mac, bật máy và giữ phím Option (⌥).\n"
                            "3. Chọn \"EFI Boot\", rồi chọn mục macOS Recovery / macOS Base System.\n"
                            "4. Kết nối Wi-Fi, chọn \"Reinstall macOS\".\n\n"
                            "Mac có chip T2 (đời 2018–2020): cần đặt Startup Security Utility → No Security "
                            "và Allow booting from external media trước.\n\n"
                            f"Ổ đích: {res['disk']}\nGói Recovery: {res['product']}\n"
                            "Hướng dẫn chi tiết: file HUONG-DAN.txt trên USB.")
            self.btn_eject.configure(state="normal")
            self.btn_eject.pack(side="right")
            self.btn_open.configure(text="Mở ổ USB")
            self.btn_open.pack(side="right", padx=8)
        else:
            self.result_root = None
            self.fin_title.configure(text="✖  Chưa tạo được USB", foreground=ERR)
            self.fin_sub.configure(text="Xem chi tiết lỗi bên dưới. Có thể bấm Làm lại để thử lần nữa.")
            t.insert("end", str(res))
        t.configure(state="disabled")
        self.show("finish")

    def start_pkg(self) -> None:
        inst = self._installer()
        if not inst:
            return
        folder = filedialog.askdirectory(title="Chọn thư mục lưu bộ cài (cần khoảng 20 GB trống)",
                                         initialdir=str(Path.home() / "Downloads"))
        if not folder:
            return

        def job(log, prog, stage):
            path = core.download_installer(inst, Path(folder), prog, log, self.cancel, stage)
            return {"path": str(path), "name": inst.label()}

        def finish(ok, res):
            t = self.fin_text
            t.configure(state="normal")
            t.delete("1.0", "end")
            self.btn_eject.pack_forget()
            self.btn_open.pack_forget()
            if ok:
                self.result_root = str(Path(res["path"]).parent)
                self.fin_title.configure(text="✔  Đã tải xong bộ cài", foreground=OK)
                self.fin_sub.configure(text=res["name"])
                t.insert("end", f"File: {res['path']}\n\n"
                                "Cách dùng trên máy Mac: chép file .pkg sang Mac, mở file để cài app "
                                "\"Install macOS …\" vào thư mục Applications, rồi dùng macUSB (bản Mac) "
                                "để tạo USB cài offline.\n\n"
                                "Trên Windows: dùng tab \"Recovery từ Apple\" để tạo USB Recovery cùng phiên bản.")
                self.btn_open.configure(text="Mở thư mục")
                self.btn_open.pack(side="right")
            else:
                self.result_root = None
                self.fin_title.configure(text="✖  Chưa tải xong", foreground=ERR)
                self.fin_sub.configure(text="Lần sau bấm tải lại sẽ tiếp tục từ chỗ đang dở.")
                t.insert("end", str(res))
            t.configure(state="disabled")
            self.show("finish")

        self._run(f"Đang tải {inst.label()}…", PKG_STAGES, job, finish)

    def eject(self) -> None:
        if not self.result_root:
            return
        try:
            core.eject_drive(self.result_root)
            self.btn_eject.configure(state="disabled")
            self.fin_sub.configure(text="Đã tháo USB an toàn. Bạn có thể rút USB ra.")
        except Exception as e:  # noqa: BLE001
            messagebox.showwarning(core.APP_NAME, str(e))

    def open_result(self) -> None:
        if self.result_root and os.path.exists(self.result_root):
            os.startfile(self.result_root)  # type: ignore[attr-defined]

    def restart(self) -> None:
        self.result_root = None
        self.show("source")
        self.refresh_disks()


def ui_smoke_test() -> int:
    """Build every page once (used by CI) and exit."""
    app = App()
    app.update()
    for name in ("target", "review", "progress", "finish", "source"):
        app.show(name)
        app.update()
    app._setup_stages(USB_STAGES)
    for k, _ in USB_STAGES:
        app._set_stage(k)
    app._finish_stages(True)
    app._finish_usb(True, {"root": "Z:\\", "name": "test", "product": "p", "disk": "d"})
    app._finish_usb(True, {"root": "Z:\\", "data": "Y:\\", "name": "t", "product": "p", "disk": "d", "offline": True})
    app._setup_stages(OFFLINE_STAGES)
    for k, _ in OFFLINE_STAGES:
        app._set_stage(k)
    app._finish_usb(False, "lỗi thử")
    app.update()
    app.destroy()
    print("UI SMOKE TEST PASSED")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if "--out" in args:
        out = args[args.index("--out") + 1]
        sys.stdout = sys.stderr = open(out, "w", encoding="utf-8", buffering=1)
    if args and args[0] == "--selftest":
        full = "--full" in args
        vhd = int(args[args.index("--disk") + 1]) if "--disk" in args else None
        return core.selftest(full=full, vhd_disk=vhd)
    if args and args[0] == "--uitest":
        return ui_smoke_test()
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    app = App()
    if os.name == "nt":
        try:
            if not ctypes.windll.shell32.IsUserAnAdmin():
                messagebox.showwarning(core.APP_NAME, "Hãy chạy app với quyền Administrator để ghi USB.")
        except Exception:  # noqa: BLE001
            pass
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
