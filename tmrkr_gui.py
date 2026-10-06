"""GUI for the The Midnight Ride Korean patcher."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import tmrkr
from tmrkr_output import build_output, BASE_MOD

BUNDLED_BASE = "FO4_AE_1.11.191.Kor"


def program_folder() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def bundled_base_package() -> Path:
    return program_folder() / BUNDLED_BASE


class App:
    def __init__(self, window):
        self.window = window
        self.folder = program_folder()
        self.events = queue.Queue()
        self.output = None
        window.title(f"The Midnight Ride 한국어 패쳐 v{tmrkr.VERSION}")
        window.minsize(840, 330)

        frame = ttk.Frame(window, padding=22)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)

        ttk.Label(frame, text="The Midnight Ride MO2 폴더").grid(
            row=0, column=0, columnspan=3, sticky="w")
        default_mo2 = "C:/Modlists/TMR" if Path("C:/Modlists/TMR/ModOrganizer.ini").is_file() else ""
        self.mo2 = tk.StringVar(value=default_mo2)
        ttk.Entry(frame, textvariable=self.mo2).grid(row=1, column=0, sticky="ew", pady=(6, 14))
        ttk.Button(frame, text="찾아보기", command=self.choose_mo2).grid(
            row=1, column=1, padx=(8, 0), pady=(6, 14))

        self.generate = ttk.Button(frame, text="Output 생성", command=self.start)
        self.generate.grid(row=2, column=0, sticky="w")
        self.open_button = ttk.Button(
            frame, text="Output 폴더 열기", command=self.open_output, state="disabled")
        self.open_button.grid(row=2, column=1, padx=(8, 0))

        self.status = tk.StringVar(value=(
            f"본편 한국어 리소스({BUNDLED_BASE})는 패쳐에 포함되어 있습니다.\n"
            f"본편 번역은 새 MO2 모드 '{BASE_MOD}'로 생성됩니다.\n"
            "나머지 번역은 기존 TMR 모드와 같은 폴더/상대경로로 생성되므로, "
            "Output의 내용을 TMR MO2 폴더에 복사하면 기존 파일을 덮어씁니다."
        ))
        ttk.Label(frame, textvariable=self.status, wraplength=790, justify="left").grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(18, 0))
        window.after(150, self.poll)

    def choose_mo2(self):
        folder = filedialog.askdirectory(title="ModOrganizer.ini가 있는 TMR 폴더")
        if folder:
            self.mo2.set(folder)

    def start(self):
        root = Path(self.mo2.get().strip())
        base = bundled_base_package()
        if not (root / "ModOrganizer.ini").is_file():
            messagebox.showerror("폴더 확인", "ModOrganizer.ini가 있는 TMR MO2 폴더를 선택해주세요.")
            return
        if not (base / "Strings").is_dir() or not (base / "Interface").is_dir():
            messagebox.showerror(
                "내장 한국어 리소스 확인",
                f"패쳐 옆의 {BUNDLED_BASE} 폴더가 없거나 손상되었습니다. 압축을 다시 풀어주세요.")
            return
        data = self.folder / "TranslationData"
        if not (data / "catalog.json").is_file():
            messagebox.showerror("패쳐 데이터 확인", "TranslationData/catalog.json을 찾을 수 없습니다.")
            return

        target = self.folder / "Output"
        if target.exists():
            target = self.folder / ("Output-" + datetime.now().strftime("%Y%m%d-%H%M%S"))

        self.generate.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.status.set("선택한 TMR 프로필을 검사하고 덮어쓰기용 Output을 생성하고 있습니다.")

        def run():
            try:
                report = build_output(root, base, data, target)
                self.events.put(("done", target, report))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=run, daemon=True).start()

    def poll(self):
        try:
            event = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.generate.configure(state="normal")
            if event[0] == "error":
                self.status.set("생성에 실패했습니다. TMR 설치 폴더는 변경하지 않았습니다.")
                messagebox.showerror("생성 실패", event[1])
            else:
                _, target, report = event
                self.output = target
                exact = sum(x["status"] == "exact_payload" for x in report["plugins"])
                fallback = sum(x["status"] in {"updated_fallback", "new_inherited"}
                               for x in report["plugins"])
                skipped = sum(
                    x["status"] in {"known_no_translation_needed", "updated_no_match", "new_no_match", "excluded"}
                    for x in report["plugins"])
                self.status.set(
                    f"완료: 빠른 적용 {exact} · 사전 번역 {fallback} · "
                    f"번역 불필요/대응 없음 {skipped}\n"
                    f"MCM {len(report['mcm'])}개 · Interface {len(report['interface'])}개\n"
                    f"{target}\n"
                    "Output 안의 mods(필요 시 overwrite) 내용을 TMR MO2 루트에 복사하고 "
                    f"기존 파일 덮어쓰기를 허용하세요. 그 다음 MO2에서 '{BASE_MOD}'를 체크하세요."
                )
                self.open_button.configure(state="normal")
        self.window.after(150, self.poll)

    def open_output(self):
        if self.output and self.output.is_dir():
            os.startfile(self.output)


def packaged_self_test(mo2_root: str) -> int:
    # Initialize Tcl without opening a window; packaging can omit its resources
    # even when importing tkinter succeeds.
    tk.Tcl().eval("info patchlevel")
    folder = program_folder()
    data = folder / "TranslationData"
    base = folder / BUNDLED_BASE
    if not (data / "catalog.json").is_file():
        raise FileNotFoundError("TranslationData/catalog.json")
    if not (data / "Backend/TmrPluginTranslator.exe").is_file():
        raise FileNotFoundError("TranslationData/Backend/TmrPluginTranslator.exe")
    if not (base / "Strings").is_dir() or not (base / "Interface").is_dir():
        raise FileNotFoundError(BUNDLED_BASE)
    with tempfile.TemporaryDirectory(prefix="tmrkr-selftest-") as tmp:
        output = Path(tmp) / "Output"
        report = build_output(Path(mo2_root), base, data, output)
        if not output.is_dir() or not report["plugins"]:
            raise RuntimeError("Output self-test failed")
        if not (output / "mods" / BASE_MOD / "Strings").is_dir():
            raise RuntimeError("FO4 KOREAN MO2 mod was not generated")
        if not any(x["status"] == "exact_payload"
                   or x.get("detail", {}).get("text_roundtrip_verified") is True
                   for x in report["plugins"]):
            raise RuntimeError("No verified plugin translation was generated")
        entries = {row["name"].casefold(): row for row in
                   json.loads((data / "catalog.json").read_text(encoding="utf-8-sig"))["plugins"]}
        for item in report["plugins"]:
            if item["status"] == "exact_payload":
                entry = entries[item["plugin"].casefold()]
                if (entry.get("payload_encoding") != "utf-8"
                        or entry.get("text_roundtrip_verified") is not True):
                    raise RuntimeError("Unverified exact payload was used")
        if report["base_files"] < 1:
            raise RuntimeError("Bundled Korean resource path was not exercised")
        for item in report["interface"]:
            provider = item["provider"]
            target_root = (output / "overwrite" if provider == "MO2:overwrite"
                           else output / "mods" / (BASE_MOD if provider == "game:Data" else provider))
            translation = target_root / item["path"]
            raw = translation.read_bytes()
            if not raw.startswith(b"\xff\xfe"):
                raise RuntimeError(f"Interface translation is not UTF-16 LE: {item['path']}")
            raw[2:].decode("utf-16-le", errors="strict")
        generated_names = {p.name.casefold() for p in output.rglob("*") if p.is_file()}
        for excluded in ("ptrfo4001_t60pistol.esl", "ptrfo4002_vangraff.esl"):
            if excluded in generated_names:
                raise RuntimeError(f"Excluded plugin was generated: {excluded}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        try:
            result = packaged_self_test(sys.argv[2])
        except Exception:
            import traceback
            (program_folder() / "self-test-error.log").write_text(traceback.format_exc(), encoding="utf-8")
            raise SystemExit(1)
        raise SystemExit(result)
    window = tk.Tk()
    App(window)
    window.mainloop()
