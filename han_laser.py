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


# ค่าที่ map เข้า parameter ของ FITS log ได้
FITS_SOURCES = {
    "serial": "Serial (โหมด Engineer มี _test ต่อท้าย)",
    "workorder": "Workorder",
    "wo_pn": "WO PN (ตั้งคู่กับ Workorder ใน Settings)",
    "iqr": "iQR code",
    "result": "ผล (PASS)",
    "failure_code": "Failure code (ว่างเมื่อ PASS)",
    "en": "EN",
    "shift": "Shift",
    "product": "Product id",
    "blank": "ค่าว่าง",
    "-": "ส่งเครื่องหมาย - ตรง ๆ",
    "NA": "ส่งข้อความ NA ตรง ๆ",
}
FITS_CONSTANTS = {"blank": "", "-": "-", "NA": "NA"}   # source ที่เป็นค่าคงที่


@dataclass
class FitsSettings:
    """ค่าการส่ง FITS (URL/รหัสไม่อยู่ที่นี่ อ่านจาก environment FITS_* ตอนส่ง)"""
    enabled: bool = False
    model: str = ""
    operation: str = ""
    parameters: list = field(default_factory=list)   # [["<parameter name>", "<source>"], ...]
    fsp: str = ","
    timeout: float = 20.0

    def validate(self) -> None:
        if self.fsp not in (",", ";", ":", "|"):
            raise ValueError("FITS: ตัวคั่น (fsp) ต้องเป็น , ; : หรือ |")
        if not (isinstance(self.timeout, (int, float)) and 1 <= self.timeout <= 120):
            raise ValueError("FITS: timeout ต้องอยู่ระหว่าง 1-120 วินาที")
        if not isinstance(self.parameters, list):
            raise ValueError("FITS: parameters ต้องเป็นรายการ")
        for item in self.parameters:
            if not (isinstance(item, (list, tuple)) and len(item) == 2 and all(isinstance(x, str) for x in item)):
                raise ValueError(f"FITS: parameter ต้องเป็นคู่ [ชื่อ, ค่า] ได้ {item!r}")
            name, src = item
            if not name.strip() or self.fsp in name:
                raise ValueError(f"FITS: ชื่อ parameter '{name}' ว่างหรือมีตัวคั่น '{self.fsp}'")
            if src not in FITS_SOURCES:
                raise ValueError(f"FITS: parameter '{name}' ใช้ค่า '{src}' ไม่ได้ (ใช้ได้: {', '.join(FITS_SOURCES)})")
        if self.enabled:
            if not self.model.strip() or not self.operation.strip():
                raise ValueError("FITS: เปิดใช้แล้วต้องระบุ model และ operation")
            if not self.parameters:
                raise ValueError("FITS: เปิดใช้แล้วต้องมี parameter อย่างน้อย 1 ตัว")


@dataclass
class CameraSettings:
    """โหมดกล้อง Dino-Lite ในหน้า Verify (อ่าน DataMatrix ต่อเนื่อง)"""
    index: str = "auto"        # "auto" = กล้องตัวแรกที่ชื่อมี Dino หรือเลข index (0, 1, ...)
    device: str = ""           # DevicePath ของกล้องที่เลือก (ผูกกับ USB port) มาก่อน index; ว่าง = ใช้ index
    device_name: str = ""      # ชื่อกล้องที่เลือก (ไว้แสดงผล)
    serial_regex: str = ""     # code ไหนคือ serial; ว่าง = ขึ้นต้นด้วย prefix ของ product
    width: int = 1280
    height: int = 1024

    def validate(self) -> None:
        if self.index != "auto" and not str(self.index).isdigit():
            raise ValueError(f"กล้อง: index ต้องเป็น auto หรือตัวเลข (ได้ '{self.index}')")
        try:
            re.compile(self.serial_regex)
        except re.error as e:
            raise ValueError(f"กล้อง: serial regex ไม่ถูกต้อง ({e})") from None
        if not (isinstance(self.width, int) and isinstance(self.height, int) and self.width > 0 and self.height > 0):
            raise ValueError("กล้อง: width/height ต้องเป็นจำนวนเต็มบวก")


INPUT_MODES = ("usb", "camera")


@dataclass
class AppConfig:
    products: dict = field(default_factory=dict)     # id -> Product
    db_file: str = "data/han_laser.db"
    archive_dir: str = "data/archive"
    txt_encoding: str = "utf-8"
    txt_newline: str = "\r\n"
    last_product: str = ""
    engineer_password: str = ""       # hash (pbkdf2) ว่าง = ยังไม่ได้ตั้ง
    operators: list = field(default_factory=list)          # EN ให้เลือกในหน้า Verify
    shifts: list = field(default_factory=lambda: ["A", "B", "C"])
    workorders: list = field(default_factory=list)         # = Lot ตอน Generate
    iqr_codes: list = field(default_factory=list)          # iQR ให้เลือกในหน้า Verify (บันทึกคู่กับ serial)
    workorder_pn: dict = field(default_factory=dict)       # Workorder -> WO PN (ส่ง FITS)
    fits: FitsSettings = field(default_factory=FitsSettings)
    input_mode: str = "usb"           # หน้า Verify รับค่าจาก "usb" (เครื่องสแกน) หรือ "camera" (Dino-Lite)
    camera: CameraSettings = field(default_factory=CameraSettings)
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
        for name in ("operators", "shifts", "workorders", "iqr_codes"):
            v = getattr(self, name)
            if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
                raise ValueError(f"{name} ต้องเป็นรายการข้อความ (ไม่ว่าง)")
        if not (isinstance(self.workorder_pn, dict)
                and all(isinstance(k, str) and isinstance(v, str) for k, v in self.workorder_pn.items())):
            raise ValueError("workorder_pn ต้องเป็น {workorder: pn}")
        self.fits.validate()
        if self.input_mode not in INPUT_MODES:
            raise ValueError(f"input_mode ต้องเป็น {' หรือ '.join(INPUT_MODES)}")
        self.camera.validate()
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
        fits = FitsSettings(**_check_keys(FitsSettings, dict(raw.pop("fits", None) or {}), "fits"))
        camera = CameraSettings(**_check_keys(CameraSettings, dict(raw.pop("camera", None) or {}), "camera"))
        cfg = cls(products=products, fits=fits, camera=camera, path=path, **raw)
        cfg.validate()
        return cfg

    @classmethod
    def load(cls, path: str | Path) -> "AppConfig":
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f), path)

    def to_dict(self) -> dict:
        d = {f.name: getattr(self, f.name) for f in fields(self) if f.name not in ("products", "path", "fits", "camera")}
        d["fits"] = asdict(self.fits)
        d["camera"] = asdict(self.camera)
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


@dataclass
class VerifyResult:
    ok: bool
    serial: str          # serial ที่บันทึก/ส่ง FITS (โหมด test มี _test ต่อท้าย)
    reason: str          # '' | EMPTY | NOT_FOUND | WRONG_WORKORDER | DUPLICATE | TEST_SERIAL
    message: str
    product: str = ""
    id: int | None = None
    pending: bool = False   # ผ่านในเครื่องแล้ว รอผล FITS
    test: bool = False


TEST_SUFFIX = "_test"


def normalize_code(raw: str) -> str:
    """ค่าที่สแกนได้ = serial ตรง ๆ ตัดช่องว่าง/ขึ้นบรรทัด และทำเป็นตัวพิมพ์ใหญ่"""
    return "".join(raw.split()).upper()


def default_serial_regex(app: AppConfig) -> str:
    """regex เริ่มต้นของโหมดกล้อง: ขึ้นต้นด้วย prefix ของ product ใด product หนึ่ง"""
    prefixes = sorted({p.prefix.upper() for p in app.products.values() if p.prefix}, key=len, reverse=True)
    return "^(?:" + "|".join(re.escape(x) for x in prefixes) + ")" if prefixes else ""


def serial_pattern(app: AppConfig) -> re.Pattern:
    return re.compile(app.camera.serial_regex or default_serial_regex(app), re.IGNORECASE)


def pick_serial(pattern: re.Pattern, codes: list[str]) -> str | None:
    """เลือก code แรกที่ตรง pattern (ชิ้นงานอาจมีหลาย code) คืน serial ที่ normalize แล้ว หรือ None"""
    for raw in codes:
        code = normalize_code(raw)
        if code and pattern.search(code):
            return code
    return None


def verify(store: Store, raw_code: str, en: str, shift: str, workorder: str,
           now: datetime | None = None, iqr: str = "", test: bool = False,
           pending: bool = False) -> VerifyResult:
    """ตรวจ serial หลังมาร์ก: ต้องเคย generate, อยู่ใน workorder ที่เลือก และยังไม่เคย PASS
    บันทึกทุกครั้ง (ทั้ง PASS และ FAIL) ยกเว้นค่าว่าง

    test=True (โหมด Engineer): ต่อ _test ท้าย serial ให้เอง ไม่เช็กซ้ำ และไม่นับเป็นของจริง
    pending=True: ผ่านในเครื่องแล้วบันทึกเป็น PENDING รอ finish_fits() หลังส่ง FITS
    """
    if not (en and shift and workorder):
        raise ValueError("เลือก EN, Shift และ Workorder ก่อนสแกน")
    code = normalize_code(raw_code)
    if not code:
        return VerifyResult(False, "", "EMPTY", "ไม่มีข้อมูลจากการสแกน")
    suffix = TEST_SUFFIX.upper()
    base = code[:-len(suffix)] if code.endswith(suffix) else code
    serial = base + TEST_SUFFIX if test else code
    now = now or datetime.now()
    stamp = now.isoformat(timespec="seconds")
    with store.transaction():
        info = store.serial_info(base)
        product = info["product"] if info else ""
        if not test and code.endswith(suffix):
            reason, msg = "TEST_SERIAL", "SN ที่ลงท้าย _test ใช้ได้เฉพาะโหมด Engineer"
        elif info is None:
            reason, msg = "NOT_FOUND", f"ไม่พบ serial {base} ในระบบ (ไม่เคย generate)"
        elif info["lot"] != workorder:
            reason, msg = "WRONG_WORKORDER", f"serial นี้อยู่ใน Workorder {info['lot'] or '-'} ไม่ใช่ {workorder}"
        else:
            prev = None if test else store.first_pass(base)
            if prev is not None:
                reason = "DUPLICATE"
                msg = f"serial นี้ verify ผ่านไปแล้วเมื่อ {prev['scanned_at'].replace('T', ' ')} (EN {prev['en']})"
            else:
                reason, msg = "", "ถูกต้อง"
        ok = reason == ""
        result = ("PENDING" if pending else "PASS") if ok else "FAIL"
        vid = store.add_verification(stamp, raw_code, serial, product, en, shift, workorder,
                                     result, reason, iqr, test)
    return VerifyResult(ok and not pending, serial, reason, msg, product, vid, ok and pending, test)


# ---------------------------------------------------------------- FITS (ผ่าน wheel fabrinet_fits_client)

class FitsSetupError(ValueError):
    """ตั้งค่า FITS ไม่ครบ (ยังไม่ส่งอะไรออกไป)"""


FITS_ENV = {"url": "FITS_URL", "project_id": "FITS_PROJECT_ID", "user_name": "FITS_USER",
            "user_password": "FITS_PASSWORD", "revision": "FITS_REVISION"}


ENV_FILE = ".env"


def load_env_file(path: str | Path, environ=None, override: bool = True) -> list[str]:
    """อ่านไฟล์ .env (KEY=VALUE บรรทัดละตัว) ใส่ environment คืนรายชื่อ key ที่ตั้ง (ไม่คืนค่า)

    รองรับ: บรรทัดว่าง, # comment, 'export KEY=...', ค่าในเครื่องหมาย "..." หรือ '...'
    override=True: ค่าใน .env ชนะตัวแปรที่ตั้งไว้ใน Windows แล้ว
    """
    env = os.environ if environ is None else environ
    path = Path(path)
    if not path.is_file():
        return []
    keys = []
    for n, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[7:].lstrip()
        key, sep, val = s.partition("=")
        key, val = key.strip(), val.strip()
        if not sep or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            raise ValueError(f"{path.name} บรรทัด {n}: ต้องเป็นรูปแบบ KEY=VALUE")
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        elif " #" in val:                      # comment ท้ายบรรทัด (ค่าที่ไม่มีเครื่องหมายคำพูด)
            val = val.split(" #", 1)[0].rstrip()
        if val.startswith("<") and val.endswith(">"):
            continue                           # ยังเป็นค่าตัวอย่าง <...> นับว่ายังไม่ได้ตั้ง
        if override or key not in env:
            env[key] = val
        keys.append(key)
    return keys


def fits_env_status(test: bool = False, environ=None) -> list[tuple[str, bool]]:
    """ตัวแปร FITS_* ตัวไหนตั้งแล้ว (ไม่คืนค่าจริง) ใช้แสดงในหน้า Settings
    โหมด test: FITS_TEST_* ถ้ามีใช้ก่อน ไม่มีใช้ FITS_* ส่วน URL ไม่ตั้งได้ (ใช้ TEST endpoint ของ fits_client)"""
    env = os.environ if environ is None else environ
    out = []
    for name in FITS_ENV.values():
        tname = name.replace("FITS_", "FITS_TEST_")
        if not test:
            out.append((name, bool(env.get(name))))
        elif name == "FITS_URL":
            out.append((tname, True))
        else:
            out.append((tname if env.get(tname) else name, bool(env.get(tname) or env.get(name))))
    return out


def make_fits_client(app: AppConfig, test: bool = False, environ=None):
    """สร้าง FitsClient จาก environment FITS_* (โหมด test ใช้ TEST endpoint)"""
    try:
        import fits_client
    except ImportError:
        raise FitsSetupError("ยังไม่ได้ติดตั้ง fabrinet_fits_client ใน .venv "
                             "(.venv\\Scripts\\pip install fabrinet_fits_client-*.whl)") from None
    env = os.environ if environ is None else environ
    values = {}
    for key, name in FITS_ENV.items():
        values[key] = (env.get(name.replace("FITS_", "FITS_TEST_")) if test else None) or env.get(name, "")
    if test and not env.get("FITS_TEST_URL"):
        values["url"] = fits_client.TEST_URL
    missing = [FITS_ENV[k] for k, v in values.items() if not v]
    if missing:
        raise FitsSetupError("ยังไม่ได้ตั้งค่า FITS: " + ", ".join(missing)
                             + " (ใส่ในไฟล์ .env ในโฟลเดอร์ han-laser แล้วเปิดโปรแกรมใหม่)")
    cfg = fits_client.FitsConfig(timeout=float(app.fits.timeout), **values)
    return fits_client.FitsClient(cfg)


def fits_log_values(app: AppConfig, ctx: dict) -> tuple[list, list]:
    """ชื่อ parameter และค่า ตามลำดับใน Settings ctx มี key ตาม FITS_SOURCES"""
    fs = app.fits
    names, values = [], []
    for name, src in fs.parameters:
        if src == "wo_pn":
            val = app.workorder_pn.get(ctx.get("workorder", ""), "")
            if not val:
                raise FitsSetupError(f"ยังไม่ได้ตั้ง WO PN ของ Workorder {ctx.get('workorder')} (Settings)")
        elif src in FITS_CONSTANTS:
            val = FITS_CONSTANTS[src]
        else:
            val = str(ctx.get(src, ""))
        if fs.fsp in val:
            raise FitsSetupError(f"ค่าของ '{name}' มีตัวคั่น '{fs.fsp}' ส่ง FITS ไม่ได้: {val}")
        names.append(name)
        values.append(val)
    return names, values


def fits_context(row) -> dict:
    """ค่าสำหรับ FITS log จากแถว verifications (ส่งเฉพาะชิ้นที่ผ่านในเครื่อง -> result PASS)"""
    return {"serial": row["serial"], "workorder": row["workorder"], "iqr": row["iqr"], "en": row["en"],
            "shift": row["shift"], "product": row["product"], "result": "PASS", "failure_code": ""}


@dataclass
class FitsOutcome:
    ok: bool
    handshake: str      # OK | NG | ERROR | '' (ข้าม)
    log: str            # OK | NG | ERROR | ''
    message: str
    reason: str         # '' | FITS_HANDSHAKE | FITS_LOG | FITS_ERROR


def fits_send(client, fs: FitsSettings, serial: str, names: list, values: list,
              skip_handshake: bool = False) -> FitsOutcome:
    """handshake แล้ว log (เรียกจาก thread แยกได้ ไม่แตะ DB)"""
    hs = "OK" if skip_handshake else ""
    stage = "log" if skip_handshake else "handshake"
    try:
        if not skip_handshake:
            r = client.handshake(fs.model, fs.operation, serial)
            if not r.ok:
                return FitsOutcome(False, "NG", "", f"Handshake ไม่ผ่าน: {r.message or '-'}", "FITS_HANDSHAKE")
            hs, stage = "OK", "log"
        r = client.log(fs.model, fs.operation, names, values, fs.fsp)
        if not r.ok:
            return FitsOutcome(False, hs, "NG", f"Log ไม่ผ่าน: {r.message or '-'}", "FITS_LOG")
        return FitsOutcome(True, hs, "OK", r.message or "ส่ง FITS สำเร็จ", "")
    except Exception as e:  # noqa: BLE001  เน็ตล่ม / FITS ไม่ตอบ / SOAP fault -> FAIL + ส่งซ้ำได้
        msg = f"ติดต่อ FITS ไม่ได้ ({stage}): {type(e).__name__}: {e}"
        return FitsOutcome(False, "ERROR" if stage == "handshake" else hs,
                           "ERROR" if stage == "log" else "", msg, "FITS_ERROR")


def finish_fits(store: Store, vid: int, outcome: FitsOutcome) -> None:
    with store.transaction():
        store.finish_verification(vid, "PASS" if outcome.ok else "FAIL", outcome.reason,
                                  outcome.handshake, outcome.log, outcome.message)


def retry_check(store: Store, vid: int):
    """แถวที่ส่ง FITS ซ้ำได้ คืน (row, skip_handshake) ไม่งั้น ValueError"""
    row = store.verification(vid)
    if row is None:
        raise ValueError("ไม่พบรายการนี้")
    if not (row["reason"].startswith("FITS_") or row["result"] == "PENDING"):
        raise ValueError("ส่งซ้ำได้เฉพาะรายการที่ FAIL เพราะ FITS")
    if not row["test"]:
        base = row["serial"]
        prev = store.first_pass(base)
        if prev is not None:
            raise ValueError(f"{base} ผ่านไปแล้วในรายการอื่น (เวลา {prev['scanned_at'].replace('T', ' ')})")
    return row, row["fits_handshake"] == "OK"


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
        load_env_file(Path(args.config).resolve().parent / ENV_FILE)
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
