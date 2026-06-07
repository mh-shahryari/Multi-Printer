"""
توابع کار با SQLite:
- init_db: ایجاد جدول logs (با فیلد paper_size) و جدول printer_counters
- add_event: ثبت رویداد (با پشتیبانی از paper_size)
- get_log: دریافت لاگ یک پرینتر
- get_all_logs: دریافت همه لاگ‌ها با فیلتر
- clear_logs: پاک کردن لاگ‌های غیر از PRINT، SERVICE و REFILL
- prune_old_print_logs: پاکسازی خودکار لاگ‌های PRINT قدیمی
- load_printer_counters, save_printer_counters: ذخیره و بازیابی مقادیر قبلی شمارنده‌ها
"""

import sqlite3
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional

from config.settings import DB_PATH
# NOTE: from core import store حذف شده است (import پویا درون تابع add_event)

log = logging.getLogger("PrinterMonitor")

# فیلدهای top-level که مستقیم در ستون‌های جدول ذخیره می‌شوند (بقیه به details JSON می‌روند)
_LOG_TOP_LEVEL_FIELDS = frozenset(
    ("timestamp", "message", "pages", "color", "code", "severity", "paper_size", "username")
)

MISSING_YIELD_FILE = "missing_yield_printers.txt"

_USER_JSON_FIELDS = frozenset(("allowed_offices", "allowed_modules"))


def update_missing_yield_list(ip: str, current_yield: int):
    """ثبت یا حذف IP از لیست پرینترهای فاقد yield ویژه."""
    try:
        if not os.path.exists(MISSING_YIELD_FILE):
            with open(MISSING_YIELD_FILE, 'w', encoding='utf-8'):
                pass

        with open(MISSING_YIELD_FILE, 'r+', encoding='utf-8') as f:
            lines = {line.strip() for line in f if line.strip()}
            if current_yield == 2000:
                if ip not in lines:
                    lines.add(ip)
                    f.seek(0)
                    f.write('\n'.join(sorted(lines)))
                    f.truncate()
            else:
                if ip in lines:
                    lines.remove(ip)
                    f.seek(0)
                    f.write('\n'.join(sorted(lines)))
                    f.truncate()
    except Exception as e:
        log.exception(f"Error updating {MISSING_YIELD_FILE} for {ip}: {e}")
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")


def _dump_json_list(value) -> str:
    if not value:
        return "[]"
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                value = parsed
            else:
                value = [parsed]
        except Exception:
            value = [value]
    if not isinstance(value, (list, tuple, set)):
        value = [value]
    cleaned = []
    for item in value:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return json.dumps(cleaned, ensure_ascii=False)


def _load_json_list(value):
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    c = conn.cursor()
    
    # بهینه‌سازی performance
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            printer_ip TEXT NOT NULL,
            printer_name TEXT,
            timestamp TEXT NOT NULL,
            type TEXT,
            message TEXT,
            pages INTEGER,
            color TEXT,
            code TEXT,
            severity TEXT,
            paper_size TEXT,
            username TEXT,
            details TEXT
        )
    ''')
    try:
        c.execute("ALTER TABLE logs ADD COLUMN paper_size TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE logs ADD COLUMN username TEXT")
    except sqlite3.OperationalError:
        pass

    c.execute('CREATE INDEX IF NOT EXISTS idx_printer_ip ON logs(printer_ip)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON logs(timestamp)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_type ON logs(type)')

    c.execute('''
        CREATE TABLE IF NOT EXISTS printer_counters (
            ip TEXT PRIMARY KEY,
            device_type TEXT,
            print_total INTEGER,
            full_color INTEGER,
            black_white INTEGER,
            toner_level INTEGER,
            manual_override INTEGER DEFAULT 0,
            override_color TEXT,
            override_base_level INTEGER,
            override_start_total INTEGER,
            override_start_toner INTEGER,
            yield_per_page INTEGER DEFAULT 2000,
            last_alert_codes TEXT,
            a3_total INTEGER,
            a4_total INTEGER,
            alert_codes TEXT,
            updated_at TEXT
        )
    ''')
    # اضافه کردن ستون device_type به جداول قدیمی
    try:
        c.execute("ALTER TABLE printer_counters ADD COLUMN device_type TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE printer_counters ADD COLUMN toner_level INTEGER DEFAULT NULL")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE printer_counters ADD COLUMN manual_override INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE printer_counters ADD COLUMN override_color TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE printer_counters ADD COLUMN override_base_level INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE printer_counters ADD COLUMN override_start_total INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE printer_counters ADD COLUMN override_start_toner INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE printer_counters ADD COLUMN yield_per_page INTEGER DEFAULT 2000")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE printer_counters ADD COLUMN last_alert_codes TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT,
            google_id TEXT UNIQUE,
            reset_token_hash TEXT,
            reset_token_expires TEXT,
            role TEXT NOT NULL DEFAULT 'viewer',
            is_verified INTEGER NOT NULL DEFAULT 0,
            email_verified INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_login_at TEXT,
            allowed_offices TEXT NOT NULL DEFAULT '[]',
            allowed_modules TEXT NOT NULL DEFAULT '[]'
        )
    ''')
    for column_sql in (
        "ALTER TABLE users ADD COLUMN password_hash TEXT",
        "ALTER TABLE users ADD COLUMN google_id TEXT",
        "ALTER TABLE users ADD COLUMN reset_token_hash TEXT",
        "ALTER TABLE users ADD COLUMN reset_token_expires TEXT",
        "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'viewer'",
        "ALTER TABLE users ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE users ADD COLUMN created_at TEXT",
        "ALTER TABLE users ADD COLUMN updated_at TEXT",
        "ALTER TABLE users ADD COLUMN last_login_at TEXT",
        "ALTER TABLE users ADD COLUMN allowed_offices TEXT NOT NULL DEFAULT '[]'",
        "ALTER TABLE users ADD COLUMN allowed_modules TEXT NOT NULL DEFAULT '[]'",
    ):
        try:
            c.execute(column_sql)
        except sqlite3.OperationalError:
            pass
    
    conn.commit()
    conn.close()


def _user_row_to_dict(row) -> Optional[dict]:
    if not row:
        return None
    role = row[7] or "viewer"
    is_verified = bool(row[8])
    return {
        "id": row[0],
        "username": row[1],
        "email": row[2],
        "password_hash": row[3],
        "google_id": row[4],
        "reset_token_hash": row[5],
        "reset_token_expires": row[6],
        "role": role,
        "is_verified": is_verified,
        "email_verified": is_verified,
        "is_active": bool(row[9]),
        "created_at": row[10],
        "updated_at": row[11],
        "last_login_at": row[12],
        "allowed_offices": _load_json_list(row[13] if len(row) > 13 else None),
        "allowed_modules": _load_json_list(row[14] if len(row) > 14 else None),
    }


def count_users() -> int:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        row = c.fetchone()
        conn.close()
        return int(row[0] or 0)
    except Exception as e:
        log.exception(f"Error counting users: {e}")
        return 0


def get_user_by_id(user_id: int) -> Optional[dict]:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
             SELECT id, username, email, password_hash, google_id, reset_token_hash,
                 reset_token_expires, role, is_verified, is_active, created_at,
                 updated_at, last_login_at, allowed_offices, allowed_modules
            FROM users WHERE id = ?
            ''',
            (user_id,),
        )
        row = c.fetchone()
        conn.close()
        return _user_row_to_dict(row)
    except Exception as e:
        log.exception(f"Error loading user {user_id}: {e}")
        return None


def get_user_by_identifier(identifier: str) -> Optional[dict]:
    identifier = (identifier or "").strip().lower()
    if not identifier:
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
             SELECT id, username, email, password_hash, google_id, reset_token_hash,
                 reset_token_expires, role, is_verified, is_active, created_at,
                 updated_at, last_login_at, allowed_offices, allowed_modules
            FROM users WHERE lower(username) = ? OR lower(email) = ?
            ''',
            (identifier, identifier),
        )
        row = c.fetchone()
        conn.close()
        return _user_row_to_dict(row)
    except Exception as e:
        log.exception(f"Error loading user by identifier {identifier}: {e}")
        return None


def get_user_by_email(email: str) -> Optional[dict]:
    email = (email or "").strip().lower()
    if not email:
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
             SELECT id, username, email, password_hash, google_id, reset_token_hash,
                 reset_token_expires, role, is_verified, is_active, created_at,
                 updated_at, last_login_at, allowed_offices, allowed_modules
            FROM users WHERE lower(email) = ?
            ''',
            (email,),
        )
        row = c.fetchone()
        conn.close()
        return _user_row_to_dict(row)
    except Exception as e:
        log.exception(f"Error loading user by email {email}: {e}")
        return None


def get_user_by_google_id(google_id: str) -> Optional[dict]:
    google_id = (google_id or "").strip()
    if not google_id:
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
             SELECT id, username, email, password_hash, google_id, reset_token_hash,
                 reset_token_expires, role, is_verified, is_active, created_at,
                 updated_at, last_login_at, allowed_offices, allowed_modules
            FROM users WHERE google_id = ?
            ''',
            (google_id,),
        )
        row = c.fetchone()
        conn.close()
        return _user_row_to_dict(row)
    except Exception as e:
        log.exception(f"Error loading user by google_id {google_id}: {e}")
        return None


def create_user(username: str, email: str, password_hash: str = None, google_id: str = None,
                role: str = "viewer", is_verified: bool = False,
                allowed_offices=None, allowed_modules=None) -> Optional[dict]:
    now = datetime.now().isoformat()
    try:
        username = (username or "").strip()
        if not USERNAME_RE.fullmatch(username):
            log.warning("Rejecting invalid username during user creation: %s", username)
            return None
        role = role if role in ("admin", "manager", "viewer") else "viewer"
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            INSERT INTO users (username, email, password_hash, google_id, role,
                               is_verified, email_verified, is_active, created_at, updated_at,
                               allowed_offices, allowed_modules)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            ''',
            (username.strip(), email.strip().lower(), password_hash, google_id,
             role, 1 if is_verified else 0, 1 if is_verified else 0, now, now,
             _dump_json_list(allowed_offices), _dump_json_list(allowed_modules)),
        )
        user_id = c.lastrowid
        conn.commit()
        conn.close()
        return get_user_by_id(user_id)
    except Exception as e:
        log.exception(f"Error creating user {username}: {e}")
        return None


def update_user_password(user_id: int, password_hash: str) -> bool:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            'UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?',
            (password_hash, datetime.now().isoformat(), user_id),
        )
        conn.commit()
        ok = c.rowcount > 0
        conn.close()
        return ok
    except Exception as e:
        log.exception(f"Error updating password for user {user_id}: {e}")
        return False


def set_user_google_id(user_id: int, google_id: str) -> bool:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            'UPDATE users SET google_id = ?, updated_at = ? WHERE id = ?',
            (google_id, datetime.now().isoformat(), user_id),
        )
        conn.commit()
        ok = c.rowcount > 0
        conn.close()
        return ok
    except Exception as e:
        log.exception(f"Error updating google_id for user {user_id}: {e}")
        return False


def touch_user_login(user_id: int) -> None:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.execute(
            'UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?',
            (now, now, user_id),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.exception(f"Error touching login for user {user_id}: {e}")


def list_users() -> list:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            SELECT id, username, email, password_hash, google_id, reset_token_hash,
                   reset_token_expires, role, is_verified, is_active, created_at,
                   updated_at, last_login_at
            FROM users
            ORDER BY
                CASE role
                    WHEN 'admin' THEN 0
                    WHEN 'manager' THEN 1
                    ELSE 2
                END,
                username COLLATE NOCASE ASC
            '''
        )
        rows = c.fetchall()
        conn.close()
        return [_user_row_to_dict(r) for r in rows]
    except Exception as e:
        log.exception(f"Error listing users: {e}")
        return []


def update_user_role(user_id: int, role: str) -> bool:
    role = role if role in ("admin", "manager", "viewer") else None
    if not role:
        return False
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            'UPDATE users SET role = ?, updated_at = ? WHERE id = ?',
            (role, datetime.now().isoformat(), user_id),
        )
        conn.commit()
        ok = c.rowcount > 0
        conn.close()
        return ok
    except Exception as e:
        log.exception(f"Error updating role for user {user_id}: {e}")
        return False


def update_user_verified(user_id: int, is_verified: bool) -> bool:
    try:
        verified_int = 1 if is_verified else 0
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            'UPDATE users SET is_verified = ?, email_verified = ?, updated_at = ? WHERE id = ?',
            (verified_int, verified_int, datetime.now().isoformat(), user_id),
        )
        conn.commit()
        ok = c.rowcount > 0
        conn.close()
        return ok
    except Exception as e:
        log.exception(f"Error updating verification for user {user_id}: {e}")
        return False


def update_user_access(user_id: int, allowed_offices=None, allowed_modules=None) -> bool:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            UPDATE users
            SET allowed_offices = ?, allowed_modules = ?, updated_at = ?
            WHERE id = ?
            ''',
            (_dump_json_list(allowed_offices), _dump_json_list(allowed_modules), datetime.now().isoformat(), user_id),
        )
        conn.commit()
        ok = c.rowcount > 0
        conn.close()
        return ok
    except Exception as e:
        log.exception(f"Error updating access for user {user_id}: {e}")
        return False


def delete_user(user_id: int) -> bool:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('DELETE FROM users WHERE id = ?', (user_id,))
        conn.commit()
        ok = c.rowcount > 0
        conn.close()
        return ok
    except Exception as e:
        log.exception(f"Error deleting user {user_id}: {e}")
        return False


def set_password_reset_token(user_id: int, token_hash: str, expires_at: str) -> bool:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            UPDATE users
            SET reset_token_hash = ?, reset_token_expires = ?, updated_at = ?
            WHERE id = ?
            ''',
            (token_hash, expires_at, datetime.now().isoformat(), user_id),
        )
        conn.commit()
        ok = c.rowcount > 0
        conn.close()
        return ok
    except Exception as e:
        log.exception(f"Error setting reset token for user {user_id}: {e}")
        return False


def get_user_by_reset_token_hash(token_hash: str) -> Optional[dict]:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            SELECT id, username, email, password_hash, google_id, reset_token_hash,
                   reset_token_expires, role, is_verified, is_active, created_at,
                   updated_at, last_login_at, allowed_offices, allowed_modules
            FROM users WHERE reset_token_hash = ?
            ''',
            (token_hash,),
        )
        row = c.fetchone()
        conn.close()
        return _user_row_to_dict(row)
    except Exception as e:
        log.exception(f"Error loading user by reset token: {e}")
        return None


def clear_password_reset_token(user_id: int) -> bool:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            UPDATE users
            SET reset_token_hash = NULL, reset_token_expires = NULL, updated_at = ?
            WHERE id = ?
            ''',
            (datetime.now().isoformat(), user_id),
        )
        conn.commit()
        ok = c.rowcount > 0
        conn.close()
        return ok
    except Exception as e:
        log.exception(f"Error clearing reset token for user {user_id}: {e}")
        return False


def add_event(ip: str, etype: str, details: dict):
    try:
        from core import store
        conn = sqlite3.connect(DB_PATH, timeout=10.0)  # timeout اضافه شد
        c = conn.cursor()
        timestamp = details.get("timestamp", datetime.now().isoformat())
        message = details.get("message", "")
        pages = details.get("pages")
        color = details.get("color")
        code = details.get("code")
        severity = details.get("severity", "info")
        paper_size = details.get("paper_size")
        username = details.get("username")
        other = {k: v for k, v in details.items() if k not in _LOG_TOP_LEVEL_FIELDS}
        printer_name = None
        with store.printers_lock:
            for p in store.PRINTERS:
                if p["ip"] == ip:
                    printer_name = p["name"]
                    break
        c.execute('''
            INSERT INTO logs (printer_ip, printer_name, timestamp, type, message,
                              pages, color, code, severity, paper_size, username, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (ip, printer_name, timestamp, etype, message,
              pages, color, code, severity, paper_size, username,
              json.dumps(other, ensure_ascii=False)))
        conn.commit()
        conn.close()
    except Exception as e:
        log.exception(f"Error adding event to DB: {e}")


def _row_to_dict(row) -> dict:
    return {
        "printer_ip":   row[0],
        "printer_name": row[1],
        "timestamp":    row[2],
        "type":         row[3],
        "message":      row[4],
        "pages":        row[5],
        "color":        row[6],
        "code":         row[7],
        "severity":     row[8],
        "paper_size":   row[9],
        "username":     row[10],
        **json.loads(row[11] or "{}"),
    }


def get_log(ip: str, limit: int = 500, ips=None) -> list:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        params = []
        where = "WHERE printer_ip = ?"
        if ips:
            ips = [str(item).strip() for item in ips if str(item).strip()]
            if not ips:
                conn.close()
                return []
            placeholders = ",".join(["?"] * len(ips))
            where = f"WHERE printer_ip IN ({placeholders})"
            params.extend(ips)
        else:
            params.append(ip)
        c.execute('''
            SELECT printer_ip, printer_name, timestamp, type, message,
                   pages, color, code, severity, paper_size, username, details
            FROM logs ''' + where + '''
            ORDER BY timestamp DESC LIMIT ?
        ''', params + [limit])
        rows = c.fetchall()
        conn.close()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        log.exception(f"Error reading logs from DB: {e}")
        return []


def get_all_logs(start=None, end=None, limit: int = 1000, ip=None, ips=None) -> list:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        query = '''
            SELECT printer_ip, printer_name, timestamp, type, message,
                   pages, color, code, severity, paper_size, username, details
            FROM logs
        '''
        params = []
        conditions = []
        if ips:
            ips = [str(item).strip() for item in ips if str(item).strip()]
            if not ips:
                conn.close()
                return []
            placeholders = ",".join(["?"] * len(ips))
            conditions.append(f"printer_ip IN ({placeholders})")
            params.extend(ips)
        elif ip:
            conditions.append("printer_ip = ?")
            params.append(ip)
        if start and end:
            conditions.append("timestamp BETWEEN ? AND ?")
            params.extend([start, end])
        elif start:
            conditions.append("timestamp >= ?")
            params.append(start)
        elif end:
            conditions.append("timestamp <= ?")
            params.append(end)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        c.execute(query, params)
        rows = c.fetchall()
        conn.close()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        log.exception(f"Error reading all logs: {e}")
        return []


def clear_logs(ip=None, ips=None) -> int:
    """
    پاک کردن رویدادهای غیر از PRINT، SERVICE و REFILL.
    رویدادهای PRINT، SERVICE و REFILL هرگز پاک نمی‌شوند.
    """
    keep_types = ('PRINT', 'SERVICE', 'REFILL')
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        placeholders = ','.join(['?'] * len(keep_types))
        if ips:
            ips = [str(item).strip() for item in ips if str(item).strip()]
            if not ips:
                conn.close()
                return 0
            ip_placeholders = ','.join(['?'] * len(ips))
            type_placeholders = ','.join(['?'] * len(keep_types))
            c.execute(
                f"DELETE FROM logs WHERE printer_ip IN ({ip_placeholders}) AND type NOT IN ({type_placeholders})",
                tuple(ips) + keep_types
            )
        elif ip:
            c.execute(
                f"DELETE FROM logs WHERE printer_ip = ? AND type NOT IN ({placeholders})",
                (ip,) + keep_types
            )
        else:
            c.execute(
                f"DELETE FROM logs WHERE type NOT IN ({placeholders})",
                keep_types
            )
        deleted = c.rowcount
        conn.commit()
        conn.close()
        log.info(f"clear_logs: {deleted} رویداد پاک شد (PRINT, SERVICE, REFILL حفظ شد)")
        return deleted
    except Exception as e:
        log.exception(f"Error clearing logs: {e}")
        return 0


def ensure_printer_counters_columns():
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        c = conn.cursor()
        for column_sql in (
            "ALTER TABLE printer_counters ADD COLUMN device_type TEXT",
            "ALTER TABLE printer_counters ADD COLUMN toner_level INTEGER DEFAULT NULL",
            "ALTER TABLE printer_counters ADD COLUMN manual_override INTEGER DEFAULT 0",
            "ALTER TABLE printer_counters ADD COLUMN override_color TEXT",
            "ALTER TABLE printer_counters ADD COLUMN override_base_level INTEGER",
            "ALTER TABLE printer_counters ADD COLUMN override_start_total INTEGER",
            "ALTER TABLE printer_counters ADD COLUMN override_start_toner INTEGER",
            "ALTER TABLE printer_counters ADD COLUMN yield_per_page INTEGER DEFAULT 2000",
            "ALTER TABLE printer_counters ADD COLUMN last_alert_codes TEXT DEFAULT NULL",
        ):
            try:
                c.execute(column_sql)
            except sqlite3.OperationalError:
                pass
        conn.commit()
        conn.close()
    except Exception as e:
        log.exception(f"Error ensuring printer_counters columns: {e}")


def prune_old_print_logs(days=90) -> int:
    """
    حذف خودکار لاگ‌های نوع PRINT که قدیمی‌تر از days روز هستند.
    """
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM logs WHERE type='PRINT' AND timestamp < ?", (cutoff,))
        deleted = c.rowcount
        conn.commit()
        conn.close()
        if deleted:
            log.info(f"prune_old_print_logs: {deleted} رکورد PRINT قدیمی پاک شد")
        return deleted
    except Exception as e:
        log.exception(f"Error pruning old logs: {e}")
        return 0


def load_printer_counters(ip: str) -> dict:
    """بارگذاری آخرین مقادیر شمارنده از دیتابیس"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT print_total, full_color, black_white, toner_level, manual_override, override_color, override_base_level, override_start_total, override_start_toner, yield_per_page, last_alert_codes, a3_total, a4_total, alert_codes FROM printer_counters WHERE ip = ?", (ip,))
        row = c.fetchone()
        conn.close()
        if row:
            return {
                "print_total": row[0],
                "full_color": row[1],
                "black_white": row[2],
                "toner_level": row[3],
                "manual_override": row[4] or 0,
                "override_color": row[5],
                "override_base_level": row[6],
                "override_start_total": row[7],
                "override_start_toner": row[8],
                "yield_per_page": row[9] if row[9] is not None else 2000,
                "last_alert_codes": json.loads(row[10]) if row[10] else [],
                "a3_total": row[11],
                "a4_total": row[12],
                "alert_codes": json.loads(row[13]) if row[13] else [],
            }
    except Exception as e:
        log.exception(f"Error loading counters for {ip}: {e}")
    return None


def save_printer_counters(ip: str, data: dict):
    """ذخیره مقادیر شمارنده در دیتابیس"""
    ensure_printer_counters_columns()
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT OR REPLACE INTO printer_counters
            (ip, print_total, full_color, black_white, toner_level, manual_override, override_color, override_base_level, override_start_total, override_start_toner, yield_per_page, last_alert_codes, a3_total, a4_total, alert_codes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            ip,
            data.get("print_total"),
            data.get("full_color"),
            data.get("black_white"),
            data.get("toner_level"),
            data.get("manual_override", 0),
            data.get("override_color"),
            data.get("override_base_level"),
            data.get("override_start_total"),
            data.get("override_start_toner"),
            data.get("yield_per_page", 2000),
            json.dumps(data.get("last_alert_codes", [])),
            data.get("a3_total"),
            data.get("a4_total"),
            json.dumps(data.get("alert_codes", [])),
            datetime.now().isoformat()
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        log.exception(f"Error saving counters for {ip}: {e}")