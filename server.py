import http.server
import json
import os
import sqlite3
import urllib.request
import urllib.error
import urllib.parse
import base64
import ssl
import imaplib
import email
import email.utils
from email.header import decode_header
import webbrowser
import socket
import threading
import time
from datetime import datetime, timezone

# ==========================================
# Environment & Configuration
# ==========================================
ENV = os.environ.get('SOVAPP_ENV', 'production').strip().lower()
if ENV not in ('production', 'test'):
    ENV = 'production'

DEFAULT_PORT = 8080 if ENV == 'test' else 8000
PORT = int(os.environ.get('PORT', DEFAULT_PORT))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DB_FILENAME = 'tasks_test.db' if ENV == 'test' else 'tasks.db'
DB_FILE = os.path.join(DATA_DIR, DB_FILENAME)
OLD_JSON_FILE = os.path.join(DATA_DIR, 'database.json')

DEFAULT_NTFY_TOPIC = 'ghazal-to-do-test' if ENV == 'test' else 'ghazal-to-do'

os.makedirs(DATA_DIR, exist_ok=True)


def parse_datetime(dt_str):
    """Safely parse ISO string or RFC email date to UTC datetime."""
    if not dt_str:
        return None
    try:
        clean = dt_str.replace('Z', '+00:00')
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    return None


def get_network_ips():
    """Detect real local network IPs (excludes loopback 127.0.0.1 and localhost)."""
    ips = []
    # Method 1: Find primary outbound routing interface
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        primary = s.getsockname()[0]
        s.close()
        if primary and not primary.startswith('127.'):
            ips.append(primary)
    except Exception:
        pass

    # Method 2: Inspect all active hostname interfaces
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if ':' not in ip and not ip.startswith('127.') and ip != 'localhost':
                if ip not in ips:
                    ips.append(ip)
    except Exception:
        pass

    return ips


def init_db(db_path=None):
    target_db = db_path or DB_FILE
    conn = sqlite3.connect(target_db)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            source TEXT,
            sender TEXT,
            title TEXT,
            body TEXT,
            sent_at TEXT,
            due_date TEXT,
            task_status TEXT,
            response_status TEXT,
            responded_at TEXT,
            is_deleted INTEGER DEFAULT 0,
            deleted_at TEXT,
            alert_triggered INTEGER DEFAULT 0,
            last_alert_at TEXT,
            alert_count INTEGER DEFAULT 0,
            updated_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Schema migration: Add columns if table already existed without them
    for col_name, col_type in [
        ('last_alert_at', 'TEXT'),
        ('alert_count', 'INTEGER DEFAULT 0'),
        ('updated_at', 'TEXT')
    ]:
        try:
            c.execute(f"ALTER TABLE tasks ADD COLUMN {col_name} {col_type}")
        except Exception:
            pass

    # Topic Default
    c.execute('SELECT value FROM settings WHERE key="ntfy_topic"')
    if not c.fetchone():
        c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES ("ntfy_topic", ?)', (DEFAULT_NTFY_TOPIC,))

    # Migration for old JSON if production and db is empty
    c.execute('SELECT COUNT(*) FROM tasks')
    if c.fetchone()[0] == 0 and os.path.exists(OLD_JSON_FILE) and ENV == 'production':
        try:
            with open(OLD_JSON_FILE, 'r', encoding='utf-8') as f:
                old_data = json.load(f)
                for t in old_data.get('tasks', []):
                    c.execute("""
                        INSERT OR IGNORE INTO tasks (id, source, sender, title, body, sent_at, due_date, task_status, response_status, responded_at, is_deleted, deleted_at, alert_triggered)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        t['id'], t['source'], t['sender'], t['title'], t.get('body', ''),
                        t['sent_at'], t.get('due_date'), t['task_status'], t['response_status'],
                        t.get('responded_at'), 1 if t.get('is_deleted') else 0,
                        t.get('deleted_at'), 1 if t.get('alert_triggered') else 0
                    ))
            print('[sovapp] داده‌های قبلی به دیتابیس SQLite منتقل شدند.')
        except Exception as e:
            print(f'[Migration Notice] {e}')

    conn.commit()
    conn.close()


init_db()


def get_setting(key, default='', db_path=None):
    try:
        conn = sqlite3.connect(db_path or DB_FILE)
        c = conn.cursor()
        c.execute('SELECT value FROM settings WHERE key = ?', (key,))
        row = c.fetchone()
        conn.close()
        return row[0] if row and row[0] else default
    except Exception:
        return default


def set_setting(key, value, db_path=None):
    try:
        conn = sqlite3.connect(db_path or DB_FILE)
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def send_android_notification(title, message, priority='default', tags='bell', topic=None):
    active_topic = topic or get_setting('ntfy_topic', DEFAULT_NTFY_TOPIC)
    if not active_topic:
        return False
    try:
        url = f'https://ntfy.sh/{active_topic}'
        headers = {
            'Title': title.encode('utf-8'),
            'Priority': priority,
            'Tags': tags
        }
        req = urllib.request.Request(url, data=message.encode('utf-8'), headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status == 200
    except Exception as e:
        print(f'[Mobile Notify Error] {e}')
        return False


# ==========================================
# 48h Overdue & 3-Hour Repeating Alert Worker
# ==========================================
def check_and_send_repeating_alerts(db_path=None, force_notification_fn=None):
    target_db = db_path or DB_FILE
    now = datetime.now(timezone.utc)
    alerts_sent = 0
    notify_fn = force_notification_fn or send_android_notification

    try:
        conn = sqlite3.connect(target_db)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            SELECT * FROM tasks
            WHERE is_deleted = 0
              AND response_status != 'responded'
              AND task_status != 'done'
        """)
        rows = c.fetchall()

        for r in rows:
            t = dict(r)
            sent_at_str = t.get('sent_at')
            if not sent_at_str:
                continue

            sent_at = parse_datetime(sent_at_str)
            if not sent_at:
                continue

            diff_hours = (now - sent_at).total_seconds() / 3600.0

            if diff_hours >= 48.0:
                last_alert_str = t.get('last_alert_at')
                should_alert = False
                is_repeat = False

                if not last_alert_str:
                    should_alert = True
                    is_repeat = False
                else:
                    last_alert_dt = parse_datetime(last_alert_str)
                    if last_alert_dt:
                        hours_since_last_alert = (now - last_alert_dt).total_seconds() / 3600.0
                        if hours_since_last_alert >= 3.0:
                            should_alert = True
                            is_repeat = True

                if should_alert:
                    topic = get_setting('ntfy_topic', DEFAULT_NTFY_TOPIC, db_path=target_db)
                    hours_rounded = int(diff_hours)
                    count = (t.get('alert_count') or 0) + 1

                    if not is_repeat:
                        title = f"🔴 هشدار مهلت ۴۸ ساعته [{t.get('source', 'کار')}]"
                        msg = f"فرستنده: {t.get('sender', 'نامشخص')}\nموضوع: {t.get('title', '')}\nبیش از ۴۸ ساعت ({hours_rounded} ساعت) گذشته و نیاز به اقدام فوری دارد."
                        tags = "warning,hourglass"
                    else:
                        title = f"⏰ یادآوری مکرر ({hours_rounded} ساعت گذشته) [{t.get('source', 'کار')}]"
                        msg = f"فرستنده: {t.get('sender', 'نامشخص')}\nموضوع: {t.get('title', '')}\nهنوز پاسخی ثبت نشده است (یادآوری هر ۳ ساعت - نوبت #{count})."
                        tags = "alarm_clock,hourglass_flowing_sand"

                    success = notify_fn(title, msg, priority="high", tags=tags, topic=topic)
                    if success:
                        alerts_sent += 1
                        c.execute("""
                            UPDATE tasks
                            SET alert_triggered = 1,
                                last_alert_at = ?,
                                alert_count = COALESCE(alert_count, 0) + 1,
                                updated_at = ?
                            WHERE id = ?
                        """, (now.isoformat(), now.isoformat(), t['id']))
                        conn.commit()

        conn.close()
    except Exception as e:
        print(f"[Alert Worker Error] {e}")

    return alerts_sent


ALERT_WORKER_STARTED = False

def start_alert_worker():
    global ALERT_WORKER_STARTED
    if ALERT_WORKER_STARTED:
        return
    ALERT_WORKER_STARTED = True

    def run_worker():
        while True:
            try:
                check_and_send_repeating_alerts()
            except Exception:
                pass
            time.sleep(60)

    thread = threading.Thread(target=run_worker, daemon=True)
    thread.start()


# ==========================================
# HTTP Request Handler
# ==========================================
class TaskHubHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # Anchor directory permanently to BASE_DIR regardless of launch CWD
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def translate_path(self, path):
        # Security: Prevent directory traversal outside BASE_DIR
        clean_path = super().translate_path(path)
        rel = os.path.relpath(clean_path, BASE_DIR)
        if rel.startswith('..') or os.path.isabs(rel):
            return os.path.join(BASE_DIR, '__invalid_path__')
        return clean_path

    def end_headers(self):
        # Security & CORS headers (Allow Wi-Fi cross-device communication)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'SAMEORIGIN')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def send_json(self, status_code, data):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def do_POST(self):
        # همگام‌سازی دوطرفه صندوق کارها در شبکه Wi-Fi (Wi-Fi Sync)
        if self.path == '/api/sync':
            try:
                length = int(self.headers.get('Content-Length', 0))
                payload = json.loads(self.rfile.read(length).decode('utf-8'))
                client_tasks = payload.get('tasks', [])
                now_str = datetime.now(timezone.utc).isoformat()

                conn = sqlite3.connect(DB_FILE)
                conn.row_factory = sqlite3.Row
                c = conn.cursor()

                c.execute('SELECT * FROM tasks')
                existing_map = {row['id']: dict(row) for row in c.fetchall()}

                synced_in = 0
                for ct in client_tasks:
                    tid = ct.get('id')
                    if not tid:
                        continue

                    existing = existing_map.get(tid)
                    if not existing:
                        c.execute("""
                            INSERT INTO tasks (id, source, sender, title, body, sent_at, due_date, task_status, response_status, responded_at, is_deleted, deleted_at, alert_triggered, last_alert_at, alert_count, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            tid, ct.get('source', 'Manual'), ct.get('sender', ''), ct.get('title', ''), ct.get('body', ''),
                            ct.get('sent_at', now_str), ct.get('due_date'), ct.get('task_status', 'pending'),
                            ct.get('response_status', 'pending_response'), ct.get('responded_at'),
                            1 if ct.get('is_deleted') else 0, ct.get('deleted_at'),
                            1 if ct.get('alert_triggered') else 0, ct.get('last_alert_at'),
                            ct.get('alert_count', 0), now_str
                        ))
                        synced_in += 1
                    else:
                        client_responded = (ct.get('response_status') == 'responded' and existing.get('response_status') != 'responded')
                        client_deleted = (bool(ct.get('is_deleted')) and not bool(existing.get('is_deleted')))
                        client_done = (ct.get('task_status') == 'done' and existing.get('task_status') != 'done')
                        due_changed = (ct.get('due_date') != existing.get('due_date') and ct.get('due_date') is not None)

                        if client_responded or client_deleted or client_done or due_changed:
                            c.execute("""
                                UPDATE tasks SET
                                    due_date = COALESCE(?, due_date),
                                    task_status = ?,
                                    response_status = ?,
                                    responded_at = COALESCE(?, responded_at),
                                    is_deleted = ?,
                                    deleted_at = COALESCE(?, deleted_at),
                                    updated_at = ?
                                WHERE id = ?
                            """, (
                                ct.get('due_date'),
                                ct.get('task_status', existing['task_status']),
                                ct.get('response_status', existing['response_status']),
                                ct.get('responded_at'),
                                1 if (ct.get('is_deleted') or existing['is_deleted']) else 0,
                                ct.get('deleted_at'),
                                now_str,
                                tid
                            ))
                            synced_in += 1

                conn.commit()

                c.execute('SELECT * FROM tasks ORDER BY sent_at DESC')
                merged_tasks = []
                for r in c.fetchall():
                    item = dict(r)
                    item['is_deleted'] = bool(item['is_deleted'])
                    item['alert_triggered'] = bool(item['alert_triggered'])
                    merged_tasks.append(item)

                conn.close()

                self.send_json(200, {
                    'success': True,
                    'synced_count': synced_in,
                    'tasks': merged_tasks,
                    'server_time': now_str
                })
            except Exception as e:
                self.send_json(500, {'error': f'خطا در همگام‌سازی وای‌فای: {str(e)}'})

        # تنظیم کانال نوتیفیکیشن موبایل
        elif self.path == '/api/settings/mobile':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length).decode('utf-8'))
                topic = body.get('topic', '').strip()
                if topic:
                    set_setting('ntfy_topic', topic)
                self.send_json(200, {'success': True, 'topic': topic or get_setting('ntfy_topic', DEFAULT_NTFY_TOPIC)})
            except Exception as e:
                self.send_json(500, {'error': 'خطا در ثبت تنظیمات نوتیفیکیشن'})

        # تست نوتیفیکیشن
        elif self.path == '/api/mobile/test':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length).decode('utf-8')) if length > 0 else {}
                topic = body.get('topic', '').strip() or get_setting('ntfy_topic', DEFAULT_NTFY_TOPIC)

                success = send_android_notification(
                    'تست ارسال sovapp',
                    f'ارتباط موفق با کانال [{topic}] برقرار است. (محیط: {ENV})',
                    priority='high',
                    tags='tada,iphone',
                    topic=topic
                )
                self.send_json(200, {'success': success, 'topic': topic, 'env': ENV})
            except Exception as e:
                self.send_json(500, {'error': 'خطا در ارسال نوتیفیکیشن تست'})

        # بررسی و ارسال فوری هشدارهای ۴۸ ساعته و یادآوری ۳ ساعته
        elif self.path == '/api/alerts/check_now':
            try:
                alerts_count = check_and_send_repeating_alerts()
                self.send_json(200, {'success': True, 'alerts_sent': alerts_count})
            except Exception as e:
                self.send_json(500, {'error': str(e)})

        # ذخیره‌سازی تسک‌ها در دیتابیس
        elif self.path == '/api/save':
            try:
                length = int(self.headers.get('Content-Length', 0))
                payload = json.loads(self.rfile.read(length).decode('utf-8'))
                tasks = payload.get('tasks', [])
                permanently_ignored = payload.get('permanentlyIgnoredIds', [])
                integrations_data = payload.get('integrations', None)
                now_str = datetime.now(timezone.utc).isoformat()

                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()

                for t in tasks:
                    c.execute("""
                        INSERT INTO tasks (id, source, sender, title, body, sent_at, due_date, task_status, response_status, responded_at, is_deleted, deleted_at, alert_triggered, last_alert_at, alert_count, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            due_date=excluded.due_date,
                            task_status=excluded.task_status,
                            response_status=excluded.response_status,
                            responded_at=excluded.responded_at,
                            is_deleted=excluded.is_deleted,
                            deleted_at=excluded.deleted_at,
                            alert_triggered=excluded.alert_triggered,
                            updated_at=excluded.updated_at
                    """, (
                        t['id'], t['source'], t['sender'], t['title'], t.get('body', ''),
                        t['sent_at'], t.get('due_date'), t['task_status'], t['response_status'],
                        t.get('responded_at'), 1 if t.get('is_deleted') else 0,
                        t.get('deleted_at'), 1 if t.get('alert_triggered') else 0,
                        t.get('last_alert_at'), t.get('alert_count', 0), now_str
                    ))

                c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)',
                          ('permanently_ignored', json.dumps(permanently_ignored)))

                if integrations_data is not None:
                    c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)',
                              ('integrations', json.dumps(integrations_data)))

                conn.commit()
                conn.close()

                # Trigger overdue check after saving
                check_and_send_repeating_alerts()

                self.send_json(200, {'status': 'saved_to_sqlite', 'env': ENV, 'db': DB_FILENAME})
            except Exception as e:
                self.send_json(500, {'error': f'خطا در ذخیره‌سازی: {str(e)}'})

        # پروکسی جیرا
        elif self.path == '/api/jira/sync':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length).decode('utf-8'))
                domain = body.get('domain', '').strip()
                token = body.get('token', '').strip()
                email_addr = body.get('email', '').strip()

                if domain.startswith('http://') or domain.startswith('https://'):
                    base_url = domain.rstrip('/')
                else:
                    base_url = f'https://{domain}.atlassian.net'

                jql = 'assignee = currentUser() AND resolution = Unresolved order by updated DESC'
                api_url = f'{base_url}/rest/api/2/search?jql={urllib.parse.quote(jql)}&maxResults=25'

                req = urllib.request.Request(api_url)
                req.add_header('Accept', 'application/json')

                if email_addr:
                    auth_pair = f'{email_addr}:{token}'.encode('utf-8')
                    req.add_header('Authorization', f'Basic {base64.b64encode(auth_pair).decode("utf-8")}')
                else:
                    req.add_header('Authorization', f'Bearer {token}')

                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE

                with urllib.request.urlopen(req, context=ctx, timeout=12) as response:
                    res_data = json.loads(response.read().decode('utf-8'))
                    self.send_json(200, res_data)

            except urllib.error.HTTPError as he:
                self.send_json(he.code, {'error': f'خطای سرویس جیرا: {he.code}'})
            except urllib.error.URLError:
                self.send_json(504, {'error': 'عدم دسترسی به سرور جیرا'})
            except Exception as e:
                self.send_json(500, {'error': f'خطا در ارتباط با جیرا: {str(e)}'})

        # اتصال مستقیم IMAP
        elif self.path == '/api/mail/imap_sync':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length).decode('utf-8'))
                host = body.get('host', '').strip()
                port = int(body.get('port', 993))
                username = body.get('username', '').strip()
                password = body.get('password', '').strip()
                source_label = body.get('source', 'Outlook')

                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE

                mail = imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
                mail.login(username, password)
                mail.select('INBOX', readonly=True)

                status, messages = mail.search(None, 'ALL')
                mail_ids = messages[0].split()
                recent_ids = mail_ids[-15:]
                fetched_items = []

                for m_id in reversed(recent_ids):
                    res, data = mail.fetch(m_id, '(RFC822.HEADER BODY.PEEK[TEXT])')
                    for response_part in data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])
                            subject_header = decode_header(msg['Subject'])[0]
                            sub_text = subject_header[0]
                            if isinstance(sub_text, bytes):
                                sub_text = sub_text.decode(subject_header[1] or 'utf-8', errors='ignore')
                            sender_header = decode_header(msg.get('From', ''))[0]
                            sender_text = sender_header[0]
                            if isinstance(sender_text, bytes):
                                sender_text = sender_text.decode(sender_header[1] or 'utf-8', errors='ignore')

                            date_text = msg.get('Date', '')
                            clean_id = f'imap-{host}-{m_id.decode("utf-8")}'

                            fetched_items.append({
                                'id': clean_id,
                                'source': source_label,
                                'sender': sender_text or 'نامشخص',
                                'title': sub_text or '(بدون عنوان)',
                                'body': f'دریافت شده از سرور اختصاصی {host}',
                                'sent_at': date_text
                            })

                mail.close()
                mail.logout()
                self.send_json(200, {'messages': fetched_items})
            except Exception as e:
                self.send_json(500, {'error': f'خطا در IMAP: {str(e)}'})
        else:
            self.send_error(404)

    def do_GET(self):
        # هدایت مسیر ریشه یا خالی به tasks.html
        clean_url_path = self.path.split('?')[0]
        if clean_url_path in ('', '/', '/index', '/index.html'):
            self.path = '/tasks.html'

        # اطلاعات وضعیت محیط و آدرس‌های شبکه
        if self.path == '/api/env':
            self.send_json(200, {
                'env': ENV,
                'db': DB_FILENAME,
                'port': PORT,
                'network_ips': get_network_ips(),
                'status': 'online'
            })
            return

        # وضعیت هشدارهای ۴۸ ساعته و یادآوری ۳ ساعته
        elif self.path == '/api/alerts/status':
            try:
                conn = sqlite3.connect(DB_FILE)
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                now = datetime.now(timezone.utc)
                c.execute("""
                    SELECT id, title, sender, source, sent_at, last_alert_at, alert_count
                    FROM tasks
                    WHERE is_deleted = 0
                      AND response_status != 'responded'
                      AND task_status != 'done'
                """)
                active_overdue = []
                for r in c.fetchall():
                    item = dict(r)
                    dt = parse_datetime(item.get('sent_at'))
                    if dt:
                        hours = (now - dt).total_seconds() / 3600.0
                        if hours >= 48:
                            item['hours_overdue'] = round(hours, 1)
                            active_overdue.append(item)
                conn.close()
                self.send_json(200, {
                    'active_overdue_count': len(active_overdue),
                    'tasks': active_overdue
                })
            except Exception as e:
                self.send_json(500, {'error': str(e)})
            return

        # بررسی سلامت سرویس (Health Check)
        elif self.path == '/api/health':
            self.send_json(200, {
                'status': 'healthy',
                'env': ENV,
                'db': DB_FILENAME,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
            return

        # بارگذاری دیتابیس در لود صفحه
        elif self.path == '/api/load':
            try:
                conn = sqlite3.connect(DB_FILE)
                conn.row_factory = sqlite3.Row
                c = conn.cursor()

                c.execute('SELECT * FROM tasks ORDER BY sent_at DESC')
                rows = c.fetchall()
                tasks = []
                for r in rows:
                    t = dict(r)
                    t['is_deleted'] = bool(t['is_deleted'])
                    t['alert_triggered'] = bool(t['alert_triggered'])
                    tasks.append(t)

                c.execute('SELECT value FROM settings WHERE key="permanently_ignored"')
                ignored_row = c.fetchone()
                permanently_ignored = json.loads(ignored_row['value']) if ignored_row else []

                c.execute('SELECT value FROM settings WHERE key="integrations"')
                ints_row = c.fetchone()
                saved_integrations = json.loads(ints_row['value']) if ints_row else None

                c.execute('SELECT value FROM settings WHERE key="ntfy_topic"')
                ntfy_row = c.fetchone()
                saved_topic = ntfy_row[0] if ntfy_row else DEFAULT_NTFY_TOPIC

                conn.close()

                self.send_json(200, {
                    'tasks': tasks,
                    'permanentlyIgnoredIds': permanently_ignored,
                    'integrations': saved_integrations,
                    'ntfy_topic': saved_topic,
                    'env': ENV,
                    'db': DB_FILENAME,
                    'port': PORT,
                    'network_ips': get_network_ips()
                })
            except Exception as e:
                self.send_json(500, {'error': f'خطا در بارگذاری اطلاعات: {str(e)}'})
            return

        super().do_GET()


def run_server():
    all_ips = get_network_ips()
    env_label = 'محیط تست (Test / Development)' if ENV == 'test' else 'محیط اصلی و پایدار (Production / Main)'
    print('=' * 65)
    print(f'  سرور میز مدیریت تسک‌ها (sovapp) - {env_label}')
    print(f'  دیتابیس فعال: data/{DB_FILENAME}')
    print(f'  آدرس لوکال: http://localhost:{PORT}/tasks.html')
    if all_ips:
        print(f'  آدرس واقعی در شبکه وای‌فای (برای باز کردن روی گوشی):')
        for ip in all_ips:
            print(f'    -> http://{ip}:{PORT}/tasks.html')
    print('=' * 65)

    # Start background alert monitor
    start_alert_worker()

    if os.environ.get('SOVAPP_NO_BROWSER', '0') != '1':
        webbrowser.open(f'http://localhost:{PORT}/tasks.html')

    server = http.server.HTTPServer(('0.0.0.0', PORT), TaskHubHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    run_server()
