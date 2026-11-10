"""han-laser: สร้างไฟล์ serial number (.txt) ให้ Han's Laser Marking Control Software V4.0.1
อ่านทีละบรรทัด (1 บรรทัด = 1 ชิ้นที่มาร์ก) และเปิดซอฟต์แวร์พร้อม template

ใช้ได้กับ Python 3.9+ ไม่ต้องติดตั้ง package เพิ่ม

    python han_laser.py generate --count 100 --lot LOT001
    python han_laser.py launch
    python han_laser.py run --count 100 --lot LOT001     (generate + launch)
    python han_laser.py status
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

DEFAULT_CONFIG = "config.json"

# seq_reset -> รูปแบบ strftime ของรอบ (never = รอบเดียวตลอด)
PERIOD_FORMATS = {"daily": "%Y-%m-%d", "monthly": "%Y-%m", "never": "all"}


# ---------------------------------------------------------------- config

@dataclass
class Config:
    marking_exe: str
    template: str
    serial_txt: str
    serial_format: str = "{prefix}{date:%y%m}{seq:04d}"
    prefix: str = "CB"
    seq_start: int = 1
    seq_max: int = 9999
    seq_reset: str = "monthly"        # "daily" | "monthly" | "never"
    txt_encoding: str = "utf-8"
    txt_newline: str = "\r\n"
    launch_args: list = field(default_factory=lambda: ["{template}"])
    state_file: str = "data/state.json"
    history_csv: str = "data/history.csv"
    archive_dir: str = "data/archive"

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        raw = {k: v for k, v in raw.items() if not k.startswith("_")}  # "_comment" keys
        unknown = set(raw) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"config มี key ที่ไม่รู้จัก: {sorted(unknown)}")
        cfg = cls(**raw)
        # path ที่เป็น relative ให้อิงจากโฟลเดอร์ของ config
        base = path.resolve().parent
        for name in ("serial_txt", "state_file", "history_csv", "archive_dir", "template"):
            p = Path(getattr(cfg, name))
            if not p.is_absolute():
                setattr(cfg, name, str(base / p))
        if cfg.seq_reset not in PERIOD_FORMATS:
            raise ValueError(f"seq_reset ต้องเป็นหนึ่งใน {list(PERIOD_FORMATS)}")
        return cfg


# ---------------------------------------------------------------- helpers

def atomic_write_text(path: Path, text: str, encoding: str) -> None:
    """เขียนลงไฟล์ชั่วคราวแล้ว rename ทับ กันซอฟต์แวร์มาร์กอ่านเจอไฟล์ที่เขียนไม่เสร็จ"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def load_state(path: Path) -> dict:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(path: Path, state: dict) -> None:
    atomic_write_text(path, json.dumps(state, indent=2, ensure_ascii=False), "utf-8")


def load_history_serials(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with open(path, encoding="utf-8", newline="") as f:
        return {row["serial"] for row in csv.DictReader(f)}


def append_history(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["generated_at", "lot", "serial"])
        if new:
            w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------- core

def period_key(cfg: Config, now: datetime) -> str:
    """รอบของเลขลำดับ เปลี่ยนรอบเมื่อไรเลขลำดับเริ่มที่ seq_start ใหม่"""
    return now.strftime(PERIOD_FORMATS[cfg.seq_reset])


def next_seq(cfg: Config, state: dict, now: datetime) -> int:
    """เลขลำดับตัวถัดไป (ยังไม่บันทึก)"""
    if not state or state.get("period") != period_key(cfg, now):
        return cfg.seq_start
    return state["last_seq"] + 1


def make_serials(cfg: Config, count: int, start_seq: int, now: datetime) -> list[str]:
    end = start_seq + count - 1
    if end > cfg.seq_max:
        raise ValueError(
            f"เลขลำดับเกิน seq_max ({cfg.seq_max}): ขอ {start_seq}..{end} "
            f"เหลือใช้ได้อีก {max(cfg.seq_max - start_seq + 1, 0)} ตัว"
        )
    return [
        cfg.serial_format.format(prefix=cfg.prefix, date=now, seq=s)
        for s in range(start_seq, end + 1)
    ]


def generate(cfg: Config, count: int, lot: str = "", now: datetime | None = None) -> list[str]:
    if count < 1:
        raise ValueError("count ต้องมากกว่า 0")
    now = now or datetime.now()
    state_path = Path(cfg.state_file)
    state = load_state(state_path)

    start = next_seq(cfg, state, now)
    serials = make_serials(cfg, count, start, now)

    dup_in_batch = len(set(serials)) != len(serials)
    dup_history = load_history_serials(Path(cfg.history_csv)) & set(serials)
    if dup_in_batch or dup_history:
        sample = sorted(dup_history)[:5]
        raise ValueError(
            "พบ serial ซ้ำ ตรวจ serial_format ว่ามี {seq} อยู่ด้วย"
            + (f" (ซ้ำกับที่เคยสร้าง: {sample})" if sample else "")
        )

    txt = Path(cfg.serial_txt)
    if txt.exists():
        # ไฟล์เดิมอาจยังมาร์กไม่หมด เก็บสำรองไว้ก่อนเขียนทับ
        archive = Path(cfg.archive_dir)
        archive.mkdir(parents=True, exist_ok=True)
        shutil.copy2(txt, archive / f"{txt.stem}_{now:%Y%m%d_%H%M%S}{txt.suffix}")

    text = cfg.txt_newline.join(serials) + cfg.txt_newline
    atomic_write_text(txt, text, cfg.txt_encoding)

    stamp = now.isoformat(timespec="seconds")
    append_history(Path(cfg.history_csv),
                   [{"generated_at": stamp, "lot": lot, "serial": s} for s in serials])
    save_state(state_path, {"period": period_key(cfg, now), "last_seq": start + count - 1,
                            "last_lot": lot, "updated_at": stamp})
    return serials


def launch(cfg: Config) -> subprocess.Popen:
    exe = Path(cfg.marking_exe)
    if not exe.exists():
        raise FileNotFoundError(f"ไม่พบโปรแกรมมาร์ก: {exe}")
    if not Path(cfg.template).exists():
        raise FileNotFoundError(f"ไม่พบ template: {cfg.template}")
    args = [a.format(template=cfg.template, serial_txt=cfg.serial_txt) for a in cfg.launch_args]
    return subprocess.Popen([str(exe), *args], cwd=str(exe.parent))


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="han_laser", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--config", default=DEFAULT_CONFIG)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("generate", "run"):
        p = sub.add_parser(name, help="สร้างไฟล์ serial" + (" แล้วเปิดโปรแกรมมาร์ก" if name == "run" else ""))
        p.add_argument("-n", "--count", type=int, required=True)
        p.add_argument("--lot", default="")
    sub.add_parser("launch", help="เปิดโปรแกรมมาร์กพร้อม template")
    sub.add_parser("status", help="แสดงเลขล่าสุดและตัวถัดไป")
    args = ap.parse_args(argv)

    try:
        cfg = Config.load(args.config)
        if args.cmd in ("generate", "run"):
            serials = generate(cfg, args.count, args.lot)
            print(f"สร้าง {len(serials)} serial: {serials[0]} .. {serials[-1]}")
            print(f"เขียนลง {cfg.serial_txt}")
        if args.cmd in ("launch", "run"):
            launch(cfg)
            print(f"เปิด {cfg.marking_exe} พร้อม {cfg.template}")
        if args.cmd == "status":
            state = load_state(Path(cfg.state_file))
            now = datetime.now()
            seq = next_seq(cfg, state, now)
            print("state:", json.dumps(state, ensure_ascii=False) if state else "(ยังไม่เคยสร้าง)")
            print("serial ตัวถัดไป:", cfg.serial_format.format(prefix=cfg.prefix, date=now, seq=seq))
    except (ValueError, FileNotFoundError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
