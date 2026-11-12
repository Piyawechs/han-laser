"""SQLite: ประวัติการ generate และเลขลำดับล่าสุดของแต่ละ product (stdlib sqlite3)"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    product      TEXT NOT NULL,
    lot          TEXT NOT NULL DEFAULT '',
    count        INTEGER NOT NULL,
    first_serial TEXT NOT NULL,
    last_serial  TEXT NOT NULL,
    txt_path     TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS serials (
    serial   TEXT PRIMARY KEY,
    product  TEXT NOT NULL,
    period   TEXT NOT NULL,
    seq      INTEGER NOT NULL,
    batch_id INTEGER NOT NULL REFERENCES batches(id)
);
CREATE INDEX IF NOT EXISTS ix_serials_product_period ON serials(product, period);
CREATE INDEX IF NOT EXISTS ix_batches_created ON batches(created_at);
CREATE INDEX IF NOT EXISTS ix_batches_lot ON batches(lot);
CREATE TABLE IF NOT EXISTS verifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    scanned_at TEXT NOT NULL,
    raw_code   TEXT NOT NULL,
    serial     TEXT NOT NULL,
    product    TEXT NOT NULL DEFAULT '',
    en         TEXT NOT NULL,
    shift      TEXT NOT NULL,
    workorder  TEXT NOT NULL,
    iqr        TEXT NOT NULL DEFAULT '',
    result     TEXT NOT NULL,          -- PASS | FAIL
    reason     TEXT NOT NULL DEFAULT '' -- '' | NOT_FOUND | WRONG_WORKORDER | DUPLICATE
);
CREATE INDEX IF NOT EXISTS ix_verif_serial ON verifications(serial, result);
CREATE INDEX IF NOT EXISTS ix_verif_workorder ON verifications(workorder);
"""


class Store:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None -> คุม transaction เองด้วย BEGIN/COMMIT
        self.conn = sqlite3.connect(str(self.path), isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """เพิ่มคอลัมน์ใหม่ให้ DB ที่สร้างจากเวอร์ชันก่อน"""
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(verifications)")}
        if "iqr" not in cols:
            self.conn.execute("ALTER TABLE verifications ADD COLUMN iqr TEXT NOT NULL DEFAULT ''")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @contextmanager
    def transaction(self):
        """BEGIN IMMEDIATE กันสองโปรแกรมเขียนพร้อมกัน error ข้างใน -> ROLLBACK ทั้งหมด"""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    # ------------------------------------------------------------ read

    def last_seq(self, product: str, period: str) -> int | None:
        row = self.conn.execute(
            "SELECT MAX(seq) FROM serials WHERE product = ? AND period = ?", (product, period)
        ).fetchone()
        return row[0]

    def existing(self, serials: list[str]) -> list[str]:
        """serial ในรายการที่มีอยู่ใน DB แล้ว"""
        found = []
        for i in range(0, len(serials), 500):
            chunk = serials[i:i + 500]
            q = f"SELECT serial FROM serials WHERE serial IN ({','.join('?' * len(chunk))})"
            found += [r[0] for r in self.conn.execute(q, chunk)]
        return sorted(found)

    def list_batches(self, product: str | None = None, lot_like: str | None = None,
                     limit: int = 500) -> list[sqlite3.Row]:
        sql, args = "SELECT * FROM batches WHERE 1=1", []
        if product:
            sql += " AND product = ?"
            args.append(product)
        if lot_like:
            sql += " AND lot LIKE ?"
            args.append(f"%{lot_like}%")
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        return self.conn.execute(sql, args).fetchall()

    def serials_of(self, batch_id: int) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT serial FROM serials WHERE batch_id = ? ORDER BY seq", (batch_id,))]

    def serial_info(self, serial: str) -> sqlite3.Row | None:
        """serial นี้อยู่ batch/lot/product ไหน (None = ไม่เคย generate)"""
        return self.conn.execute(
            "SELECT s.serial, s.product, s.batch_id, b.lot FROM serials s JOIN batches b ON b.id = s.batch_id"
            " WHERE s.serial = ?", (serial,)).fetchone()

    def first_pass(self, serial: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM verifications WHERE serial = ? AND result = 'PASS' ORDER BY id LIMIT 1",
            (serial,)).fetchone()

    def add_verification(self, scanned_at: str, raw_code: str, serial: str, product: str, en: str,
                         shift: str, workorder: str, result: str, reason: str, iqr: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO verifications"
            " (scanned_at, raw_code, serial, product, en, shift, workorder, iqr, result, reason)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (scanned_at, raw_code, serial, product, en, shift, workorder, iqr, result, reason))
        return cur.lastrowid

    def list_verifications(self, workorder: str | None = None, limit: int = 300) -> list[sqlite3.Row]:
        sql, args = "SELECT * FROM verifications", []
        if workorder:
            sql += " WHERE workorder = ?"
            args.append(workorder)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        return self.conn.execute(sql, args).fetchall()

    def workorder_stats(self, workorder: str) -> dict:
        """จำนวนที่ generate ใน workorder นี้ และจำนวนที่ verify PASS แล้ว (นับ serial ไม่ซ้ำ)"""
        generated = self.conn.execute(
            "SELECT COALESCE(SUM(count), 0) FROM batches WHERE lot = ?", (workorder,)).fetchone()[0]
        passed = self.conn.execute(
            "SELECT COUNT(DISTINCT serial) FROM verifications WHERE workorder = ? AND result = 'PASS'",
            (workorder,)).fetchone()[0]
        failed = self.conn.execute(
            "SELECT COUNT(*) FROM verifications WHERE workorder = ? AND result = 'FAIL'",
            (workorder,)).fetchone()[0]
        return {"generated": generated, "passed": passed, "failed": failed}

    # ------------------------------------------------------------ write (เรียกภายใน transaction)

    def add_batch(self, product: str, lot: str, serials: list[str], seqs: list[int],
                  period: str, txt_path: str, created_at: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO batches (product, lot, count, first_serial, last_serial, txt_path, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (product, lot, len(serials), serials[0], serials[-1], txt_path, created_at),
        )
        batch_id = cur.lastrowid
        self.conn.executemany(
            "INSERT INTO serials (serial, product, period, seq, batch_id) VALUES (?, ?, ?, ?, ?)",
            [(s, product, period, q, batch_id) for s, q in zip(serials, seqs)],
        )
        return batch_id
