#!/usr/bin/env python3
"""One-time copy of GAMEVAULT data from SQLite to PostgreSQL.

Set DATABASE_URL and SQLITE_SOURCE, then run:
  python migrate_sqlite_to_postgres.py
Run only against an EMPTY PostgreSQL database. Keep the SQLite backup unchanged.
"""
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'backend'))

TABLE_COLUMNS = {
    'users': ('id', 'username', 'password_hash', 'role', 'avatar', 'status', 'created_at', 'last_name_change_at'),
    'accounts': ('id', 'game', 'code', 'name', 'note', 'email', 'password_enc', 'created_at'),
    'password_requests': ('id', 'user_id', 'account_id', 'status', 'created_at'),
    'chat_messages': ('id', 'user_id', 'body', 'pinned', 'created_at'),
    'settings': ('key', 'value'),
}


def main():
    source = os.getenv('SQLITE_SOURCE', '').strip()
    url = os.getenv('DATABASE_URL', '').strip()
    if not source or not url:
        raise SystemExit('Cần đặt SQLITE_SOURCE và DATABASE_URL trước khi chạy.')
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    if not url.startswith('postgresql://'):
        raise SystemExit('DATABASE_URL phải là URL PostgreSQL.')
    source_path = Path(source).expanduser().resolve()
    if not source_path.is_file():
        raise SystemExit(f'Không tìm thấy file SQLite: {source_path}')

    import psycopg
    from psycopg.rows import dict_row
    from database import init_db

    # Create schema and verify target is empty before copying.
    init_db()
    with psycopg.connect(url, row_factory=dict_row) as pg:
        existing = {t: pg.execute(f'SELECT COUNT(*) AS n FROM {t}').fetchone()['n'] for t in TABLE_COLUMNS}
        if any(existing.values()):
            raise SystemExit(f'Database PostgreSQL không trống: {existing}. Dừng để tránh ghi đè/trùng dữ liệu.')

        src = sqlite3.connect(f'file:{source_path}?mode=ro', uri=True)
        src.row_factory = sqlite3.Row
        try:
            expected = {}
            for table, columns in TABLE_COLUMNS.items():
                rows = src.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()
                expected[table] = len(rows)
                if rows:
                    placeholders = ','.join(['%s'] * len(columns))
                    col_sql = ','.join(columns)
                    pg.executemany(
                        f'INSERT INTO {table} ({col_sql}) VALUES ({placeholders})',
                        [tuple(row[c] for c in columns) for row in rows],
                    )
            # Move serial sequences past imported IDs.
            for table in ('users', 'accounts', 'password_requests', 'chat_messages'):
                pg.execute(
                    "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                    f"GREATEST(COALESCE((SELECT MAX(id) FROM {table}), 1), 1), "
                    f"EXISTS(SELECT 1 FROM {table}))",
                    (table,),
                )
        finally:
            src.close()

        actual = {t: pg.execute(f'SELECT COUNT(*) AS n FROM {t}').fetchone()['n'] for t in TABLE_COLUMNS}
        if actual != expected:
            raise SystemExit(f'Đối chiếu số dòng không khớp. SQLite={expected}; PostgreSQL={actual}')
        print('Chuyển dữ liệu thành công. Số dòng đã đối chiếu:')
        for table in TABLE_COLUMNS:
            print(f'  {table}: {actual[table]}')
        print('Giữ nguyên GAME_PASSWORD_KEY cũ để giải mã mật khẩu game đã lưu.')


if __name__ == '__main__':
    main()
