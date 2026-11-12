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
