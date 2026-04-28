"""
SQLiteによるユーザー管理
テーブル:
  users           - ユーザー情報・主顔画像
  face_embeddings - 追加顔特徴量（複数顔登録用）
  auth_logs       - 認証試行ログ（監査用）
  app_config      - 永続化設定
"""

import sqlite3
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

DB_PATH = Path(__file__).parent / "face_auth.db"


class Database:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_tables()
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    name       TEXT    NOT NULL,
                    embedding  BLOB    NOT NULL,
                    photo      BLOB,
                    created_at TEXT    DEFAULT (datetime('now', 'localtime'))
                );

                CREATE TABLE IF NOT EXISTS face_embeddings (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    embedding  BLOB    NOT NULL,
                    created_at TEXT    DEFAULT (datetime('now', 'localtime'))
                );

                CREATE TABLE IF NOT EXISTS auth_logs (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER,
                    name       TEXT,
                    score      REAL,
                    success    INTEGER NOT NULL,
                    ip_address TEXT,
                    created_at TEXT    DEFAULT (datetime('now', 'localtime'))
                );

                CREATE TABLE IF NOT EXISTS app_config (
                    key        TEXT PRIMARY KEY,
                    value      TEXT NOT NULL
                );
            """)
            conn.commit()

    def _migrate(self):
        """既存DBにカラムが不足している場合だけ追加する（冪等）"""
        with self._connect() as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
            if "photo" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN photo BLOB")
            if "created_at" not in cols:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN created_at TEXT "
                    "DEFAULT (datetime('now', 'localtime'))"
                )
            if "department" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN department TEXT DEFAULT ''")
            conn.commit()

    # ── ユーザー管理 ──────────────────────────────────────────────────

    def register_user(
        self,
        name: str,
        embedding: np.ndarray,
        photo_bytes: Optional[bytes] = None,
        department: str = "",
    ) -> int:
        blob = embedding.astype(np.float32).tobytes()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO users (name, department, embedding, photo, created_at) VALUES (?, ?, ?, ?, ?)",
                (name, department, blob, photo_bytes, now),
            )
            conn.commit()
            return cur.lastrowid

    def add_face(self, user_id: int, embedding: np.ndarray) -> bool:
        """追加顔特徴量を登録する。ユーザーが存在しない場合は False を返す。"""
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row:
                return False
            conn.execute(
                "INSERT INTO face_embeddings (user_id, embedding) VALUES (?, ?)",
                (user_id, embedding.astype(np.float32).tobytes()),
            )
            conn.commit()
            return True

    def get_face_count(self, user_id: int) -> int:
        """追加登録された顔画像の件数を返す（主顔画像を含まない）。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM face_embeddings WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            return row["cnt"] if row else 0

    def get_all_users(self) -> List[Dict]:
        """全ユーザーの情報・全埋め込みベクトルを返す。"""
        with self._connect() as conn:
            users_rows = conn.execute(
                "SELECT id, name, department, embedding, photo, created_at FROM users ORDER BY department, name"
            ).fetchall()
            extra_rows = conn.execute(
                "SELECT user_id, embedding FROM face_embeddings"
            ).fetchall()

        extra: Dict[int, List[np.ndarray]] = {}
        for row in extra_rows:
            uid = row["user_id"]
            extra.setdefault(uid, []).append(
                np.frombuffer(row["embedding"], dtype=np.float32)
            )

        result = []
        for row in users_rows:
            primary = np.frombuffer(row["embedding"], dtype=np.float32)
            all_embeddings = [primary] + extra.get(row["id"], [])
            result.append({
                "user_id": row["id"],
                "name": row["name"],
                "department": row["department"] or "",
                "embedding": primary,
                "embeddings": all_embeddings,
                "photo": row["photo"],
                "created_at": row["created_at"],
            })
        return result

    def get_user(self, user_id: int) -> Optional[Dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, department, embedding, photo, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        emb = np.frombuffer(row["embedding"], dtype=np.float32)
        return {
            "user_id": row["id"],
            "name": row["name"],
            "department": row["department"] or "",
            "embedding": emb,
            "photo": row["photo"],
            "created_at": row["created_at"],
        }

    def delete_user(self, user_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
            return cur.rowcount > 0

    # ── 監査ログ ─────────────────────────────────────────────────────

    def log_auth(
        self,
        *,
        success: bool,
        ip: str,
        user_id: Optional[int] = None,
        name: Optional[str] = None,
        score: Optional[float] = None,
    ):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO auth_logs (user_id, name, score, success, ip_address) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, name, score, 1 if success else 0, ip),
            )
            conn.commit()

    def get_auth_logs(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, user_id, name, score, success, ip_address, created_at "
                "FROM auth_logs ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    # ── 設定の永続化 ─────────────────────────────────────────────────

    def get_config(self, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM app_config WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def set_config(self, key: str, value: str):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO app_config (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            conn.commit()
