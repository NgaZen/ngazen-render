# -*- coding: utf-8 -*-
"""
NgaZen Hosting Bot – Ultimate Edition v3
Projects = Folders. Add unlimited files into a folder. Any file type.
No auto-run. All packages pre-installed. Sleek glass website.
"""

import os
import sys
import subprocess
import threading
import time
import sqlite3
import json
import logging
import shutil
import tempfile
import zipfile
import re
import signal
import atexit
import random
import string
import base64
import hashlib
from datetime import datetime, timedelta

# ============================================================================
# AUTO-INSTALL CORE
# ============================================================================
def auto_install(package):
    try:
        __import__(package)
    except ModuleNotFoundError:
        print(f"Installing {package} ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", package])

CORE = ["pyTelegramBotAPI", "psutil", "requests", "flask"]
for p in CORE:
    import_name = "telebot" if p == "pyTelegramBotAPI" else p
    auto_install(import_name)

from flask import Flask, render_template_string, request, session, redirect, url_for, send_file, jsonify
import telebot
from telebot import types
import psutil
import requests

# Pre-install EVERYTHING in background so user bots just work
EXTRA = [
    "aiohttp","aiofiles","asyncio-throttle","aiohttp-socks","python-socks",
    "colorama","rich","pyfiglet","tqdm","emoji","faker",
    "cryptography","pyOpenSSL","pynacl","bcrypt","pytz","tzlocal","python-dateutil",
    "apscheduler","motor","pymongo","redis","sqlalchemy","psycopg2-binary","dnspython",
    "urllib3","certifi","charset-normalizer","idna","six","websockets","websocket-client",
    "httpx","httpcore","fastapi","uvicorn","jinja2","markdown","lxml","beautifulsoup4",
    "openpyxl","pandas","numpy","Pillow","qrcode","python-dotenv","PyYAML",
    "google-generativeai","openai","python-telegram-bot","aiogram","pyrogram",
    "telethon","tgcrypto","pyromod","wheel","setuptools","pip"
]
def _install_extra_bg():
    for pkg in EXTRA:
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "--quiet",
                            "--disable-pip-version-check", pkg],
                           capture_output=True, timeout=180)
        except:
            pass
threading.Thread(target=_install_extra_bg, daemon=True).start()

# ============================================================================
# CONFIG
# ============================================================================
TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
ADMIN_ID = int(os.environ.get("ADMIN_ID", str(OWNER_ID)))
YOUR_USERNAME = os.environ.get("YOUR_USERNAME", "@OfcNgaZen")
UPDATE_CHANNEL = os.environ.get("UPDATE_CHANNEL", "https://t.me/ChannelByCrucial")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, 'upload_bots')
IROTECH_DIR = os.path.join(BASE_DIR, 'inf')
DATABASE_PATH = os.path.join(IROTECH_DIR, 'bot_data.db')
os.makedirs(UPLOAD_BOTS_DIR, exist_ok=True)
os.makedirs(IROTECH_DIR, exist_ok=True)

bot = telebot.TeleBot(TOKEN)

RUNNABLE_EXTS = {'.py': 'py', '.js': 'js'}

# ============================================================================
# DATABASE
# ============================================================================
class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_db()
        self._init_settings()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT, first_name TEXT,
                        token TEXT UNIQUE, joined_at TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions (user_id INTEGER PRIMARY KEY, expiry TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS projects (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER, name TEXT, created_at TEXT,
                        UNIQUE(user_id, name))''')
        c.execute('''CREATE TABLE IF NOT EXISTS files (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER, project_id INTEGER DEFAULT 0,
                        display_name TEXT, stored_name TEXT, file_type TEXT,
                        running INTEGER DEFAULT 0, uploaded_at TEXT)''')
        # migrations for old db
        for col, ddl in [('project_id', "ALTER TABLE files ADD COLUMN project_id INTEGER DEFAULT 0"),
                         ('folder_name', "ALTER TABLE files ADD COLUMN folder_name TEXT DEFAULT ''")]:
            try:
                c.execute(ddl)
            except Exception:
                pass
        c.execute('''CREATE TABLE IF NOT EXISTS active_users (user_id INTEGER PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS bot_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER, action TEXT, details TEXT, timestamp TEXT)''')
        c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (OWNER_ID,))
        if ADMIN_ID != OWNER_ID:
            c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (ADMIN_ID,))
        conn.commit()
        conn.close()
        self._migrate_legacy()

    def _migrate_legacy(self):
        """Move old rows (project_id=0) that have folder_name into real projects."""
        try:
            rows = self._q("SELECT id, user_id, folder_name FROM files WHERE project_id=0 AND folder_name != ''", fetch=True)
            for fid, uid, fname in rows:
                pid = self.get_or_create_project(uid, fname)
                self._q('UPDATE files SET project_id=? WHERE id=?', (pid, fid))
        except Exception:
            pass

    def _init_settings(self):
        defaults = {
            'free_user_limit': '10',
            'premium_user_limit': '50',
            'admin_limit': '999',
            'max_upload_size_mb': '0',
            'log_retention_days': '30',
            'auto_restart_on_crash': '1',
            'website_url': 'http://139.180.139.82:8080'
        }
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        for key, val in defaults.items():
            c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?,?)', (key, val))
        conn.commit()
        conn.close()

    def _q(self, sql, params=(), fetch=False):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(sql, params)
        rows = c.fetchall() if fetch else None
        lastid = c.lastrowid
        conn.commit()
        conn.close()
        return rows if fetch else lastid

    # ---- settings / logs / users ----
    def get_setting(self, key, default=None):
        rows = self._q('SELECT value FROM settings WHERE key=?', (key,), fetch=True)
        return rows[0][0] if rows else default

    def set_setting(self, key, value):
        self._q('INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)', (key, value))

    def log_action(self, user_id, action, details=''):
        self._q('INSERT INTO bot_logs (user_id, action, details, timestamp) VALUES (?,?,?,?)',
                (user_id, action, details, datetime.now().isoformat()))

    def get_user_token(self, user_id):
        rows = self._q('SELECT token FROM users WHERE user_id=?', (user_id,), fetch=True)
        if rows:
            return rows[0][0]
        token = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
        self._q('INSERT OR IGNORE INTO users (user_id, token, joined_at) VALUES (?,?,?)',
                (user_id, token, datetime.now().isoformat()))
        return token

    def get_user_by_token(self, token):
        rows = self._q('SELECT user_id FROM users WHERE token=?', (token,), fetch=True)
        return rows[0][0] if rows else None

    def get_user_info(self, user_id):
        rows = self._q('SELECT username, first_name, joined_at FROM users WHERE user_id=?', (user_id,), fetch=True)
        return rows[0] if rows else (None, None, None)

    def update_user_info(self, user_id, username, first_name):
        self._q('UPDATE users SET username=?, first_name=? WHERE user_id=?',
                (username or '', first_name or '', user_id))

    # ---- projects ----
    def get_or_create_project(self, user_id, name):
        self._q('INSERT OR IGNORE INTO projects (user_id, name, created_at) VALUES (?,?,?)',
                (user_id, name, datetime.now().isoformat()))
        rows = self._q('SELECT id FROM projects WHERE user_id=? AND name=?', (user_id, name), fetch=True)
        return rows[0][0]

    def get_project(self, pid):
        rows = self._q('SELECT id, user_id, name FROM projects WHERE id=?', (pid,), fetch=True)
        return rows[0] if rows else None

    def get_project_by_name(self, user_id, name):
        rows = self._q('SELECT id FROM projects WHERE user_id=? AND name=?', (user_id, name), fetch=True)
        return rows[0][0] if rows else None

    def get_user_projects(self, user_id):
        """Returns list of (id, name, total_files, running_files)."""
        return self._q('''SELECT p.id, p.name,
                                 (SELECT COUNT(*) FROM files f WHERE f.project_id=p.id),
                                 (SELECT COUNT(*) FROM files f WHERE f.project_id=p.id AND f.running=1)
                          FROM projects p WHERE p.user_id=? ORDER BY p.id DESC''',
                       (user_id,), fetch=True)

    def project_exists(self, user_id, name):
        return bool(self._q('SELECT 1 FROM projects WHERE user_id=? AND name=?', (user_id, name), fetch=True))

    def delete_project(self, pid, user_id):
        proj = self.get_project(pid)
        if not proj or proj[1] != user_id:
            return False
        self._q('DELETE FROM files WHERE project_id=?', (pid,))
        self._q('DELETE FROM projects WHERE id=?', (pid,))
        pdir = project_dir(user_id, proj[2])
        if os.path.isdir(pdir):
            shutil.rmtree(pdir, ignore_errors=True)
        return True

    # ---- files ----
    def get_project_files(self, pid):
        return self._q('SELECT id, display_name, stored_name, file_type, running, uploaded_at '
                       'FROM files WHERE project_id=? ORDER BY uploaded_at DESC', (pid,), fetch=True)

    def get_user_files(self, user_id):
        return self._q('SELECT id, display_name, stored_name, file_type, running, uploaded_at '
                       'FROM files WHERE user_id=? ORDER BY uploaded_at DESC', (user_id,), fetch=True)

    def add_file(self, user_id, project_id, display_name, stored_name, file_type):
        return self._q('INSERT INTO files (user_id, project_id, display_name, stored_name, file_type, running, uploaded_at) '
                       'VALUES (?,?,?,?,?,0,?)',
                       (user_id, project_id, display_name, stored_name, file_type, datetime.now().isoformat()))

    def file_exists_in_project(self, pid, stored_name):
        return bool(self._q('SELECT 1 FROM files WHERE project_id=? AND stored_name=?',
                            (pid, stored_name), fetch=True))

    def get_file_row(self, file_id):
        rows = self._q('SELECT id, user_id, project_id, display_name, stored_name, file_type, running '
                       'FROM files WHERE id=?', (file_id,), fetch=True)
        return rows[0] if rows else None

    def delete_file(self, file_id):
        row = self.get_file_row(file_id)
        if not row:
            return False
        _, user_id, pid, _, stored_name, _, _ = row
        self._q('DELETE FROM files WHERE id=?', (file_id,))
        fp = file_full_path(user_id, pid, stored_name)
        if fp and os.path.exists(fp):
            try: os.remove(fp)
            except: pass
        if fp:
            log_path = os.path.join(os.path.dirname(fp), os.path.splitext(os.path.basename(fp))[0] + '.log')
            if os.path.exists(log_path):
                try: os.remove(log_path)
                except: pass
        return True

    def set_running(self, file_id, running):
        self._q('UPDATE files SET running=? WHERE id=?', (1 if running else 0, file_id))

    def get_running_files(self):
        return self._q('SELECT id FROM files WHERE running=1', fetch=True)

    def rename_file(self, file_id, new_display_name):
        self._q('UPDATE files SET display_name=? WHERE id=?', (new_display_name, file_id))

    # ---- admin / subs ----
    def is_admin(self, user_id):
        return bool(self._q('SELECT 1 FROM admins WHERE user_id=?', (user_id,), fetch=True))

    def add_admin(self, user_id):
        self._q('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (user_id,))

    def remove_admin(self, user_id):
        if user_id == OWNER_ID:
            return False
        self._q('DELETE FROM admins WHERE user_id=?', (user_id,))
        return True

    def get_all_admins(self):
        return [r[0] for r in self._q('SELECT user_id FROM admins', fetch=True)]

    def get_all_users(self):
        return [r[0] for r in self._q('SELECT user_id FROM users', fetch=True)]

    def get_subscription(self, user_id):
        rows = self._q('SELECT expiry FROM subscriptions WHERE user_id=?', (user_id,), fetch=True)
        if rows:
            try:
                return datetime.fromisoformat(rows[0][0])
            except:
                return None
        return None

    def set_subscription(self, user_id, expiry):
        self._q('INSERT OR REPLACE INTO subscriptions (user_id, expiry) VALUES (?,?)',
                (user_id, expiry.isoformat()))

    def remove_subscription(self, user_id):
        self._q('DELETE FROM subscriptions WHERE user_id=?', (user_id,))

    def add_active_user(self, user_id):
        self._q('INSERT OR IGNORE INTO active_users (user_id) VALUES (?)', (user_id,))

    def get_active_users(self):
        return [r[0] for r in self._q('SELECT user_id FROM active_users', fetch=True)]

    def get_logs(self, limit=50):
        return self._q('SELECT id, user_id, action, details, timestamp FROM bot_logs ORDER BY id DESC LIMIT ?',
                       (limit,), fetch=True)

    def get_user_count(self):
        return self._q('SELECT COUNT(*) FROM users', fetch=True)[0][0]

    def get_file_count(self, user_id=None):
        if user_id:
            return self._q('SELECT COUNT(*) FROM files WHERE user_id=?', (user_id,), fetch=True)[0][0]
        return self._q('SELECT COUNT(*) FROM files', fetch=True)[0][0]

db = Database(DATABASE_PATH)

# ============================================================================
# PATH HELPERS
# ============================================================================
def sanitize_folder_name(name):
    name = (name or '').strip().replace('\\', '').replace('/', '')
    name = re.sub(r'[^\w\-. ]', '', name, flags=re.UNICODE).strip().strip('.')
    return name[:50]

def project_dir(user_id, name):
    return os.path.join(UPLOAD_BOTS_DIR, str(user_id), 'projects', name)

def file_full_path(user_id, pid, stored_name):
    if pid:
        proj = db.get_project(pid)
        if not proj:
            return None
        return os.path.join(project_dir(user_id, proj[2]), stored_name)
    return os.path.join(UPLOAD_BOTS_DIR, str(user_id), stored_name)

def detect_type(filename):
    ext = os.path.splitext(filename)[1].lower()
    return RUNNABLE_EXTS.get(ext, ext.lstrip('.') or 'file')

def is_runnable(file_type):
    return file_type in ('py', 'js')

def ext_icon(name, ftype=''):
    if ftype == 'py': return '🐍'
    if ftype == 'js': return '🟨'
    e = os.path.splitext(name)[1].lower()
    return {'.txt': '📄', '.json': '🧾', '.zip': '🗜', '.db': '🗄', '.env': '🔐',
            '.yml': '⚙️', '.yaml': '⚙️', '.csv': '📊', '.html': '🌐', '.md': '📝',
            '.png': '🖼', '.jpg': '🖼', '.jpeg': '🖼', '.mp3': '🎵', '.mp4': '🎬',
            '.sh': '🐚', '.log': '📜', '.session': '🔑'}.get(e, '📎')

def safe_extract_zip(zip_path, dest_dir):
    dest_real = os.path.realpath(dest_dir)
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for member in zf.namelist():
            target = os.path.realpath(os.path.join(dest_dir, member))
            if not target.startswith(dest_real + os.sep) and target != dest_real:
                raise ValueError(f"Unsafe path in zip: {member}")
        zf.extractall(dest_dir)
    return True

def format_bytes(size):
    for unit in ['B','KB','MB','GB','TB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"

def get_system_stats():
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    uptime = time.time() - psutil.boot_time()
    return {'cpu': cpu, 'memory_total': mem.total, 'memory_used': mem.used,
            'memory_percent': mem.percent, 'disk_total': disk.total,
            'disk_used': disk.used, 'disk_percent': disk.percent, 'uptime': uptime}

def get_user_limit(user_id):
    if user_id == OWNER_ID:
        return float('inf')
    if db.is_admin(user_id):
        return int(db.get_setting('admin_limit', '999'))
    sub = db.get_subscription(user_id)
    if sub and sub > datetime.now():
        return int(db.get_setting('premium_user_limit', '50'))
    return int(db.get_setting('free_user_limit', '10'))

def count_user_files(user_id):
    return db.get_file_count(user_id)

# ============================================================================
# SCRIPT MANAGER
# ============================================================================
class ScriptManager:
    def __init__(self):
        self.processes = {}
        self.metadata = {}
        self.lock = threading.Lock()
        self._restore_running()

    def _restore_running(self):
        for (file_id,) in db.get_running_files():
            self.start(file_id)

    def _resolve(self, file_id):
        row = db.get_file_row(file_id)
        if not row:
            return None
        _, user_id, pid, disp, stored_name, ftype, running = row
        full = file_full_path(user_id, pid, stored_name)
        return user_id, pid, disp, stored_name, ftype, full

    def start(self, file_id, notify=True):
        if file_id in self.processes:
            return False
        res = self._resolve(file_id)
        if not res:
            return False
        user_id, pid, disp, stored_name, ftype, script_path = res
        if not is_runnable(ftype) or not script_path or not os.path.exists(script_path):
            db.set_running(file_id, False)
            return False
        work_dir = os.path.dirname(script_path)
        proj_root = os.path.dirname(work_dir)
        # install requirements first if present (project root or script dir)
        for cand in (os.path.join(proj_root, 'requirements.txt'),
                     os.path.join(proj_root, 'user_requirements.txt'),
                     os.path.join(work_dir, 'requirements.txt')):
            if os.path.exists(cand):
                if notify:
                    try: bot.send_message(user_id, f"📦 Installing packages from `{os.path.basename(cand)}`...", parse_mode='Markdown')
                    except: pass
                try:
                    subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', cand],
                                   capture_output=True, timeout=600)
                except:
                    pass
                break
        log_path = os.path.join(work_dir, os.path.splitext(os.path.basename(stored_name))[0] + '.log')
        try:
            log_file = open(log_path, 'w', encoding='utf-8', errors='ignore')
        except:
            return False
        cmd = [sys.executable, script_path] if ftype == 'py' else ['node', script_path]
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
        try:
            proc = subprocess.Popen(cmd, cwd=work_dir, stdout=log_file, stderr=log_file,
                                    stdin=subprocess.PIPE, startupinfo=startupinfo,
                                    encoding='utf-8', errors='ignore')
            with self.lock:
                self.processes[file_id] = proc
                self.metadata[file_id] = {'log_file': log_file, 'user_id': user_id,
                                          'stored_name': stored_name, 'start_time': datetime.now(),
                                          'work_dir': work_dir}
            db.set_running(file_id, True)
            threading.Thread(target=self._log_watcher, args=(file_id, log_path, user_id, stored_name), daemon=True).start()
            return True
        except Exception:
            log_file.close()
            return False

    def stop(self, file_id):
        with self.lock:
            if file_id not in self.processes:
                return False
            proc = self.processes[file_id]
            meta = self.metadata.get(file_id, {})
        try:
            parent = psutil.Process(proc.pid)
            children = parent.children(recursive=True)
            for child in children:
                try: child.terminate()
                except: pass
            gone, alive = psutil.wait_procs(children, timeout=2)
            for p in alive:
                try: p.kill()
                except: pass
            parent.terminate()
            try: parent.wait(timeout=2)
            except: parent.kill()
        except:
            try: proc.kill()
            except: pass
        lf = meta.get('log_file')
        if lf and not lf.closed:
            try: lf.close()
            except: pass
        with self.lock:
            self.processes.pop(file_id, None)
            self.metadata.pop(file_id, None)
        db.set_running(file_id, False)
        return True

    def restart(self, file_id):
        self.stop(file_id)
        time.sleep(0.5)
        return self.start(file_id)

    def is_running(self, file_id):
        with self.lock:
            return file_id in self.processes

    def stop_all(self):
        for fid in list(self.processes.keys()):
            self.stop(fid)

    def _log_watcher(self, file_id, log_path, user_id, stored_name):
        start = time.time()
        seen = 0
        installed = set()
        while time.time() - start < 120 and file_id in self.processes:
            try:
                if os.path.exists(log_path):
                    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                        f.seek(seen)
                        new = f.read()
                        seen = f.tell()
                    if new:
                        m = re.search(r"ModuleNotFoundError: No module named ['\"]([^'\"]+)['\"]", new)
                        if m:
                            missing = m.group(1)
                            if missing not in installed:
                                installed.add(missing)
                                pkg = self._resolve_pip_name(missing)
                                if pkg is None:
                                    continue
                                try:
                                    bot.send_message(user_id, f"📦 Auto-installing `{pkg}`...", parse_mode='Markdown')
                                    ok, _ = self._pip_install(pkg)
                                    if ok:
                                        bot.send_message(user_id, f"✅ Installed `{pkg}`, restarting...", parse_mode='Markdown')
                                        self.restart(file_id)
                                        return
                                except:
                                    pass
                        m2 = re.search(r"Cannot find module ['\"]([^'\"]+)['\"]", new)
                        if m2:
                            missing = m2.group(1)
                            if missing not in installed and not missing.startswith(('.', '/')):
                                installed.add(missing)
                                meta = self.metadata.get(file_id, {})
                                cwd = meta.get('work_dir') or UPLOAD_BOTS_DIR
                                try:
                                    bot.send_message(user_id, f"📦 Installing Node module `{missing}`...", parse_mode='Markdown')
                                    ok, _ = self._npm_install(missing, cwd)
                                    if ok:
                                        bot.send_message(user_id, f"✅ Installed `{missing}`, restarting...", parse_mode='Markdown')
                                        self.restart(file_id)
                                        return
                                except:
                                    pass
            except:
                pass
            time.sleep(1.5)

    def _resolve_pip_name(self, module):
        mapping = {
            'telebot': 'pyTelegramBotAPI', 'telegram': 'python-telegram-bot',
            'aiogram': 'aiogram', 'pyrogram': 'pyrogram', 'telethon': 'telethon',
            'tgcrypto': 'tgcrypto', 'pyromod': 'pyromod', 'bs4': 'beautifulsoup4',
            'PIL': 'Pillow', 'pillow': 'Pillow', 'cv2': 'opencv-python', 'yaml': 'PyYAML',
            'dotenv': 'python-dotenv', 'dateutil': 'python-dateutil', 'OpenSSL': 'pyOpenSSL',
            'nacl': 'pynacl', 'websocket': 'websocket-client', 'google.generativeai': 'google-generativeai',
        }
        top = module.split('.')[0]
        return mapping.get(top, top)

    def _pip_install(self, pkg):
        try:
            r = subprocess.run([sys.executable, '-m', 'pip', 'install', '--upgrade', pkg],
                               capture_output=True, text=True, timeout=300, encoding='utf-8')
            return r.returncode == 0, r.stdout + r.stderr
        except:
            return False, ""

    def _npm_install(self, pkg, cwd):
        try:
            r = subprocess.run(['npm', 'install', pkg], cwd=cwd, capture_output=True, text=True, timeout=300, encoding='utf-8')
            return r.returncode == 0, r.stdout + r.stderr
        except:
            return False, ""

    def get_process_info(self, file_id):
        with self.lock:
            if file_id not in self.processes:
                return None
            proc = self.processes[file_id]
            meta = self.metadata.get(file_id, {})
            try:
                p = psutil.Process(proc.pid)
                cpu = p.cpu_percent(interval=0.1)
                mem = p.memory_info().rss / (1024*1024)
                status = p.status()
            except:
                cpu = mem = status = 0
            return {'pid': proc.pid, 'cpu': cpu, 'mem': mem, 'status': status,
                    'start_time': meta.get('start_time'), 'stored_name': meta.get('stored_name'),
                    'user_id': meta.get('user_id')}

script_manager = ScriptManager()

# ============================================================================
# TELEGRAM BOT – EMOJI UI
# ============================================================================

# pending upload state: user_id -> {'mode': 'file'|'folder', 'pid': int|None}
pending_upload = {}

def main_menu_markup(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton('📢 Updates Channel', url=UPDATE_CHANNEL),
        types.InlineKeyboardButton('⬆️ Upload', callback_data='upload'),
        types.InlineKeyboardButton('📂 My Files', callback_data='check_files'),
        types.InlineKeyboardButton('⚡ Speed', callback_data='speed'),
        types.InlineKeyboardButton('🌐 Website', callback_data='website'),
        types.InlineKeyboardButton('👑 Contact Owner', url=f'https://t.me/{YOUR_USERNAME.replace("@","")}')
    ]
    if db.is_admin(user_id):
        admin_buttons = [
            types.InlineKeyboardButton('💳 Subscriptions', callback_data='subscription'),
            types.InlineKeyboardButton('📊 Statistics', callback_data='stats'),
            types.InlineKeyboardButton('🔒 Lock Bot' if not bot_locked else '🔓 Unlock Bot',
                                     callback_data='lock_bot' if not bot_locked else 'unlock_bot'),
            types.InlineKeyboardButton('📣 Broadcast', callback_data='broadcast'),
            types.InlineKeyboardButton('🛠 Admin Panel', callback_data='admin_panel'),
            types.InlineKeyboardButton('▶️ Run All Scripts', callback_data='run_all'),
            types.InlineKeyboardButton('🔄 Restart Bot', callback_data='restart_bot_self'),
            types.InlineKeyboardButton('📨 Send All', callback_data='sendall'),
            types.InlineKeyboardButton('🖥 System Info', callback_data='sysinfo'),
        ]
        markup.add(buttons[0])
        markup.add(buttons[1], buttons[2])
        markup.add(buttons[3], admin_buttons[0])
        markup.add(admin_buttons[1], admin_buttons[3])
        markup.add(admin_buttons[2], admin_buttons[5])
        markup.add(admin_buttons[6])
        markup.add(admin_buttons[4], admin_buttons[7])
        markup.add(admin_buttons[8])
        markup.add(buttons[4], buttons[5])
    else:
        markup.add(buttons[0])
        markup.add(buttons[1], buttons[2])
        markup.add(buttons[3], buttons[4])
        markup.add(buttons[5])
    return markup

def reply_keyboard(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    if db.is_admin(user_id):
        layout = [
            ["📢 Updates Channel"],
            ["⬆️ Upload", "📂 My Files"],
            ["⚡ Speed", "📊 Statistics"],
            ["💳 Subscriptions", "📣 Broadcast"],
            ["🔒 Lock Bot", "▶️ Run All Scripts"],
            ["🔄 Restart Bot"],
            ["🛠 Admin Panel", "👑 Contact Owner"],
            ["🌐 Website", "📨 Send All"],
            ["🖥 System Info"]
        ]
    else:
        layout = [
            ["📢 Updates Channel"],
            ["⬆️ Upload", "📂 My Files"],
            ["⚡ Speed", "📊 Statistics"],
            ["🌐 Website", "👑 Contact Owner"]
        ]
    for row in layout:
        markup.add(*[types.KeyboardButton(t) for t in row])
    return markup

# ---- Start ----
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    user_id = message.from_user.id
    db.add_active_user(user_id)
    db.update_user_info(user_id, message.from_user.username, message.from_user.first_name)
    db.get_user_token(user_id)
    sub = db.get_subscription(user_id)
    if user_id == OWNER_ID:
        status = "👑 Owner"
    elif db.is_admin(user_id):
        status = "🛡 Admin"
    elif sub and sub > datetime.now():
        days = (sub - datetime.now()).days
        status = f"💎 Premium ({days}d left)"
    else:
        status = "🆓 Free"
    files = count_user_files(user_id)
    limit = get_user_limit(user_id)
    limit_str = "∞" if limit == float('inf') else str(limit)
    text = (f"👋 Welcome, {message.from_user.first_name}!\n\n"
            f"🆔 ID: `{user_id}`\n"
            f"⭐ Status: {status}\n"
            f"📄 Files: {files} / {limit_str}\n\n"
            f"🚀 Host Python / JS bots easily.\n"
            f"📁 Folders = Projects — put many files inside one folder!\n"
            f"🌐 Website: {db.get_setting('website_url', 'http://localhost:8080')}\n\n"
            f"👇 Use the buttons below.")
    bot.send_message(message.chat.id, text, reply_markup=reply_keyboard(user_id), parse_mode='Markdown')

# ---- Upload flow ----
@bot.message_handler(commands=['upload'])
@bot.message_handler(func=lambda m: m.text == "⬆️ Upload")
def upload_start(message):
    user_id = message.from_user.id
    if bot_locked and not db.is_admin(user_id):
        bot.reply_to(message, "🔒 Bot is locked.")
        return
    limit = get_user_limit(user_id)
    if count_user_files(user_id) >= limit:
        bot.reply_to(message, f"⚠️ File limit reached ({limit}).")
        return
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📄 File", callback_data='upmode_file'),
        types.InlineKeyboardButton("📁 Folder", callback_data='upmode_folder')
    )
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data='back_main'))
    bot.reply_to(message,
                 "⬆️ What do you want to upload?\n\n"
                 "📄 File — a single file (.py / .js / .txt / .json / anything)\n"
                 "📁 Folder — a project folder. You can keep adding files into it!",
                 reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == 'upmode_file')
def upmode_file(call):
    user_id = call.from_user.id
    pending_upload[user_id] = {'mode': 'file', 'pid': 0}
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Cancel", callback_data='back_main'))
    bot.edit_message_text("📄 File mode selected.\n\nNow send me any file:\n"
                          "🐍 .py  🟨 .js  📄 .txt  🧾 .json  🗜 .zip — everything is OK!\n"
                          "(Nothing runs automatically — you start it yourself from 📂 My Files)",
                          call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

def _folder_pick_markup(projects, prefix):
    markup = types.InlineKeyboardMarkup(row_width=2)
    for pid, pname, total, running in projects:
        markup.add(types.InlineKeyboardButton(f"📁 {pname} ({total} files)", callback_data=f'{prefix}{pid}'))
    markup.add(types.InlineKeyboardButton("➕ New Folder", callback_data=f'{prefix}new'))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data='upload'))
    return markup

@bot.callback_query_handler(func=lambda c: c.data == 'upmode_folder')
def upmode_folder(call):
    user_id = call.from_user.id
    projects = db.get_user_projects(user_id)
    markup = _folder_pick_markup(projects, 'upfold_')
    text = ("📁 Folder upload mode.\n\n"
            "👇 Choose an existing folder, or create a new one.\n"
            "ℹ️ Files you send next will be added INSIDE that folder — "
            "you can add unlimited files (.py, .txt, .json, ...) into the same folder.")
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == 'upfold_new')
def upfold_new(call):
    msg = bot.edit_message_text("✏️ Send the new folder name (e.g. `sas`):",
                                call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    bot.register_next_step_handler(msg, process_new_folder_name)
    bot.answer_callback_query(call.id)

def process_new_folder_name(message):
    user_id = message.from_user.id
    name = sanitize_folder_name(message.text or '')
    if not name:
        msg = bot.reply_to(message, "⚠️ Invalid name. Send a folder name (letters/numbers only):")
        bot.register_next_step_handler(msg, process_new_folder_name)
        return
    pid = db.get_or_create_project(user_id, name)
    os.makedirs(project_dir(user_id, name), exist_ok=True)
    pending_upload[user_id] = {'mode': 'folder', 'pid': pid}
    existed = db.get_project_files(pid)
    note = f"📁 Folder `{name}` already exists — new files will be added inside it." if existed \
           else f"✅ Folder `{name}` created!"
    bot.reply_to(message,
                 f"{note}\n\n📤 Now send me files one by one — they all go into 📁 `{name}`.\n"
                 f"Any type is OK: .py .js .txt .json .db .env ...\n"
                 f"When you're done, open 📂 My Files to run your bot.",
                 parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data.startswith('upfold_') and c.data != 'upfold_new')
def upfold_pick(call):
    user_id = call.from_user.id
    pid = int(call.data[len('upfold_'):])
    proj = db.get_project(pid)
    if not proj or proj[1] != user_id:
        bot.answer_callback_query(call.id, "❌ Folder not found.", show_alert=True)
        return
    pending_upload[user_id] = {'mode': 'folder', 'pid': pid}
    bot.edit_message_text(f"📁 Folder `{proj[2]}` selected.\n\n"
                          f"📤 Now send me files — they will be added inside `{proj[2]}`.\n"
                          f"Any type is OK (.py, .txt, .json, .db, ...). Send as many as you want!",
                          call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    bot.answer_callback_query(call.id, f"📁 {proj[2]}")

# ---- Handle any document ----
@bot.message_handler(content_types=['document'])
def handle_file_upload(message):
    user_id = message.from_user.id
    if bot_locked and not db.is_admin(user_id):
        bot.reply_to(message, "🔒 Bot is locked.")
        return
    limit = get_user_limit(user_id)
    if count_user_files(user_id) >= limit:
        bot.reply_to(message, f"⚠️ File limit reached ({limit}).")
        return
    doc = message.document
    if doc.file_size > 20 * 1024 * 1024:
        bot.reply_to(message, "⚠️ File too large (max 20MB).")
        return
    st = pending_upload.get(user_id, {'mode': 'file', 'pid': 0})
    pid = st.get('pid', 0)
    orig_name = doc.file_name or f"file_{int(time.time())}"
    ext = os.path.splitext(orig_name)[1].lower()
    ftype = detect_type(orig_name)

    try:
        file_info = bot.get_file(doc.file_id)
        content = bot.download_file(file_info.file_path)
    except Exception as e:
        bot.reply_to(message, f"❌ Download failed: {e}")
        return

    # ---- zip handling ----
    if ext == '.zip':
        # zip into chosen folder, or ask which folder to use
        if pid:
            _handle_zip(message, user_id, pid, content, orig_name)
        else:
            projects = db.get_user_projects(user_id)
            pending_upload[user_id] = {'mode': 'zipwait', 'pid': 0, 'data': content, 'name': orig_name}
            markup = _folder_pick_markup(projects, 'zipfold_')
            bot.reply_to(message,
                         "🗜 Zip received!\n\n👇 Which folder should I put it in?\n"
                         "(All zip contents will be extracted inside that folder — existing files are kept)",
                         reply_markup=markup)
        return

    # ---- normal file ----
    saved = _save_single_file(user_id, pid, orig_name, content)
    if not saved:
        bot.reply_to(message, "❌ Failed to save file.")
        return
    proj = db.get_project(pid) if pid else None
    pname = proj[2] if proj else None
    place = f"📁 {pname}" if pname else "📄 root"
    icon = ext_icon(orig_name, ftype)
    run_hint = "\n▶️ Start it anytime from 📂 My Files!" if is_runnable(ftype) else ""
    bot.reply_to(message,
                 f"✅ Uploaded!\n\n"
                 f"{icon} File: `{orig_name}`\n"
                 f"📦 Size: {format_bytes(doc.file_size)}\n"
                 f"📍 Saved to: {place}"
                 f"{run_hint}", parse_mode='Markdown')

def _save_single_file(user_id, pid, orig_name, content):
    """Save one file into project folder (pid) or user root. Dedupes by replacing same name."""
    safe_name = os.path.basename(orig_name).replace('\\', '')
    if pid:
        proj = db.get_project(pid)
        if not proj:
            return False
        dest_dir = project_dir(user_id, proj[2])
        stored_name = safe_name
    else:
        dest_dir = os.path.join(UPLOAD_BOTS_DIR, str(user_id))
        stored_name = safe_name
    os.makedirs(dest_dir, exist_ok=True)
    file_path = os.path.join(dest_dir, stored_name)
    # if a file with the same name exists in this project, update it instead of duplicating
    if pid and db.file_exists_in_project(pid, stored_name):
        row = None
        for fid, disp, sname, ftype, running, _ in db.get_project_files(pid):
            if sname == stored_name:
                row = (fid, running)
                break
        if row:
            fid, running = row
            if running:
                script_manager.stop(fid)
            try:
                with open(file_path, 'wb') as f:
                    f.write(content)
            except:
                return False
            db.log_action(user_id, 'update_file', f'Updated {stored_name}')
            return True
    try:
        with open(file_path, 'wb') as f:
            f.write(content)
    except:
        return False
    db.add_file(user_id, pid, os.path.splitext(safe_name)[0], stored_name, detect_type(safe_name))
    db.log_action(user_id, 'upload', f'Uploaded {safe_name}')
    return True

# zip waiting for folder choice
@bot.callback_query_handler(func=lambda c: c.data == 'zipfold_new')
def zipfold_new(call):
    user_id = call.from_user.id
    st = pending_upload.get(user_id, {})
    if st.get('mode') != 'zipwait':
        bot.answer_callback_query(call.id, "Session expired. Upload the zip again.", show_alert=True)
        return
    msg = bot.edit_message_text("✏️ Send the folder name for this zip (e.g. `sas`):",
                                call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    bot.register_next_step_handler(msg, process_zip_folder_name)
    bot.answer_callback_query(call.id)

def process_zip_folder_name(message):
    user_id = message.from_user.id
    name = sanitize_folder_name(message.text or '')
    if not name:
        msg = bot.reply_to(message, "⚠️ Invalid name. Send a folder name:")
        bot.register_next_step_handler(msg, process_zip_folder_name)
        return
    pid = db.get_or_create_project(user_id, name)
    st = pending_upload.pop(user_id, None)
    if not st or 'data' not in st:
        bot.reply_to(message, "⚠️ Session expired. Upload the zip again.")
        return
    _extract_zip_into_project(message, user_id, pid, st['data'], st['name'])

@bot.callback_query_handler(func=lambda c: c.data.startswith('zipfold_') and c.data != 'zipfold_new')
def zipfold_pick(call):
    user_id = call.from_user.id
    st = pending_upload.get(user_id, {})
    if st.get('mode') != 'zipwait':
        bot.answer_callback_query(call.id, "Session expired. Upload the zip again.", show_alert=True)
        return
    pid = int(call.data[len('zipfold_'):])
    proj = db.get_project(pid)
    if not proj or proj[1] != user_id:
        bot.answer_callback_query(call.id, "❌ Folder not found.", show_alert=True)
        return
    pending_upload.pop(user_id, None)
    bot.edit_message_text(f"🗜 Extracting into 📁 `{proj[2]}`...",
                          call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    bot.answer_callback_query(call.id)
    _extract_zip_into_project(call.message, user_id, pid, st['data'], st['name'])

def _handle_zip(message, user_id, pid, content, orig_name):
    proj = db.get_project(pid)
    bot.reply_to(message, f"🗜 Extracting `{orig_name}` into 📁 `{proj[2]}`...", parse_mode='Markdown')
    _extract_zip_into_project(message, user_id, pid, content, orig_name)

def _extract_zip_into_project(message, user_id, pid, content, orig_name):
    """Extract full zip into the project folder. Files merge, same names overwritten. Nothing auto-runs."""
    proj = db.get_project(pid)
    if not proj:
        bot.send_message(message.chat.id, "❌ Folder not found.")
        return
    pdir = project_dir(user_id, proj[2])
    os.makedirs(pdir, exist_ok=True)
    tmp_zip = os.path.join(tempfile.mkdtemp(), 'up.zip')
    try:
        with open(tmp_zip, 'wb') as f:
            f.write(content)
        temp_dir = tempfile.mkdtemp()
        safe_extract_zip(tmp_zip, temp_dir)
        # flatten single top-level wrapper folder
        entries = [e for e in os.listdir(temp_dir) if e != '__MACOSX']
        src_root = temp_dir
        if len(entries) == 1 and os.path.isdir(os.path.join(temp_dir, entries[0])):
            src_root = os.path.join(temp_dir, entries[0])
        added = 0
        for dirpath, dirnames, filenames in os.walk(src_root):
            dirnames[:] = [d for d in dirnames if d not in ('__pycache__', 'node_modules', '.git')]
            rel_dir = os.path.relpath(dirpath, src_root)
            dest_dir = pdir if rel_dir == '.' else os.path.join(pdir, rel_dir)
            os.makedirs(dest_dir, exist_ok=True)
            for fn in filenames:
                src = os.path.join(dirpath, fn)
                rel = fn if rel_dir == '.' else os.path.join(rel_dir, fn)
                dest = os.path.join(dest_dir, fn)
                shutil.copy2(src, dest)
                # register top-level runnable/data files in db (dedupe by name)
                if not db.file_exists_in_project(pid, rel):
                    db.add_file(user_id, pid, os.path.splitext(fn)[0], rel, detect_type(fn))
                    added += 1
        db.log_action(user_id, 'upload_zip', f'Extracted {orig_name} into {proj[2]}')
        bot.send_message(message.chat.id,
                         f"✅ Zip extracted into 📁 `{proj[2]}`!\n\n"
                         f"📄 New files registered: {added}\n"
                         f"▶️ Nothing runs automatically — start any .py/.js from 📂 My Files.",
                         parse_mode='Markdown')
    except zipfile.BadZipFile:
        bot.send_message(message.chat.id, "❌ Not a valid zip file.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Zip error: {e}")
    finally:
        shutil.rmtree(os.path.dirname(tmp_zip), ignore_errors=True)
        try: shutil.rmtree(temp_dir, ignore_errors=True)
        except: pass

# ---- My Files: project list ----
@bot.message_handler(commands=['files'])
@bot.message_handler(func=lambda m: m.text == "📂 My Files")
def check_files(message):
    user_id = message.from_user.id
    projects = db.get_user_projects(user_id)
    root_files = [f for f in db.get_user_files(user_id) if not _file_pid(user_id, f[0])]
    if not projects and not root_files:
        bot.reply_to(message, "📭 No files uploaded yet.\nUse ⬆️ Upload to add your first file!")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for pid, pname, total, running in projects:
        dot = "🟢" if running else "⚪"
        markup.add(types.InlineKeyboardButton(f"{dot} 📁 {pname} ({total} files)", callback_data=f'proj_{pid}'))
    for fid, disp, stored, ftype, running, _ in root_files:
        dot = "🟢" if running else "⚪"
        markup.add(types.InlineKeyboardButton(f"{dot} {ext_icon(stored, ftype)} {disp}", callback_data=f'file_{fid}'))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data='back_main'))
    total_p = len(projects)
    bot.reply_to(message, f"📂 Your Projects ({total_p} total)\n\nSelect a project:", reply_markup=markup)

def _file_pid(user_id, fid):
    row = db.get_file_row(fid)
    return row[2] if row else 0

# ---- Open a project: list its files ----
@bot.callback_query_handler(func=lambda c: c.data.startswith('proj_'))
def project_view(call):
    pid = int(call.data.split('_')[1])
    user_id = call.from_user.id
    proj = db.get_project(pid)
    if not proj or (proj[1] != user_id and not db.is_admin(user_id)):
        bot.answer_callback_query(call.id, "⛔ Not your folder.", show_alert=True)
        return
    files = db.get_project_files(pid)
    running = sum(1 for f in files if f[4])
    markup = types.InlineKeyboardMarkup(row_width=1)
    for fid, disp, stored, ftype, frun, _ in files:
        dot = "🟢" if frun else "⚪"
        markup.add(types.InlineKeyboardButton(f"{dot} {ext_icon(stored, ftype)} {disp}", callback_data=f'file_{fid}'))
    markup.add(types.InlineKeyboardButton("➕ Add Files Here", callback_data=f'upfold_{pid}'))
    markup.add(types.InlineKeyboardButton("🔙 Back to Projects", callback_data='check_files'),
               types.InlineKeyboardButton("🗑 Delete Project", callback_data=f'delproj_{pid}'))
    try:
        bot.edit_message_text(f"📁 Project: {proj[2]}\n\n"
                              f"📄 Files: {len(files)}\n"
                              f"🟢 Running: {running}\n"
                              f"⚪ Stopped: {len(files)-running}\n\n"
                              f"Select an item:",
                              call.message.chat.id, call.message.message_id, reply_markup=markup)
    except Exception:
        pass
    bot.answer_callback_query(call.id)

# ---- Delete whole project ----
@bot.callback_query_handler(func=lambda c: c.data.startswith('delproj_'))
def del_project(call):
    pid = int(call.data.split('_')[1])
    user_id = call.from_user.id
    proj = db.get_project(pid)
    if not proj or (proj[1] != user_id and not db.is_admin(user_id)):
        bot.answer_callback_query(call.id, "⛔ Not your folder.", show_alert=True)
        return
    for fid, disp, stored, ftype, frun, _ in db.get_project_files(pid):
        if script_manager.is_running(fid):
            script_manager.stop(fid)
    db.delete_project(pid, proj[1])
    db.log_action(user_id, 'del_project', f'Deleted project {proj[2]}')
    bot.answer_callback_query(call.id, f"🗑 Deleted {proj[2]}")
    call.message.from_user = call.from_user
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    check_files(call.message)

# ---- File control ----
@bot.callback_query_handler(func=lambda c: c.data.startswith('file_'))
def file_control(call):
    fid = int(call.data.split('_')[1])
    user_id = call.from_user.id
    row = db.get_file_row(fid)
    if not row or (row[1] != user_id and not db.is_admin(user_id)):
        bot.answer_callback_query(call.id, "⛔ Not your file.", show_alert=True)
        return
    _, owner, pid, disp, stored, ftype, running = row
    runnable = is_runnable(ftype)
    markup = types.InlineKeyboardMarkup(row_width=3)
    if runnable:
        if running:
            markup.add(
                types.InlineKeyboardButton("⏹ Stop", callback_data=f'stop_{fid}'),
                types.InlineKeyboardButton("🔄 Restart", callback_data=f'restart_{fid}'),
                types.InlineKeyboardButton("📜 Logs", callback_data=f'logs_{fid}'),
                types.InlineKeyboardButton("🗑 Delete", callback_data=f'delete_{fid}'),
                types.InlineKeyboardButton("ℹ️ Process Info", callback_data=f'proc_{fid}')
            )
        else:
            markup.add(
                types.InlineKeyboardButton("▶️ Start", callback_data=f'start_{fid}'),
                types.InlineKeyboardButton("📜 Logs", callback_data=f'logs_{fid}'),
                types.InlineKeyboardButton("🗑 Delete", callback_data=f'delete_{fid}')
            )
    else:
        markup.add(types.InlineKeyboardButton("🗑 Delete", callback_data=f'delete_{fid}'))
    back_cb = f'proj_{pid}' if pid else 'check_files'
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data=back_cb))
    icon = ext_icon(stored, ftype)
    kind = "runnable script" if runnable else "data file (cannot run — it's used by your scripts)"
    try:
        bot.edit_message_text(f"{icon} {disp} ({ftype})\n"
                              f"Type: {kind}\n"
                              f"Status: {'🟢 Running' if running else '⚪ Stopped'}",
                              call.message.chat.id, call.message.message_id,
                              reply_markup=markup)
    except Exception:
        pass
    bot.answer_callback_query(call.id)

# ---- Action callbacks ----
@bot.callback_query_handler(func=lambda c: c.data.startswith(('start_','stop_','restart_','delete_','logs_','proc_')))
def script_actions(call):
    action, fid = call.data.split('_')[0], int(call.data.split('_')[1])
    user_id = call.from_user.id
    row = db.get_file_row(fid)
    if not row:
        bot.answer_callback_query(call.id, "❌ File not found.", show_alert=True)
        return
    _, owner, pid, disp, stored, ftype, running = row
    if owner != user_id and not db.is_admin(user_id):
        bot.answer_callback_query(call.id, "⛔ Permission denied.", show_alert=True)
        return
    if action in ('start', 'restart') and not is_runnable(ftype):
        bot.answer_callback_query(call.id, "ℹ️ This file type can't run.", show_alert=True)
        return
    if action == 'start':
        if script_manager.is_running(fid):
            bot.answer_callback_query(call.id, "ℹ️ Already running.", show_alert=True)
            return
        bot.answer_callback_query(call.id, "⏳ Starting...")
        if script_manager.start(fid):
            db.log_action(user_id, 'start', f'Started file {fid}')
        else:
            bot.answer_callback_query(call.id, "❌ Failed to start.", show_alert=True)
        file_control(call)
    elif action == 'stop':
        if script_manager.is_running(fid):
            if script_manager.stop(fid):
                bot.answer_callback_query(call.id, "⏹ Stopped.")
                db.log_action(user_id, 'stop', f'Stopped file {fid}')
            else:
                bot.answer_callback_query(call.id, "❌ Failed to stop.", show_alert=True)
        else:
            bot.answer_callback_query(call.id, "ℹ️ Not running.", show_alert=True)
        file_control(call)
    elif action == 'restart':
        bot.answer_callback_query(call.id, "🔄 Restarting...")
        if script_manager.restart(fid):
            db.log_action(user_id, 'restart', f'Restarted file {fid}')
        else:
            bot.answer_callback_query(call.id, "❌ Restart failed.", show_alert=True)
        file_control(call)
    elif action == 'delete':
        if script_manager.is_running(fid):
            script_manager.stop(fid)
        db.delete_file(fid)
        db.log_action(user_id, 'delete', f'Deleted file {fid}')
        bot.answer_callback_query(call.id, "🗑 Deleted.")
        if pid:
            call.data = f'proj_{pid}'
            project_view(call)
        else:
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception:
                pass
            call.message.from_user = call.from_user
            check_files(call.message)
    elif action == 'logs':
        full = file_full_path(owner, pid, stored)
        log_path = os.path.join(os.path.dirname(full), os.path.splitext(os.path.basename(full))[0] + '.log') if full else None
        if not log_path or not os.path.exists(log_path):
            bot.answer_callback_query(call.id, "📭 No logs yet.", show_alert=True)
            return
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            if len(content) > 4000:
                content = content[-4000:]
            if not content.strip():
                content = "(log file is empty)"
            bot.send_message(call.message.chat.id, f"📜 Logs for `{os.path.basename(stored)}`:\n```\n{content}\n```",
                             parse_mode='Markdown')
            bot.answer_callback_query(call.id)
        except Exception as e:
            bot.answer_callback_query(call.id, f"❌ Error reading logs: {e}", show_alert=True)
    elif action == 'proc':
        pinfo = script_manager.get_process_info(fid)
        if not pinfo:
            bot.answer_callback_query(call.id, "ℹ️ Process not running.", show_alert=True)
            return
        txt = (f"ℹ️ Process Info — {pinfo['stored_name']}\n"
               f"🆔 PID: {pinfo['pid']}\n"
               f"🔥 CPU: {pinfo['cpu']:.1f}%\n"
               f"💾 Memory: {pinfo['mem']:.1f} MB\n"
               f"📶 Status: {pinfo['status']}\n"
               f"🕐 Started: {pinfo['start_time'].strftime('%Y-%m-%d %H:%M:%S')}")
        bot.send_message(call.message.chat.id, txt)
        bot.answer_callback_query(call.id)

# ---- Statistics ----
@bot.message_handler(commands=['stats'])
@bot.message_handler(func=lambda m: m.text == "📊 Statistics")
def stats(message):
    total_users = db.get_user_count()
    total_files = db.get_file_count()
    running = len(script_manager.processes)
    sys_stats = get_system_stats()
    txt = (f"📊 Statistics\n\n"
           f"👥 Total Users: {total_users}\n"
           f"📄 Total Files: {total_files}\n"
           f"🟢 Running Scripts: {running}\n"
           f"🔒 Bot locked: {'Yes' if bot_locked else 'No'}\n"
           f"🔥 CPU: {sys_stats['cpu']:.1f}%\n"
           f"💾 RAM: {format_bytes(sys_stats['memory_used'])} / {format_bytes(sys_stats['memory_total'])}\n"
           f"💿 Disk: {format_bytes(sys_stats['disk_used'])} / {format_bytes(sys_stats['disk_total'])}")
    bot.reply_to(message, txt)

# ---- Speed ----
@bot.message_handler(commands=['speed'])
@bot.message_handler(func=lambda m: m.text == "⚡ Speed")
def speed(message):
    st = time.time()
    msg = bot.reply_to(message, "⚡ Testing...")
    latency = round((time.time() - st) * 1000, 2)
    bot.edit_message_text(f"⚡ Speed\nResponse: {latency} ms",
                          message.chat.id, msg.message_id)

# ---- Contact Owner ----
@bot.message_handler(commands=['contact'])
@bot.message_handler(func=lambda m: m.text == "👑 Contact Owner")
def contact(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("👑 Contact", url=f'https://t.me/{YOUR_USERNAME.replace("@","")}'))
    bot.reply_to(message, "👑 Click to contact Owner:", reply_markup=markup)

# ---- Website ----
@bot.message_handler(commands=['website', 'web'])
@bot.message_handler(func=lambda m: m.text == "🌐 Website")
def website_link(message):
    user_id = message.from_user.id
    token = db.get_user_token(user_id)
    url = db.get_setting('website_url', 'http://139.180.139.82:8080')
    bot.reply_to(message, f"🌐 Web Dashboard\n\n🔗 URL: {url}\n🔑 Your token: `{token}`\n\nUse this token to login.",
                 parse_mode='Markdown')

# ---- Subscriptions ----
@bot.message_handler(commands=['subscription'])
@bot.message_handler(func=lambda m: m.text == "💳 Subscriptions" and db.is_admin(m.from_user.id))
def sub_menu(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("➕ Add Sub", callback_data='add_sub'),
               types.InlineKeyboardButton("➖ Remove Sub", callback_data='rem_sub'))
    markup.add(types.InlineKeyboardButton("🔍 Check Sub", callback_data='check_sub'))
    markup.add(types.InlineKeyboardButton("📋 List Subs", callback_data='list_subs'))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data='back_main'))
    bot.reply_to(message, "💳 Subscription Management", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data in ('add_sub','rem_sub','check_sub','list_subs'))
def sub_actions(call):
    if not db.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ Admin only.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    if call.data == 'add_sub':
        msg = bot.send_message(call.message.chat.id, "➕ Enter: `user_id days` (e.g., 12345 30)\n/cancel to abort.", parse_mode='Markdown')
        bot.register_next_step_handler(msg, process_add_sub)
    elif call.data == 'rem_sub':
        msg = bot.send_message(call.message.chat.id, "➖ Enter user_id to remove subscription.\n/cancel to abort.")
        bot.register_next_step_handler(msg, process_rem_sub)
    elif call.data == 'check_sub':
        msg = bot.send_message(call.message.chat.id, "🔍 Enter user_id to check.\n/cancel to abort.")
        bot.register_next_step_handler(msg, process_check_sub)
    elif call.data == 'list_subs':
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute('SELECT user_id, expiry FROM subscriptions')
        rows = c.fetchall()
        conn.close()
        if not rows:
            txt = "📭 No subscriptions."
        else:
            txt = "💳 Active Subscriptions:\n"
            for uid, exp in rows:
                try:
                    exp_dt = datetime.fromisoformat(exp)
                    if exp_dt > datetime.now():
                        txt += f"✅ `{uid}`: {exp_dt.strftime('%Y-%m-%d')} ({(exp_dt-datetime.now()).days} d left)\n"
                    else:
                        txt += f"❌ `{uid}`: EXPIRED\n"
                except:
                    txt += f"⚠️ `{uid}`: invalid date\n"
        bot.send_message(call.message.chat.id, txt, parse_mode='Markdown')

def process_add_sub(message):
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Cancelled."); return
    try:
        parts = message.text.split()
        uid, days = int(parts[0]), int(parts[1])
        cur = db.get_subscription(uid)
        base = cur if cur and cur > datetime.now() else datetime.now()
        new_exp = base + timedelta(days=days)
        db.set_subscription(uid, new_exp)
        db.log_action(message.from_user.id, 'add_sub', f'Added {days}d for {uid}')
        bot.reply_to(message, f"✅ Subscription for `{uid}` extended to {new_exp.strftime('%Y-%m-%d')}", parse_mode='Markdown')
    except:
        bot.reply_to(message, "⚠️ Invalid format. Use: `user_id days`", parse_mode='Markdown')

def process_rem_sub(message):
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Cancelled."); return
    try:
        uid = int(message.text.strip())
        db.remove_subscription(uid)
        db.log_action(message.from_user.id, 'rem_sub', f'Removed sub for {uid}')
        bot.reply_to(message, f"✅ Removed subscription for `{uid}`", parse_mode='Markdown')
    except:
        bot.reply_to(message, "⚠️ Invalid user_id.")

def process_check_sub(message):
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Cancelled."); return
    try:
        uid = int(message.text.strip())
        exp = db.get_subscription(uid)
        if exp and exp > datetime.now():
            bot.reply_to(message, f"✅ User `{uid}` active until {exp.strftime('%Y-%m-%d')} ({(exp-datetime.now()).days} days left)", parse_mode='Markdown')
        else:
            bot.reply_to(message, f"ℹ️ User `{uid}` has no active subscription.", parse_mode='Markdown')
    except:
        bot.reply_to(message, "⚠️ Invalid user_id.")

# ---- Broadcast ----
@bot.message_handler(commands=['broadcast'])
@bot.message_handler(func=lambda m: m.text == "📣 Broadcast" and db.is_admin(m.from_user.id))
def broadcast_start(message):
    msg = bot.reply_to(message, "📣 Send message to broadcast.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_broadcast)

def process_broadcast(message):
    if message.text and message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Cancelled."); return
    content = message.text or "Media message"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Confirm", callback_data=f'bcast_confirm_{message.message_id}'),
               types.InlineKeyboardButton("❌ Cancel", callback_data='bcast_cancel'))
    bot.reply_to(message, f"📣 Broadcast to all users?\n\nPreview:\n```\n{content[:300]}\n```",
                 parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith('bcast_'))
def bcast_confirm(call):
    if not db.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ Admin only.", show_alert=True); return
    if call.data == 'bcast_cancel':
        bot.answer_callback_query(call.id, "❌ Cancelled.")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        return
    bot.answer_callback_query(call.id, "📣 Broadcasting...")
    orig = call.message.reply_to_message
    if not orig:
        bot.edit_message_text("❌ Original message lost.", call.message.chat.id, call.message.message_id)
        return
    users = db.get_all_users()
    bot.edit_message_text(f"📣 Broadcasting to {len(users)} users...", call.message.chat.id, call.message.message_id)
    threading.Thread(target=do_broadcast, args=(orig, call.message.chat.id), daemon=True).start()

def do_broadcast(orig_msg, admin_chat):
    sent = failed = 0
    for uid in db.get_all_users():
        try:
            bot.copy_message(uid, orig_msg.chat.id, orig_msg.message_id)
            sent += 1
        except:
            failed += 1
        time.sleep(0.05)
    bot.send_message(admin_chat, f"📣 Broadcast done.\n✅ Sent: {sent}\n❌ Failed: {failed}")

# ---- Send All ----
@bot.message_handler(commands=['sendall'])
@bot.message_handler(func=lambda m: m.text == "📨 Send All" and db.is_admin(m.from_user.id))
def sendall_start(message):
    msg = bot.reply_to(message, "📨 Reply to a message to send to all users.\nUse /sendall -copy to copy instead of forward.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_sendall)

def process_sendall(message):
    if message.text and message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Cancelled."); return
    copy_mode = False
    if message.text and '-copy' in message.text:
        copy_mode = True
    if not message.reply_to_message:
        bot.reply_to(message, "⚠️ Please reply to a message.")
        return
    orig = message.reply_to_message
    users = db.get_all_users()
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Confirm Send", callback_data=f'sendall_confirm_{orig.message_id}_{int(copy_mode)}'),
               types.InlineKeyboardButton("❌ Cancel", callback_data='sendall_cancel'))
    bot.reply_to(message, f"📨 Send to {len(users)} users? {'Copy' if copy_mode else 'Forward'} mode.",
                 reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith('sendall_'))
def sendall_confirm(call):
    if not db.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ Admin only.", show_alert=True); return
    if call.data == 'sendall_cancel':
        bot.answer_callback_query(call.id, "❌ Cancelled.")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        return
    parts = call.data.split('_')
    copy_mode = bool(int(parts[3]))
    bot.answer_callback_query(call.id, "📨 Sending...")
    orig = call.message.reply_to_message
    if not orig:
        bot.edit_message_text("❌ Original message lost.", call.message.chat.id, call.message.message_id)
        return
    users = db.get_all_users()
    bot.edit_message_text(f"📨 Sending to {len(users)} users...", call.message.chat.id, call.message.message_id)
    threading.Thread(target=do_sendall, args=(orig, copy_mode, call.message.chat.id), daemon=True).start()

def do_sendall(orig, copy_mode, admin_chat):
    sent = failed = 0
    for uid in db.get_all_users():
        try:
            if copy_mode:
                bot.copy_message(uid, orig.chat.id, orig.message_id)
            else:
                bot.forward_message(uid, orig.chat.id, orig.message_id)
            sent += 1
        except:
            failed += 1
        time.sleep(0.05)
    bot.send_message(admin_chat, f"📨 Done.\n✅ Sent: {sent}\n❌ Failed: {failed}")

# ---- Admin Panel ----
@bot.message_handler(commands=['adminpanel'])
@bot.message_handler(func=lambda m: m.text == "🛠 Admin Panel" and db.is_admin(m.from_user.id))
def admin_panel(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("➕ Add Admin", callback_data='add_admin'),
               types.InlineKeyboardButton("➖ Remove Admin", callback_data='rem_admin'))
    markup.add(types.InlineKeyboardButton("📋 List Admins", callback_data='list_admin'))
    markup.add(types.InlineKeyboardButton("📜 Bot Logs", callback_data='bot_logs'))
    markup.add(types.InlineKeyboardButton("⚙️ Settings", callback_data='bot_settings'))
    markup.add(types.InlineKeyboardButton("🔄 Restart Bot", callback_data='restart_bot_self'))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data='back_main'))
    bot.reply_to(message, "🛠 Admin Panel", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data in ('add_admin','rem_admin','list_admin','bot_logs','bot_settings'))
def admin_actions(call):
    if not db.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ Admin only.", show_alert=True); return
    bot.answer_callback_query(call.id)
    if call.data == 'add_admin':
        msg = bot.send_message(call.message.chat.id, "➕ Enter user_id to promote.\n/cancel.")
        bot.register_next_step_handler(msg, process_add_admin)
    elif call.data == 'rem_admin':
        msg = bot.send_message(call.message.chat.id, "➖ Enter user_id to demote.\n/cancel.")
        bot.register_next_step_handler(msg, process_rem_admin)
    elif call.data == 'list_admin':
        admins = db.get_all_admins()
        txt = "🛡 Admins:\n" + "\n".join(f"• `{a}`" + (" 👑" if a == OWNER_ID else "") for a in admins)
        bot.send_message(call.message.chat.id, txt, parse_mode='Markdown')
    elif call.data == 'bot_logs':
        logs = db.get_logs(30)
        if not logs:
            txt = "📭 No logs."
        else:
            txt = "📜 Recent Bot Logs:\n"
            for lid, uid, action, details, ts in logs:
                txt += f"• `{ts}` U:{uid} {action} {details}\n"
        bot.send_message(call.message.chat.id, txt, parse_mode='Markdown')
    elif call.data == 'bot_settings':
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton("🆓 Free Limit", callback_data='set_free_limit'),
                   types.InlineKeyboardButton("💎 Premium Limit", callback_data='set_premium_limit'),
                   types.InlineKeyboardButton("🛡 Admin Limit", callback_data='set_admin_limit'),
                   types.InlineKeyboardButton("🗓 Log Retention", callback_data='set_log_retention'),
                   types.InlineKeyboardButton("🌐 Set Website URL", callback_data='set_website_url'),
                   types.InlineKeyboardButton("🔙 Back", callback_data='admin_panel'))
        bot.send_message(call.message.chat.id, "⚙️ Settings:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith('set_'))
def settings_callback(call):
    if not db.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ Admin only.", show_alert=True); return
    key_map = {
        'set_free_limit': 'free_user_limit',
        'set_premium_limit': 'premium_user_limit',
        'set_admin_limit': 'admin_limit',
        'set_log_retention': 'log_retention_days',
        'set_website_url': 'website_url'
    }
    key = key_map.get(call.data)
    if not key:
        return
    current = db.get_setting(key, '')
    msg = bot.send_message(call.message.chat.id, f"⚙️ Current value: `{current}`\nEnter new value (or /cancel):", parse_mode='Markdown')
    bot.register_next_step_handler(msg, lambda m: process_setting(m, key))

def process_setting(message, key):
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Cancelled."); return
    db.set_setting(key, message.text.strip())
    bot.reply_to(message, f"✅ Updated {key} to `{message.text.strip()}`.", parse_mode='Markdown')

def process_add_admin(message):
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Cancelled."); return
    try:
        uid = int(message.text.strip())
        db.add_admin(uid)
        db.log_action(message.from_user.id, 'add_admin', f'Added admin {uid}')
        bot.reply_to(message, f"✅ `{uid}` is now admin.", parse_mode='Markdown')
    except:
        bot.reply_to(message, "⚠️ Invalid ID.")

def process_rem_admin(message):
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Cancelled."); return
    try:
        uid = int(message.text.strip())
        if db.remove_admin(uid):
            db.log_action(message.from_user.id, 'rem_admin', f'Removed admin {uid}')
            bot.reply_to(message, f"✅ `{uid}` removed from admin.", parse_mode='Markdown')
        else:
            bot.reply_to(message, "⛔ Cannot remove owner.")
    except:
        bot.reply_to(message, "⚠️ Invalid ID.")

# ---- Lock/Unlock ----
@bot.message_handler(commands=['lock'])
@bot.message_handler(func=lambda m: m.text == "🔒 Lock Bot" and db.is_admin(m.from_user.id))
def lock_bot(message):
    global bot_locked
    bot_locked = True
    db.log_action(message.from_user.id, 'lock', 'Locked bot')
    bot.reply_to(message, "🔒 Bot locked.")

@bot.message_handler(commands=['unlock'])
@bot.message_handler(func=lambda m: m.text == "🔓 Unlock Bot" and db.is_admin(m.from_user.id))
def unlock_bot(message):
    global bot_locked
    bot_locked = False
    db.log_action(message.from_user.id, 'unlock', 'Unlocked bot')
    bot.reply_to(message, "🔓 Bot unlocked.")

# ---- Run All Scripts ----
@bot.message_handler(commands=['runall'])
@bot.message_handler(func=lambda m: m.text == "▶️ Run All Scripts" and db.is_admin(m.from_user.id))
def run_all_scripts(message):
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("SELECT id, file_type FROM files WHERE running=0 AND file_type IN ('py','js')")
    rows = c.fetchall()
    conn.close()
    if not rows:
        bot.reply_to(message, "ℹ️ No stopped scripts to start.")
        return
    started = 0
    for fid, ftype in rows:
        if script_manager.start(fid, notify=False):
            started += 1
        time.sleep(0.2)
    db.log_action(message.from_user.id, 'run_all', f'Started {started} scripts')
    bot.reply_to(message, f"▶️ Started {started} scripts.")

# ---- System Info ----
@bot.message_handler(commands=['sysinfo'])
@bot.message_handler(func=lambda m: m.text == "🖥 System Info" and db.is_admin(m.from_user.id))
def sysinfo(message):
    st = get_system_stats()
    uptime = time.time() - psutil.boot_time()
    days, rem = divmod(int(uptime), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"
    txt = (f"🖥 System Info:\n"
           f"🔥 CPU: {st['cpu']:.1f}%\n"
           f"💾 RAM: {format_bytes(st['memory_used'])} / {format_bytes(st['memory_total'])} ({st['memory_percent']:.1f}%)\n"
           f"💿 Disk: {format_bytes(st['disk_used'])} / {format_bytes(st['disk_total'])} ({st['disk_percent']:.1f}%)\n"
           f"⏱ Uptime: {uptime_str}\n"
           f"🐍 Python: {sys.version.split()[0]}\n"
           f"🆔 Bot PID: {os.getpid()}\n"
           f"🟢 Running scripts: {len(script_manager.processes)}")
    bot.reply_to(message, txt)

# ---- Restart Bot ----
@bot.message_handler(commands=['restartbot'])
@bot.message_handler(func=lambda m: m.text == "🔄 Restart Bot" and db.is_admin(m.from_user.id))
def restart_bot_cmd(message):
    if message.from_user.id not in [OWNER_ID, ADMIN_ID]:
        bot.reply_to(message, "⛔ Admin only.")
        return
    bot.reply_to(message, "🔄 Restarting in 2 seconds...")
    threading.Thread(target=do_restart, daemon=True).start()

def do_restart():
    time.sleep(2)
    script_manager.stop_all()
    os.execv(sys.executable, [sys.executable] + sys.argv)

# ---- Token ----
@bot.message_handler(commands=['token'])
def show_token(message):
    token = db.get_user_token(message.from_user.id)
    bot.reply_to(message, f"🔑 Your token: `{token}`\nUse it to log into the website.", parse_mode='Markdown')

# ---- Global callbacks ----
def _fix_from(call):
    try:
        call.message.from_user = call.from_user
    except Exception:
        pass

@bot.callback_query_handler(func=lambda c: c.data == 'back_main')
def back_main(call):
    bot.answer_callback_query(call.id)
    _fix_from(call)
    send_welcome(call.message)

@bot.callback_query_handler(func=lambda c: c.data == 'check_files')
def check_files_cb(call):
    bot.answer_callback_query(call.id)
    _fix_from(call)
    check_files(call.message)

@bot.callback_query_handler(func=lambda c: c.data == 'upload')
def upload_cb(call):
    bot.answer_callback_query(call.id)
    _fix_from(call)
    upload_start(call.message)

@bot.callback_query_handler(func=lambda c: c.data == 'speed')
def speed_cb(call):
    bot.answer_callback_query(call.id)
    _fix_from(call)
    speed(call.message)

@bot.callback_query_handler(func=lambda c: c.data == 'stats')
def stats_cb(call):
    bot.answer_callback_query(call.id)
    _fix_from(call)
    stats(call.message)

@bot.callback_query_handler(func=lambda c: c.data == 'website')
def website_cb(call):
    bot.answer_callback_query(call.id)
    _fix_from(call)
    website_link(call.message)

@bot.callback_query_handler(func=lambda c: c.data == 'subscription')
def sub_cb(call):
    if not db.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ Admin only.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    _fix_from(call)
    sub_menu(call.message)

@bot.callback_query_handler(func=lambda c: c.data == 'broadcast')
def broadcast_cb(call):
    if not db.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ Admin only.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    _fix_from(call)
    broadcast_start(call.message)

@bot.callback_query_handler(func=lambda c: c.data == 'admin_panel')
def admin_panel_cb(call):
    if not db.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ Admin only.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    _fix_from(call)
    admin_panel(call.message)

@bot.callback_query_handler(func=lambda c: c.data == 'lock_bot')
def lock_bot_cb(call):
    if not db.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ Admin only.", show_alert=True)
        return
    global bot_locked
    bot_locked = True
    db.log_action(call.from_user.id, 'lock', 'Locked bot via callback')
    bot.answer_callback_query(call.id, "🔒 Locked.")
    _fix_from(call)
    send_welcome(call.message)

@bot.callback_query_handler(func=lambda c: c.data == 'unlock_bot')
def unlock_bot_cb(call):
    if not db.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ Admin only.", show_alert=True)
        return
    global bot_locked
    bot_locked = False
    db.log_action(call.from_user.id, 'unlock', 'Unlocked bot via callback')
    bot.answer_callback_query(call.id, "🔓 Unlocked.")
    _fix_from(call)
    send_welcome(call.message)

@bot.callback_query_handler(func=lambda c: c.data == 'run_all')
def run_all_cb(call):
    if not db.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ Admin only.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    _fix_from(call)
    run_all_scripts(call.message)

@bot.callback_query_handler(func=lambda c: c.data == 'restart_bot_self')
def restart_bot_cb(call):
    if not db.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ Admin only.", show_alert=True)
        return
    bot.answer_callback_query(call.id, "🔄 Restarting...")
    _fix_from(call)
    restart_bot_cmd(call.message)

@bot.callback_query_handler(func=lambda c: c.data == 'sendall')
def sendall_cb(call):
    if not db.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ Admin only.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    _fix_from(call)
    sendall_start(call.message)

@bot.callback_query_handler(func=lambda c: c.data == 'sysinfo')
def sysinfo_cb(call):
    if not db.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ Admin only.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    _fix_from(call)
    sysinfo(call.message)

# ---- Updates Channel button ----
@bot.message_handler(func=lambda m: m.text == "📢 Updates Channel")
def updates_channel(m):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📢 Updates Channel", url=UPDATE_CHANNEL))
    bot.reply_to(m, "📢 Visit our channel:", reply_markup=markup)

# ============================================================================
# FLASK WEBSITE – GLASS DARK UI
# ============================================================================

HTML_LOGIN = """
<!DOCTYPE html>
<html>
<head>
    <title>NgaZen Hosting – Login</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { min-height: 100vh; display: flex; justify-content: center; align-items: center;
               font-family: 'Segoe UI', sans-serif;
               background: radial-gradient(ellipse at 20% 20%, #2b1a55 0%, transparent 55%),
                           radial-gradient(ellipse at 80% 80%, #0e3a4d 0%, transparent 55%),
                           #0a0a14; }
        .login-card { background: rgba(255,255,255,0.05); backdrop-filter: blur(20px);
                      padding: 46px; border-radius: 20px; width: 400px;
                      border: 1px solid rgba(255,255,255,0.1);
                      box-shadow: 0 20px 60px rgba(0,0,0,0.5); }
        h1 { font-weight: 700; color: #fff; font-size: 1.6em; }
        h1 span { background: linear-gradient(135deg,#8b7bff,#4dc9ff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .sub { color: #8b8ba7; font-size: 0.9em; margin: 8px 0 30px; }
        label { display: block; margin: 12px 0 6px; color: #b7b7d1; font-size: 0.9em; }
        input[type=text] { width: 100%; padding: 14px; background: rgba(0,0,0,0.35);
                           border: 1px solid rgba(255,255,255,0.12); border-radius: 10px;
                           color: #fff; outline: none; transition: 0.2s; font-size: 1em; }
        input[type=text]:focus { border-color: #8b7bff; box-shadow: 0 0 0 4px rgba(139,123,255,0.15); }
        input[type=submit] { width: 100%; padding: 14px; border: none; border-radius: 10px;
                             background: linear-gradient(135deg,#8b7bff,#4dc9ff); color: #08101e;
                             font-weight: 700; cursor: pointer; margin-top: 24px; font-size: 1em; transition: 0.2s; }
        input[type=submit]:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(139,123,255,0.35); }
        .error { color: #ff6b6b; margin-top: 12px; font-size: 0.9em; }
        .info { color: #6f6f90; margin-top: 16px; font-size: 0.85em; }
    </style>
</head>
<body>
<div class="login-card">
    <h1>⚡ Nga<span>Zen</span></h1>
    <div class="sub">Sign in to your hosting dashboard</div>
    <form method="post">
        <label>🔑 Token</label>
        <input type="text" name="token" placeholder="Enter your token" required>
        <input type="submit" value="Login →">
    </form>
    {% if error %}
    <div class="error">⚠️ {{ error }}</div>
    {% endif %}
    <div class="info">Get your token via /token in Telegram.</div>
</div>
</body>
</html>
"""

HTML_DASHBOARD = """
<!DOCTYPE html>
<html>
<head>
    <title>Dashboard – NgaZen</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Segoe UI', sans-serif; color: #e6e6f0; min-height: 100vh;
               background: radial-gradient(ellipse at 15% 10%, #2b1a55 0%, transparent 50%),
                           radial-gradient(ellipse at 85% 90%, #0e3a4d 0%, transparent 50%),
                           #0a0a14; }
        .layout { display: flex; min-height: 100vh; }
        .sidebar { width: 240px; padding: 26px 18px; border-right: 1px solid rgba(255,255,255,0.07);
                   background: rgba(255,255,255,0.03); backdrop-filter: blur(16px);
                   position: sticky; top: 0; height: 100vh; display: flex; flex-direction: column; }
        .sidebar h2 { font-weight: 700; padding-bottom: 22px; color: #fff; }
        .sidebar h2 span { background: linear-gradient(135deg,#8b7bff,#4dc9ff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .sidebar a { color: #9a9ab8; text-decoration: none; padding: 12px 14px; display: block;
                     border-radius: 10px; transition: 0.2s; margin-bottom: 4px; }
        .sidebar a:hover { color: #fff; background: rgba(255,255,255,0.06); }
        .sidebar .active { color: #fff; background: linear-gradient(135deg,rgba(139,123,255,0.18),rgba(77,201,255,0.12));
                           border: 1px solid rgba(139,123,255,0.35); }
        .main { flex: 1; padding: 36px; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 28px; }
        .header h1 { font-size: 1.5em; color: #fff; }
        .badge { background: rgba(139,123,255,0.12); border: 1px solid rgba(139,123,255,0.35);
                 color: #c9c2ff; padding: 7px 16px; border-radius: 20px; font-size: 0.85em; }
        .card { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
                border-radius: 16px; padding: 20px; }
        .proj-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 16px; }
        .proj-card { transition: 0.2s; }
        .proj-card:hover { border-color: rgba(139,123,255,0.5); transform: translateY(-3px);
                           box-shadow: 0 10px 30px rgba(0,0,0,0.4); }
        .proj-card .pname { font-weight: 600; font-size: 1.1em; color: #fff; }
        .proj-card .meta { color: #8b8ba7; font-size: 0.85em; margin: 8px 0 14px; }
        .pill { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 0.75em; margin-right: 6px; }
        .pill.on { background: rgba(81,224,139,0.12); color: #51e08b; border: 1px solid rgba(81,224,139,0.3); }
        .pill.off { background: rgba(255,255,255,0.06); color: #8b8ba7; border: 1px solid rgba(255,255,255,0.1); }
        .actions a { margin-right: 12px; color: #a49bff; text-decoration: none; font-size: 0.88em; }
        .actions a:hover { color: #fff; }
        .danger { color: #ff6b6b !important; }
        h2.sec { margin: 34px 0 16px; font-size: 1.15em; color: #cfcfe8; }
        .upload-area { border: 2px dashed rgba(139,123,255,0.35); padding: 30px; text-align: center;
                       background: rgba(139,123,255,0.05); border-radius: 16px; }
        .upload-area input[type=file] { display: none; }
        .upload-label { background: linear-gradient(135deg,#8b7bff,#4dc9ff); color: #08101e; font-weight: 700;
                        padding: 11px 24px; border-radius: 10px; cursor: pointer; display: inline-block; transition: 0.2s; }
        .upload-label:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(139,123,255,0.35); }
        .upload-area input[type=text] { background: rgba(0,0,0,0.35); border: 1px solid rgba(255,255,255,0.12);
                                        padding: 10px; border-radius: 8px; color: #fff; margin: 10px 4px 0; }
        .upload-area input[type=submit] { background: #2ea36b; color: white; border: none;
                                          padding: 10px 20px; border-radius: 8px; cursor: pointer; font-weight: 600; }
        #fname { color: #9a9ab8; font-size: 0.85em; margin-top: 10px; }
        .terminal { background: rgba(0,0,0,0.45); border: 1px solid rgba(255,255,255,0.08);
                    padding: 18px; border-radius: 14px; }
        .terminal pre { white-space: pre-wrap; max-height: 300px; overflow-y: auto;
                        color: #b5f5c8; font-size: 0.85em; margin-top: 12px; }
        .cmd-input { width: 76%; padding: 11px; border: 1px solid rgba(255,255,255,0.12);
                     background: rgba(0,0,0,0.35); color: #fff; border-radius: 8px; outline: none; }
        .cmd-btn { padding: 11px 22px; background: linear-gradient(135deg,#8b7bff,#4dc9ff);
                   color: #08101e; border: none; border-radius: 8px; cursor: pointer; font-weight: 700; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 11px 10px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.07); }
        th { color: #8b8ba7; font-size: 0.8em; text-transform: uppercase; letter-spacing: 1px; }
        .dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 7px; }
        .dot.on { background: #51e08b; box-shadow: 0 0 10px #51e08b; }
        .dot.off { background: #55556e; }
        @media (max-width: 800px) { .sidebar { width: 70px; } .sidebar a { font-size: 0; padding: 12px; }
            .sidebar a::first-letter { font-size: 18px; } .main { padding: 18px; } }
    </style>
</head>
<body>
<div class="layout">
<div class="sidebar">
    <h2>⚡ Nga<span>Zen</span></h2>
    <a href="/dashboard" class="active">🏠 Dashboard</a>
    <a href="#projects">📁 Projects</a>
    <a href="#upload">⬆️ Upload</a>
    <a href="#terminal-section">💻 Terminal</a>
    {% if is_admin %}
    <a href="/admin">🛠 Admin Panel</a>
    {% endif %}
    <a href="/logout" style="margin-top: auto;">🚪 Logout</a>
</div>
<div class="main">
    <div class="header">
        <h1>🏠 Dashboard</h1>
        <span class="badge">🆔 {{ user_id }}</span>
    </div>

    <div id="projects">
        <h2 class="sec">📁 Your Projects ({{ projects|length }})</h2>
        <div class="proj-grid">
        {% for p in projects %}
        <div class="card proj-card">
            <div class="pname">📁 {{ p.name }}</div>
            <div class="meta">
                <span class="pill on">🟢 {{ p.running }} running</span>
                <span class="pill off">{{ p.total }} files</span>
            </div>
            <div class="actions">
                <a href="/project/{{ p.id }}">📂 Open</a>
                <a href="/download_project/{{ p.id }}">⬇️ Zip</a>
                <a href="/delete_project/{{ p.id }}" class="danger" onclick="return confirm('Delete whole project?')">🗑</a>
            </div>
        </div>
        {% endfor %}
        {% if not projects %}
        <div class="card" style="color:#8b8ba7;">📭 No projects yet — upload your first file below!</div>
        {% endif %}
        </div>
    </div>

    <div id="upload">
        <h2 class="sec">⬆️ Upload</h2>
        <div class="upload-area">
            <form method="post" action="/upload" enctype="multipart/form-data">
                <label for="file-upload" class="upload-label">⬆️ Choose file / zip</label>
                <input type="file" name="file" id="file-upload" required
                       onchange="document.getElementById('fname').textContent = this.files[0] ? this.files[0].name : ''">
                <div id="fname"></div>
                <div>
                    <input type="text" name="folder_name" placeholder="📁 Folder name (e.g. sas)">
                    <input type="submit" value="Upload">
                </div>
                <div style="color:#6f6f90;font-size:0.8em;margin-top:10px;">
                    📁 Same folder name = files are added into that folder. Zip files are extracted fully. Nothing runs automatically.
                </div>
            </form>
        </div>
    </div>

    <div id="terminal-section">
        <h2 class="sec">💻 Terminal</h2>
        <div class="terminal">
            <form method="post" action="/exec">
                <input type="text" name="command" class="cmd-input" placeholder="e.g. pip install requests" required>
                <input type="submit" value="Run ▶" class="cmd-btn">
            </form>
            <pre>{{ output or 'No output yet.' }}</pre>
        </div>
    </div>
</div>
</div>
</body>
</html>
"""

HTML_PROJECT = """
<!DOCTYPE html>
<html>
<head>
    <title>📁 {{ pname }} – NgaZen</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Segoe UI', sans-serif; color: #e6e6f0; min-height: 100vh; padding: 30px;
               background: radial-gradient(ellipse at 15% 10%, #2b1a55 0%, transparent 50%),
                           radial-gradient(ellipse at 85% 90%, #0e3a4d 0%, transparent 50%), #0a0a14; }
        .wrap { max-width: 1100px; margin: 0 auto; }
        .top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
        h1 { color: #fff; font-size: 1.4em; }
        .back { color: #a49bff; text-decoration: none; }
        .card { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
                border-radius: 16px; padding: 20px; margin-bottom: 18px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 11px 10px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.07); }
        th { color: #8b8ba7; font-size: 0.78em; text-transform: uppercase; letter-spacing: 1px; }
        .dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 7px; }
        .dot.on { background: #51e08b; box-shadow: 0 0 10px #51e08b; }
        .dot.off { background: #55556e; }
        .btn { padding: 5px 12px; border-radius: 7px; border: none; cursor: pointer; font-size: 0.85em;
               text-decoration: none; color: #fff; display: inline-block; margin-right: 4px; }
        .b-run { background: #2ea36b; } .b-stop { background: #c0392b; }
        .b-log { background: rgba(139,123,255,0.25); } .b-dl { background: rgba(255,255,255,0.1); }
        .upload-area { border: 2px dashed rgba(139,123,255,0.35); padding: 22px; text-align: center;
                       background: rgba(139,123,255,0.05); border-radius: 14px; }
        .upload-area input[type=file] { display: none; }
        .upload-label { background: linear-gradient(135deg,#8b7bff,#4dc9ff); color: #08101e; font-weight: 700;
                        padding: 10px 20px; border-radius: 10px; cursor: pointer; display: inline-block; }
        .upload-area input[type=submit] { background: #2ea36b; color: white; border: none;
                                          padding: 10px 18px; border-radius: 8px; cursor: pointer; font-weight: 600; }
        #fname { color: #9a9ab8; font-size: 0.85em; margin-top: 8px; }
    </style>
</head>
<body>
<div class="wrap">
    <div class="top">
        <h1>📁 {{ pname }}</h1>
        <a class="back" href="/dashboard">← 🔙 Dashboard</a>
    </div>

    <div class="card upload-area">
        <form method="post" action="/upload/{{ pid }}" enctype="multipart/form-data">
            <label for="file-upload" class="upload-label">⬆️ Add files into this folder</label>
            <input type="file" name="file" id="file-upload" required
                   onchange="document.getElementById('fname').textContent = this.files[0] ? this.files[0].name : ''">
            <div id="fname"></div>
            <div style="margin-top:8px;"><input type="submit" value="Upload into 📁 {{ pname }}"></div>
        </form>
    </div>

    <div class="card">
        <table>
            <tr><th>File</th><th>Type</th><th>Status</th><th>Actions</th></tr>
            {% for f in files %}
            <tr>
                <td>{{ f.icon }} {{ f.display_name }} <span style="color:#55556e;font-size:0.8em;">{{ f.stored_name }}</span></td>
                <td>{{ f.file_type }}</td>
                <td><span class="dot {{ 'on' if f.running else 'off' }}"></span>{{ 'Running' if f.running else 'Stopped' }}</td>
                <td>
                {% if f.runnable %}
                    {% if f.running %}
                    <a class="btn b-stop" href="/stop/{{ f.id }}">⏹ Stop</a>
                    <a class="btn b-log" href="/restart/{{ f.id }}">🔄</a>
                    {% else %}
                    <a class="btn b-run" href="/start/{{ f.id }}">▶️ Start</a>
                    {% endif %}
                    <a class="btn b-log" href="/logs/{{ f.id }}">📜 Logs</a>
                {% endif %}
                    <a class="btn b-dl" href="/download/{{ f.id }}">⬇️</a>
                    <a class="btn b-stop" href="/delete/{{ f.id }}" onclick="return confirm('Delete file?')">🗑</a>
                </td>
            </tr>
            {% endfor %}
            {% if not files %}
            <tr><td colspan="4" style="color:#8b8ba7;">📭 This folder is empty — add files above!</td></tr>
            {% endif %}
        </table>
    </div>
</div>
</body>
</html>
"""

HTML_ADMIN = """
<!DOCTYPE html>
<html>
<head>
    <title>Admin – NgaZen</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Segoe UI', sans-serif; color: #e6e6f0; padding: 26px; min-height: 100vh;
               background: radial-gradient(ellipse at 15% 10%, #2b1a55 0%, transparent 50%), #0a0a14; }
        .container { max-width: 1200px; margin: 0 auto; background: rgba(255,255,255,0.04);
                     padding: 28px; border-radius: 18px; border: 1px solid rgba(255,255,255,0.08); }
        h1, h2 { padding-bottom: 10px; color: #fff; }
        h2 { margin-top: 28px; font-size: 1.1em; color: #cfcfe8; }
        table { width: 100%; border-collapse: collapse; margin: 16px 0; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.07); }
        th { color: #8b8ba7; font-size: 0.78em; text-transform: uppercase; }
        .btn { background: linear-gradient(135deg,#8b7bff,#4dc9ff); color: #08101e; padding: 5px 13px;
               border: none; border-radius: 6px; cursor: pointer; font-weight: 600; }
        .btn-danger { background: #c0392b; color: #fff; }
        .form-inline { display: inline-block; margin: 2px; }
        .form-inline input { padding: 5px; background: rgba(0,0,0,0.35); border: 1px solid rgba(255,255,255,0.12);
                             color: #fff; border-radius: 6px; }
        .nav { display: flex; justify-content: space-between; align-items: center; }
        .nav a { margin-left: 15px; color: #a49bff; text-decoration: none; }
        pre.logs { background: rgba(0,0,0,0.45); border: 1px solid rgba(255,255,255,0.08);
                   padding: 12px; max-height: 300px; overflow-y: auto; border-radius: 8px;
                   color: #9adcff; font-size: 0.8em; }
    </style>
</head>
<body>
<div class="container">
    <div class="nav">
        <h1>🛠 Admin Panel</h1>
        <div>
            <a href="/dashboard">🏠 Dashboard</a>
            <a href="/logout">🚪 Logout</a>
        </div>
    </div>

    <h2>👥 Users</h2>
    <table>
        <tr><th>ID</th><th>Username</th><th>First Name</th><th>Subscription</th><th>Admin</th><th>Actions</th></tr>
        {% for user in users %}
        <tr>
            <td>{{ user.user_id }}</td>
            <td>{{ user.username or '-' }}</td>
            <td>{{ user.first_name or '-' }}</td>
            <td>{% if user.subscription %}{{ user.subscription.strftime('%Y-%m-%d') }}{% else %}None{% endif %}</td>
            <td>{{ '✅' if user.is_admin else '' }}</td>
            <td>
                <form method="post" action="/admin/add_sub" class="form-inline">
                    <input type="hidden" name="user_id" value="{{ user.user_id }}">
                    <input type="number" name="days" placeholder="Days" required style="width:65px;">
                    <input type="submit" value="💳 Add Sub" class="btn">
                </form>
                <form method="post" action="/admin/remove_sub" class="form-inline">
                    <input type="hidden" name="user_id" value="{{ user.user_id }}">
                    <input type="submit" value="🗑 Remove Sub" class="btn btn-danger">
                </form>
                {% if not user.is_admin and user.user_id != owner_id %}
                <form method="post" action="/admin/add_admin" class="form-inline">
                    <input type="hidden" name="user_id" value="{{ user.user_id }}">
                    <input type="submit" value="🛡 Make Admin" class="btn">
                </form>
                {% elif user.is_admin and user.user_id != owner_id %}
                <form method="post" action="/admin/remove_admin" class="form-inline">
                    <input type="hidden" name="user_id" value="{{ user.user_id }}">
                    <input type="submit" value="➖ Remove Admin" class="btn btn-danger">
                </form>
                {% endif %}
            </td>
        </tr>
        {% endfor %}
    </table>

    <h2>🟢 Running Processes</h2>
    <table>
        <tr><th>File ID</th><th>User</th><th>Script</th><th>PID</th><th>CPU%</th><th>Memory (MB)</th><th>Action</th></tr>
        {% for proc in processes %}
        <tr>
            <td>{{ proc.file_id }}</td>
            <td>{{ proc.user_id }}</td>
            <td>{{ proc.stored_name }}</td>
            <td>{{ proc.pid }}</td>
            <td>{{ proc.cpu }}</td>
            <td>{{ proc.mem }}</td>
            <td><a href="/stop_process/{{ proc.file_id }}"><button class="btn btn-danger">⏹ Stop</button></a></td>
        </tr>
        {% endfor %}
    </table>

    <h2>📜 Bot Logs</h2>
    <pre class="logs">{% for log in logs %}{{ log.timestamp }} | U:{{ log.user_id }} | {{ log.action }} | {{ log.details }}
{% endfor %}</pre>

    <h2>⚙️ Settings</h2>
    <form method="post" action="/admin/settings">
        <table>
            {% for key, val in settings.items() %}
            <tr>
                <td>{{ key }}</td>
                <td><input type="text" name="{{ key }}" value="{{ val }}" style="width:300px;padding:6px;background:rgba(0,0,0,0.35);border:1px solid rgba(255,255,255,0.12);color:#fff;border-radius:6px;"></td>
                <td><input type="submit" value="💾 Update" class="btn"></td>
            </tr>
            {% endfor %}
        </table>
    </form>
</div>
</body>
</html>
"""

app = Flask(__name__)
app.secret_key = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
bot_locked = False

# ---------------- web routes ----------------
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        token = request.form.get('token', '').strip()
        user_id = db.get_user_by_token(token)
        if user_id:
            session['user_id'] = user_id
            return redirect(url_for('dashboard'))
        else:
            return render_template_string(HTML_LOGIN, error="Invalid token")
    return render_template_string(HTML_LOGIN)

def _projects_for_web(user_id):
    out = []
    for pid, pname, total, running in db.get_user_projects(user_id):
        out.append({'id': pid, 'name': pname, 'total': total, 'running': running})
    return out

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    return render_template_string(HTML_DASHBOARD, user_id=user_id,
                                  projects=_projects_for_web(user_id),
                                  is_admin=db.is_admin(user_id), output=None)

@app.route('/project/<int:pid>')
def project_page(pid):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    proj = db.get_project(pid)
    if not proj or (proj[1] != user_id and not db.is_admin(user_id)):
        return "Not found", 404
    files = []
    for fid, disp, stored, ftype, running, _ in db.get_project_files(pid):
        files.append({'id': fid, 'display_name': disp, 'stored_name': stored,
                      'file_type': ftype, 'running': running,
                      'runnable': is_runnable(ftype), 'icon': ext_icon(stored, ftype)})
    return render_template_string(HTML_PROJECT, pid=pid, pname=proj[2], files=files)

@app.route('/upload', methods=['POST'])
@app.route('/upload/<int:pid>', methods=['POST'])
def upload_file_web(pid=0):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    if 'file' not in request.files:
        return "No file part", 400
    f = request.files['file']
    if f.filename == '':
        return "No selected file", 400
    limit = get_user_limit(user_id)
    if count_user_files(user_id) >= limit:
        return "File limit reached", 403
    folder_name = sanitize_folder_name(request.form.get('folder_name', ''))
    if pid:
        proj = db.get_project(pid)
        if not proj or proj[1] != user_id:
            return "Not found", 404
    else:
        if not folder_name:
            folder_name = os.path.splitext(f.filename)[0]
        pid = db.get_or_create_project(user_id, folder_name)
        proj = db.get_project(pid)
    content = f.read()
    ext = os.path.splitext(f.filename)[1].lower()
    db.log_action(user_id, 'upload_web', f'Uploaded {f.filename} into {proj[2]}')
    if ext == '.zip':
        pdir = project_dir(user_id, proj[2])
        os.makedirs(pdir, exist_ok=True)
        tmp_zip = os.path.join(tempfile.mkdtemp(), 'up.zip')
        try:
            with open(tmp_zip, 'wb') as fp:
                fp.write(content)
            temp_dir = tempfile.mkdtemp()
            safe_extract_zip(tmp_zip, temp_dir)
            entries = [e for e in os.listdir(temp_dir) if e != '__MACOSX']
            src_root = temp_dir
            if len(entries) == 1 and os.path.isdir(os.path.join(temp_dir, entries[0])):
                src_root = os.path.join(temp_dir, entries[0])
            for dirpath, dirnames, filenames in os.walk(src_root):
                dirnames[:] = [d for d in dirnames if d not in ('__pycache__', 'node_modules', '.git')]
                rel_dir = os.path.relpath(dirpath, src_root)
                dest_dir = pdir if rel_dir == '.' else os.path.join(pdir, rel_dir)
                os.makedirs(dest_dir, exist_ok=True)
                for fn in filenames:
                    rel = fn if rel_dir == '.' else os.path.join(rel_dir, fn)
                    shutil.copy2(os.path.join(dirpath, fn), os.path.join(dest_dir, fn))
                    if not db.file_exists_in_project(pid, rel):
                        db.add_file(user_id, pid, os.path.splitext(fn)[0], rel, detect_type(fn))
        except Exception:
            pass
        finally:
            shutil.rmtree(os.path.dirname(tmp_zip), ignore_errors=True)
            try: shutil.rmtree(temp_dir, ignore_errors=True)
            except: pass
    else:
        _save_single_file(user_id, pid, os.path.basename(f.filename), content)
    return redirect(url_for('project_page', pid=pid))

@app.route('/start/<int:file_id>')
def web_start(file_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    row = db.get_file_row(file_id)
    if not row or (row[1] != user_id and not db.is_admin(user_id)):
        return "Not found", 404
    script_manager.start(file_id)
    db.log_action(user_id, 'start_web', f'Started file {file_id}')
    return redirect(url_for('project_page', pid=row[2]))

@app.route('/stop/<int:file_id>')
def web_stop(file_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    row = db.get_file_row(file_id)
    if not row or (row[1] != user_id and not db.is_admin(user_id)):
        return "Not found", 404
    script_manager.stop(file_id)
    db.log_action(user_id, 'stop_web', f'Stopped file {file_id}')
    return redirect(url_for('project_page', pid=row[2]))

@app.route('/restart/<int:file_id>')
def web_restart(file_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    row = db.get_file_row(file_id)
    if not row or (row[1] != user_id and not db.is_admin(user_id)):
        return "Not found", 404
    script_manager.restart(file_id)
    return redirect(url_for('project_page', pid=row[2]))

@app.route('/exec', methods=['POST'])
def exec_cmd():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    cmd = request.form.get('command', '').strip()
    if not cmd:
        return redirect(url_for('dashboard'))
    user_folder = os.path.join(UPLOAD_BOTS_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)
    try:
        result = subprocess.run(cmd, shell=True, cwd=user_folder,
                                capture_output=True, text=True, timeout=60)
        output = result.stdout + result.stderr
    except Exception as e:
        output = f"Error: {e}"
    return render_template_string(HTML_DASHBOARD, user_id=user_id,
                                  projects=_projects_for_web(user_id),
                                  is_admin=db.is_admin(user_id), output=output)

@app.route('/download/<int:file_id>')
def download_file(file_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    row = db.get_file_row(file_id)
    if not row or (row[1] != user_id and not db.is_admin(user_id)):
        return "File not found", 404
    full = file_full_path(row[1], row[2], row[4])
    if not full or not os.path.exists(full):
        return "File not found on disk", 404
    return send_file(full, as_attachment=True, download_name=os.path.basename(full))

@app.route('/download_project/<int:pid>')
def download_project(pid):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    proj = db.get_project(pid)
    if not proj or (proj[1] != user_id and not db.is_admin(user_id)):
        return "Not found", 404
    pdir = project_dir(user_id, proj[2])
    if not os.path.isdir(pdir):
        return "Folder not found on disk", 404
    zip_base = os.path.join(tempfile.gettempdir(), f"{proj[2]}_{int(time.time())}")
    zip_path = shutil.make_archive(zip_base, 'zip', pdir)
    return send_file(zip_path, as_attachment=True, download_name=f"{proj[2]}.zip")

@app.route('/delete/<int:file_id>')
def delete_file_web(file_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    row = db.get_file_row(file_id)
    if not row or (row[1] != user_id and not db.is_admin(user_id)):
        return "Not found", 404
    if script_manager.is_running(file_id):
        script_manager.stop(file_id)
    pid = row[2]
    db.delete_file(file_id)
    db.log_action(user_id, 'delete_web', f'Deleted file {file_id}')
    return redirect(url_for('project_page', pid=pid))

@app.route('/delete_project/<int:pid>')
def delete_project_web(pid):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    proj = db.get_project(pid)
    if not proj or (proj[1] != user_id and not db.is_admin(user_id)):
        return "Not found", 404
    for fid, disp, stored, ftype, running, _ in db.get_project_files(pid):
        if script_manager.is_running(fid):
            script_manager.stop(fid)
    db.delete_project(pid, proj[1])
    db.log_action(user_id, 'del_project_web', f'Deleted project {proj[2]}')
    return redirect(url_for('dashboard'))

@app.route('/logs/<int:file_id>')
def view_logs(file_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    row = db.get_file_row(file_id)
    if not row or (row[1] != user_id and not db.is_admin(user_id)):
        return "File not found", 404
    full = file_full_path(row[1], row[2], row[4])
    log_path = os.path.join(os.path.dirname(full), os.path.splitext(os.path.basename(full))[0] + '.log') if full else None
    back = f"/project/{row[2]}"
    if not log_path or not os.path.exists(log_path):
        return f"📭 No logs yet. <a href='{back}' style='color:#a49bff;'>Back</a>"
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    return f'''<!DOCTYPE html><html><head><title>📜 Logs</title>
    <style>body{{background:#0b0b14;color:#b5f5c8;font-family:monospace;padding:20px;}}
    a{{color:#a49bff;}}</style></head>
    <body><a href="{back}">← 🔙 Back</a><pre>{content or "(empty)"}</pre></body></html>'''

@app.route('/stop_process/<int:file_id>')
def stop_process(file_id):
    if 'user_id' not in session or not db.is_admin(session['user_id']):
        return "Unauthorized", 403
    script_manager.stop(file_id)
    return redirect(url_for('admin_panel_web'))

@app.route('/admin')
def admin_panel_web():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    if not db.is_admin(user_id):
        return "Access denied", 403
    users = []
    for uid in db.get_all_users():
        sub = db.get_subscription(uid)
        username, first_name, _ = db.get_user_info(uid)
        users.append({'user_id': uid, 'username': username, 'first_name': first_name,
                      'subscription': sub, 'is_admin': db.is_admin(uid)})
    processes = []
    for fid in list(script_manager.processes.keys()):
        pinfo = script_manager.get_process_info(fid)
        if pinfo:
            processes.append({'file_id': fid, 'user_id': pinfo['user_id'],
                              'stored_name': pinfo['stored_name'], 'pid': pinfo['pid'],
                              'cpu': round(pinfo['cpu'], 1), 'mem': round(pinfo['mem'], 1)})
    logs = [{'user_id': uid, 'action': act, 'details': det, 'timestamp': ts}
            for lid, uid, act, det, ts in db.get_logs(50)]
    settings_keys = ['free_user_limit', 'premium_user_limit', 'admin_limit',
                     'auto_restart_on_crash', 'log_retention_days', 'max_upload_size_mb', 'website_url']
    settings = {k: db.get_setting(k, '') for k in settings_keys}
    return render_template_string(HTML_ADMIN, users=users, processes=processes,
                                  logs=logs, settings=settings, owner_id=OWNER_ID)

@app.route('/admin/settings', methods=['POST'])
def admin_settings():
    if 'user_id' not in session or not db.is_admin(session['user_id']):
        return "Unauthorized", 403
    for key, value in request.form.items():
        db.set_setting(key, value)
    return redirect(url_for('admin_panel_web'))

@app.route('/admin/add_sub', methods=['POST'])
def admin_add_sub():
    if 'user_id' not in session or not db.is_admin(session['user_id']):
        return "Unauthorized", 403
    uid = int(request.form.get('user_id'))
    days = int(request.form.get('days'))
    cur = db.get_subscription(uid)
    base = cur if cur and cur > datetime.now() else datetime.now()
    db.set_subscription(uid, base + timedelta(days=days))
    db.log_action(session['user_id'], 'add_sub_web', f'Added {days}d for {uid}')
    return redirect(url_for('admin_panel_web'))

@app.route('/admin/remove_sub', methods=['POST'])
def admin_remove_sub():
    if 'user_id' not in session or not db.is_admin(session['user_id']):
        return "Unauthorized", 403
    db.remove_subscription(int(request.form.get('user_id')))
    return redirect(url_for('admin_panel_web'))

@app.route('/admin/add_admin', methods=['POST'])
def admin_add_admin():
    if 'user_id' not in session or not db.is_admin(session['user_id']):
        return "Unauthorized", 403
    db.add_admin(int(request.form.get('user_id')))
    return redirect(url_for('admin_panel_web'))

@app.route('/admin/remove_admin', methods=['POST'])
def admin_remove_admin():
    if 'user_id' not in session or not db.is_admin(session['user_id']):
        return "Unauthorized", 403
    db.remove_admin(int(request.form.get('user_id')))
    return redirect(url_for('admin_panel_web'))

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False)

def keep_alive():
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    print("Flask server running")

# ============================================================================
# BACKGROUND TASKS
# ============================================================================
def cleanup_old_logs():
    while True:
        time.sleep(3600*24)
        retention = int(db.get_setting('log_retention_days', '30'))
        if retention <= 0:
            continue
        cutoff = datetime.now() - timedelta(days=retention)
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute('DELETE FROM bot_logs WHERE timestamp < ?', (cutoff.isoformat(),))
        conn.commit()
        conn.close()

threading.Thread(target=cleanup_old_logs, daemon=True).start()

# ============================================================================
# CLEANUP
# ============================================================================
def cleanup():
    script_manager.stop_all()
    print("Cleanup done.")
atexit.register(cleanup)

# ============================================================================
# MAIN
# ============================================================================
if __name__ == '__main__':
    print("="*50)
    print("NgaZen Hosting Bot – Ultimate Edition v3")
    print(f"Upload dir: {UPLOAD_BOTS_DIR}")
    print(f"Owner: {OWNER_ID}")
    print("="*50)
    keep_alive()
    print("Starting Telegram polling...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=30)
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(5)
