"""han-laser: สร้างไฟล์ serial number (.txt) ให้ Han's Laser Marking Control Software V4.0.1
อ่านทีละบรรทัด ("Obtained from files (Each Line)": 1 บรรทัด = 1 ชิ้นที่มาร์ก) และเปิด template (.hs)

แต่ละ product มีรูปแบบ serial, template และไฟล์ .txt ของตัวเอง ประวัติเก็บใน SQLite
core นี้ใช้ได้กับ Python 3.9+ ไม่ต้องติดตั้ง package เพิ่ม (UI ใช้ PySide6 แยกไฟล์)

    python han_laser.py status
    python han_laser.py -p ceramic_box generate -n 100 --lot LOT001
    python han_laser.py -p lid launch
    python han_laser.py -p lid run -n 100 --lot LOT001     (generate + launch)
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

from store import Store

DEFAULT_CONFIG = "config.json"

# seq_reset -> รูปแบบ strftime ของรอบ (never = รอบเดียวตลอด)
PERIOD_FORMATS = {"daily": "%Y-%m-%d", "monthly": "%Y-%m", "never": "all"}
PRODUCT_ID_RE = re.compile(r"^[a-z0-9_]+$")


# ---------------------------------------------------------------- config

def _check_keys(cls, raw: dict, where: str) -> dict:
    raw = {k: v for k, v in raw.items() if not k.startswith("_")}  # "_comment" keys
    unknown = set(raw) - {f.name for f in fields(cls)}
    if unknown:
        raise ValueError(f"{where}: มี key ที่ไม่รู้จัก {sorted(unknown)}")
    return raw


@dataclass
class Product:
    id: str
    name: str
    template: str                     # ไฟล์ .hs (HS.Document)
    serial_txt: str
    prefix: str = ""
    serial_format: str = "{prefix}{date:%y%m}{seq:04d}"
    seq_reset: str = "monthly"        # "daily" | "monthly" | "never"
    seq_start: int = 1
    seq_max: int = 9999
    marking_exe: str = ""             # ว่าง = เปิด .hs ด้วยโปรแกรมที่ Windows ผูกไว้
    launch_args: list = field(default_factory=lambda: ["{template}"])
    image: str = ""                   # รูปตัวอย่างตำแหน่งที่มาร์ก

    def validate(self) -> None:
        p = f"product '{self.id}'"
        if not PRODUCT_ID_RE.match(self.id):
            raise ValueError(f"{p}: id ใช้ได้แค่ a-z 0-9 _")
        if not self.name.strip():
            raise ValueError(f"{p}: ต้องมีชื่อ")
        if self.seq_reset not in PERIOD_FORMATS:
            raise ValueError(f"{p}: seq_reset ต้องเป็นหนึ่งใน {list(PERIOD_FORMATS)}")
        if not (0 <= self.seq_start <= self.seq_max):
            raise ValueError(f"{p}: ต้องเป็น 0 <= seq_start <= seq_max")
        if "{seq" not in self.serial_format:
            raise ValueError(f"{p}: serial_format ต้องมี {{seq}} เช่น {{seq:04d}}")
        try:
            self.format_serial(datetime(2026, 1, 1), self.seq_start)
        except (KeyError, ValueError, IndexError) as e:
            raise ValueError(f"{p}: serial_format ไม่ถูกต้อง ({e!r})") from None
        if not self.template.strip() or not self.serial_txt.strip():
            raise ValueError(f"{p}: ต้องระบุ template และ serial_txt")

    def format_serial(self, now: datetime, seq: int) -> str:
        return self.serial_format.format(prefix=self.prefix, date=now, seq=seq)

    def period_key(self, now: datetime) -> str:
        """รอบของเลขลำดับ เปลี่ยนรอบเมื่อไรเลขลำดับเริ่มที่ seq_start ใหม่"""
        return now.strftime(PERIOD_FORMATS[self.seq_reset])


@dataclass
class AppConfig:
    products: dict = field(default_factory=dict)     # id -> Product
    db_file: str = "data/han_laser.db"
    archive_dir: str = "data/archive"
    txt_encoding: str = "utf-8"
    txt_newline: str = "\r\n"
    last_product: str = ""
    engineer_password: str = ""       # hash (pbkdf2) ว่าง = ยังไม่ได้ตั้ง
    path: Path | None = field(default=None, repr=False, compare=False)

    # path ใน config เก็บตามที่เขียน (relative ได้) แล้วค่อย resolve ตอนใช้ จะได้ save กลับเหมือนเดิม
    def abspath(self, p: str) -> Path:
        q = Path(p)
        if q.is_absolute() or self.path is None:
            return q
        return self.path.resolve().parent / q

    def product(self, product_id: str | None = None) -> Product:
        pid = product_id or self.last_product or next(iter(self.products), "")
        if pid not in self.products:
            raise ValueError(f"ไม่พบ product '{pid}' (มี: {', '.join(self.products) or '-'})")
        return self.products[pid]

    def validate(self) -> None:
        if not self.products:
            raise ValueError("config ต้องมีอย่างน้อย 1 product")
        for pid, prod in self.products.items():
            if pid != prod.id:
                raise ValueError(f"product key '{pid}' ไม่ตรงกับ id '{prod.id}'")
            prod.validate()
        txts = [str(self.abspath(p.serial_txt)).lower() for p in self.products.values()]
        if len(set(txts)) != len(txts):
            raise ValueError("แต่ละ product ต้องใช้ไฟล์ serial_txt คนละไฟล์")
        try:
            "".encode(self.txt_encoding)
        except LookupError:
            raise ValueError(f"txt_encoding ไม่ถูกต้อง: {self.txt_encoding}") from None

    @classmethod
    def from_dict(cls, raw: dict, path: Path | None = None) -> "AppConfig":
        raw = _check_keys(cls, raw, "config")
        raw.pop("path", None)
        products = {}
        for pid, praw in (raw.pop("products", None) or {}).items():
            praw = _check_keys(Product, dict(praw), f"product '{pid}'")
            praw.setdefault("id", pid)
            products[pid] = Product(**praw)
        cfg = cls(products=products, path=path, **raw)
        cfg.validate()
        return cfg

    @classmethod
    def load(cls, path: str | Path) -> "AppConfig":
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f), path)

    def to_dict(self) -> dict:
        d = {f.name: getattr(self, f.name) for f in fields(self) if f.name not in ("products", "path")}
        d["products"] = {pid: {k: v for k, v in asdict(p).items() if k != "id"}
                         for pid, p in self.products.items()}
        return d

    def save(self, path: str | Path | None = None) -> None:
        self.validate()
        target = Path(path) if path else self.path
        if target is None:
            raise ValueError("ไม่ได้ระบุ path ของ config")
        atomic_write_text(target, json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n", "utf-8")
        self.path = target


# ---------------------------------------------------------------- engineer password

PBKDF2_ITER = 200_000


def hash_password(password: str) -> str:
    """เก็บเป็น hash ไม่เก็บรหัสจริง: pbkdf2_sha256$iter$salt$hash"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITER)
    return f"pbkdf2_sha256${PBKDF2_ITER}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, it, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(it))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), digest)


# ---------------------------------------------------------------- helpers

def atomic_write_text(path: Path, text: str, encoding: str) -> None:
    """เขียนลงไฟล์ชั่วคราวแล้ว rename ทับ กันซอฟต์แวร์มาร์กอ่านเจอไฟล์ที่เขียนไม่เสร็จ"""
    path = Path(path)
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


def open_store(app: AppConfig) -> Store:
    return Store(app.abspath(app.db_file))


# ---------------------------------------------------------------- core

@dataclass
class Batch:
    id: int
    product: str
    lot: str
    serials: list
    txt_path: str
    created_at: str


def ensure_txt_dir(app: AppConfig, prod: Product) -> Path:
    """โฟลเดอร์ของไฟล์ .txt ต้องมีอยู่แล้ว (สร้างให้เฉพาะเมื่ออยู่ในโฟลเดอร์โปรเจกต์)"""
    txt = app.abspath(prod.serial_txt)
    parent = txt.parent
    if parent.is_dir():
        return txt
    base = app.path.resolve().parent if app.path else None
    if base and (parent.resolve() == base or base in parent.resolve().parents):
        parent.mkdir(parents=True, exist_ok=True)
        return txt
    raise ValueError(
        f"ไม่พบโฟลเดอร์ (หรือไม่มีสิทธิ์เข้าถึง): {parent}\n"
        f"แก้ช่อง 'ไฟล์ serial .txt' ของ {prod.name} ในหน้า Settings ให้อยู่ในโฟลเดอร์ที่มีอยู่จริง"
    )


def next_seq(store: Store, prod: Product, now: datetime) -> int:
    """เลขลำดับตัวถัดไป (ยังไม่บันทึก)"""
    last = store.last_seq(prod.id, prod.period_key(now))
    return prod.seq_start if last is None else last + 1


def make_serials(prod: Product, count: int, start_seq: int, now: datetime) -> list[str]:
    if count < 1:
        raise ValueError("จำนวนต้องมากกว่า 0")
    end = start_seq + count - 1
    if end > prod.seq_max:
        raise ValueError(
            f"เลขลำดับเกิน seq_max ({prod.seq_max}): ขอ {start_seq}..{end} "
            f"เหลือใช้ได้อีก {max(prod.seq_max - start_seq + 1, 0)} ตัว"
        )
    return [prod.format_serial(now, s) for s in range(start_seq, end + 1)]


def preview(app: AppConfig, product_id: str | None, count: int,
            now: datetime | None = None, store: Store | None = None) -> list[str]:
    """serial ที่จะได้ถ้า generate ตอนนี้ (ไม่บันทึกอะไร)"""
    now = now or datetime.now()
    prod = app.product(product_id)
    own = store is None
    store = store or open_store(app)
    try:
        return make_serials(prod, count, next_seq(store, prod, now), now)
    finally:
        if own:
            store.close()


def generate(app: AppConfig, product_id: str | None, count: int, lot: str = "",
             now: datetime | None = None, store: Store | None = None) -> Batch:
    now = now or datetime.now()
    prod = app.product(product_id)
    txt = ensure_txt_dir(app, prod)
    own = store is None
    store = store or open_store(app)
    try:
        with store.transaction():
            start = next_seq(store, prod, now)
            serials = make_serials(prod, count, start, now)
            if len(set(serials)) != len(serials):
                raise ValueError("serial ในชุดนี้ซ้ำกันเอง ตรวจ serial_format ว่ามี {seq} อยู่ด้วย")
            dup = store.existing(serials)
            if dup:
                raise ValueError(f"พบ serial ซ้ำกับที่เคยสร้าง: {dup[:5]} ตรวจ serial_format/seq_reset")

            stamp = now.isoformat(timespec="seconds")
            try:
                batch_id = store.add_batch(prod.id, lot, serials, list(range(start, start + count)),
                                           prod.period_key(now), str(txt), stamp)
            except sqlite3.IntegrityError as e:
                raise ValueError(f"บันทึกไม่ได้ serial ซ้ำ ({e})") from None

            if txt.exists():
                # ไฟล์เดิมอาจยังมาร์กไม่หมด เก็บสำรองไว้ก่อนเขียนทับ
                archive = app.abspath(app.archive_dir)
                archive.mkdir(parents=True, exist_ok=True)
                shutil.copy2(txt, archive / f"{txt.stem}_{now:%Y%m%d_%H%M%S}{txt.suffix}")
            # เขียนไฟล์เป็นขั้นสุดท้าย ถ้าเขียนไม่ได้ transaction จะ rollback ไม่มีอะไรถูกบันทึก
            atomic_write_text(txt, app.txt_newline.join(serials) + app.txt_newline, app.txt_encoding)
        return Batch(batch_id, prod.id, lot, serials, str(txt), stamp)
    finally:
        if own:
            store.close()


def associated_exe(ext: str) -> str | None:
    """โปรแกรมที่ Windows ผูกไว้กับนามสกุลไฟล์ (เช่น .hs -> HLM.exe) ไม่พบหรือไม่ใช่ Windows -> None"""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes
    ASSOCSTR_EXECUTABLE = 2
    size = wintypes.DWORD(1024)
    buf = ctypes.create_unicode_buffer(size.value)
    hr = ctypes.windll.shlwapi.AssocQueryStringW(0, ASSOCSTR_EXECUTABLE, ext, "open", buf, ctypes.byref(size))
    return buf.value if hr == 0 and buf.value else None


def is_running(image_name: str) -> bool:
    """มีโปรเซสชื่อนี้ (เช่น HLM.exe) รันอยู่ไหม (Windows เท่านั้น)"""
    if sys.platform != "win32":
        return False
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/NH"],
                         capture_output=True, text=True, creationflags=0x08000000).stdout  # CREATE_NO_WINDOW
    return image_name.lower() in out.lower()


def launch(app: AppConfig, product_id: str | None = None) -> str:
    """เปิด template ของ product คืนค่าข้อความบอกว่าเปิดด้วยอะไร

    เปิด HLM.exe ตรง ๆ โดยให้ working directory เป็นโฟลเดอร์ของ HLM.exe
    (ถ้าเปิดจากโฟลเดอร์อื่น HLM.exe crash ตอนโหลด template)
    """
    prod = app.product(product_id)
    template = app.abspath(prod.template).resolve()
    if not template.exists():
        raise FileNotFoundError(f"ไม่พบ template: {template}")
    exe_s = prod.marking_exe or associated_exe(template.suffix)
    if not exe_s:
        raise OSError(f"ไม่รู้ว่าจะเปิด {template.suffix} ด้วยโปรแกรมอะไร "
                      f"ใส่ path ของ HLM.exe ในช่อง 'โปรแกรมมาร์ก' หน้า Settings")
    exe = Path(exe_s)
    if not exe.exists():
        raise FileNotFoundError(f"ไม่พบโปรแกรมมาร์ก: {exe}")
    if is_running(exe.name):
        raise OSError(f"{exe.name} เปิดอยู่แล้ว\n"
                      f"ให้เปิด template จากเมนู File > Open ในโปรแกรมที่เปิดอยู่ หรือปิดโปรแกรมก่อนแล้วกดใหม่")
    txt = app.abspath(prod.serial_txt).resolve()
    args = [a.format(template=template, serial_txt=txt) for a in prod.launch_args]
    subprocess.Popen([str(exe), *args], cwd=str(exe.parent))
    return str(exe)


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="han_laser", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--config", default=DEFAULT_CONFIG)
    ap.add_argument("-p", "--product", default=None, help="id ของ product (ค่าเริ่มต้น: last_product)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("generate", "run"):
        p = sub.add_parser(name, help="สร้างไฟล์ serial" + (" แล้วเปิด template" if name == "run" else ""))
        p.add_argument("-n", "--count", type=int, required=True)
        p.add_argument("--lot", default="")
    sub.add_parser("launch", help="เปิด template ของ product")
    sub.add_parser("status", help="แสดง serial ตัวถัดไปของทุก product")
    args = ap.parse_args(argv)

    try:
        app = AppConfig.load(args.config)
        if args.cmd in ("generate", "run"):
            b = generate(app, args.product, args.count, args.lot)
            print(f"[{b.product}] สร้าง {len(b.serials)} serial: {b.serials[0]} .. {b.serials[-1]}")
            print(f"เขียนลง {b.txt_path}")
        if args.cmd in ("launch", "run"):
            how = launch(app, args.product)
            print(f"เปิด template ของ {app.product(args.product).id} ด้วย {how}")
        if args.cmd == "status":
            with open_store(app) as store:
                for prod in app.products.values():
                    nxt = preview(app, prod.id, 1, store=store)[0]
                    print(f"{prod.id:15} {prod.name:20} ตัวถัดไป: {nxt}")
    except (ValueError, FileNotFoundError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
