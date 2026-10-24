"""Database adapter for SQLite (local development) and PostgreSQL (production)."""
import os
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = 'postgresql://' + DATABASE_URL[len('postgres://'):]
USE_POSTGRES = DATABASE_URL.startswith(('postgresql://', 'postgresql+'))
DB_PATH = Path(os.getenv('GAMEVAULT_DB', BASE / 'gamevault.db'))


class PostgresConnection:
    """Small compatibility wrapper so existing ? placeholders keep working."""
    def __init__(self, conn):
        self._conn = conn

    @staticmethod
    def _sql(sql):
        # Application SQL uses positional '?' placeholders (SQLite style).
        # None of the current queries contain literal question marks.
        return sql.replace('?', '%s')

    def execute(self, sql, params=()):
        return self._conn.execute(self._sql(sql), params)

    def commit(self):
        return self._conn.commit()

    def close(self):
        return self._conn.close()


def get_db():
    if USE_POSTGRES:
        import psycopg
        from psycopg.rows import dict_row
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10)
        return PostgresConnection(conn)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def init_db():
    db = get_db()
    if USE_POSTGRES:
        db.execute('''CREATE TABLE IF NOT EXISTS users(
          id BIGSERIAL PRIMARY KEY,
          username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','leader','admin')),
          avatar TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL, last_name_change_at TEXT
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS accounts(
          id BIGSERIAL PRIMARY KEY,
          game TEXT NOT NULL CHECK(game IN ('roblox','freefire','lienquan')),
          code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, note TEXT DEFAULT '',
          email TEXT DEFAULT '', password_enc TEXT NOT NULL, created_at TEXT NOT NULL
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS password_requests(
          id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL,
          account_id BIGINT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
          created_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
          FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS chat_messages(
          id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL,
          body TEXT NOT NULL, pinned INTEGER DEFAULT 0, created_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )''')
        db.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        db.execute("INSERT INTO settings(key,value) VALUES('chat_enabled','1') ON CONFLICT(key) DO NOTHING")
        # IDs may be imported from SQLite; advance each serial sequence safely.
        for table in ('users', 'accounts', 'password_requests', 'chat_messages'):
            db.execute(
                "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                f"GREATEST(COALESCE((SELECT MAX(id) FROM {table}), 1), 1), "
                f"EXISTS(SELECT 1 FROM {table}))",
                (table,),
            )
        db.commit()
        db.close()
        return

    db.executescript('''
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','leader','admin')),
      avatar TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
      created_at TEXT NOT NULL, last_name_change_at TEXT
    );
    CREATE TABLE IF NOT EXISTS accounts(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      game TEXT NOT NULL CHECK(game IN ('roblox','freefire','lienquan')),
      code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, note TEXT DEFAULT '',
      email TEXT DEFAULT '', password_enc TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS password_requests(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
      account_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
      created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
      FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS chat_messages(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
      body TEXT NOT NULL, pinned INTEGER DEFAULT 0, created_at TEXT NOT NULL,
      FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    ''')
    # Older SQLite databases may have the original two-game CHECK constraint.
    schema = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='accounts'").fetchone()
    if schema and "'lienquan'" not in (schema['sql'] or ''):
        db.commit()
        db.execute('PRAGMA foreign_keys=OFF')
        db.executescript("""
        CREATE TABLE accounts_new(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          game TEXT NOT NULL CHECK(game IN ('roblox','freefire','lienquan')),
          code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, note TEXT DEFAULT '',
          email TEXT DEFAULT '', password_enc TEXT NOT NULL, created_at TEXT NOT NULL
        );
        INSERT INTO accounts_new(id,game,code,name,note,email,password_enc,created_at)
          SELECT id,game,code,name,note,email,password_enc,created_at FROM accounts;
        DROP TABLE accounts;
        ALTER TABLE accounts_new RENAME TO accounts;
        """)
        db.execute('PRAGMA foreign_keys=ON')
    db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('chat_enabled','1')")
    db.commit()
    db.close()
