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
from email.header import decode_header
import webbrowser
import socket
from datetime import datetime, timezone

# ==========================================
# Environment & Configuration
# ==========================================
# Environments: 'production' (main client) or 'test' (staging/testing)
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


def get_network_ips():
    ips = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if ':' not in ip and not ip.startswith('127.'):
                if ip not in ips:
                    ips.append(ip)
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        primary = s.getsockname()[0]
        s.close()
        if primary not in ips and not primary.startswith('127.'):
            ips.insert(0, primary)
    except Exception:
        pass
    return ips if ips else ['127.0.0.1']


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
            alert_triggered INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

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


class TaskHubHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        # Security: Prevent directory traversal outside BASE_DIR
        clean_path = super().translate_path(path)
        rel = os.path.relpath(clean_path, BASE_DIR)
        if rel.startswith('..') or os.path.isabs(rel):
            return os.path.join(BASE_DIR, '__invalid_path__')
        return clean_path

    def end_headers(self):
        # Security & CORS headers
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
        # تنظیم کانال نوتیفیکیشن موبایل
        if self.path == '/api/settings/mobile':
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

        # ذخیره‌سازی تسک‌ها در دیتابیس
        elif self.path == '/api/save':
            try:
                length = int(self.headers.get('Content-Length', 0))
                payload = json.loads(self.rfile.read(length).decode('utf-8'))
                tasks = payload.get('tasks', [])
                permanently_ignored = payload.get('permanentlyIgnoredIds', [])
                integrations_data = payload.get('integrations', None)

                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()

                for t in tasks:
                    if t.get('alert_triggered') and t.get('response_status') != 'responded' and not t.get('is_deleted'):
                        c.execute('SELECT alert_triggered FROM tasks WHERE id = ?', (t['id'],))
                        row = c.fetchone()
                        if not row or not row[0]:
                            send_android_notification(
                                f'هشدار مهلت ۴۸ ساعته [{t["source"]}]',
                                f'فرستنده: {t["sender"]}\nموضوع: {t["title"]}',
                                priority='high',
                                tags='warning,hourglass'
                            )

                    c.execute("""
                        INSERT INTO tasks (id, source, sender, title, body, sent_at, due_date, task_status, response_status, responded_at, is_deleted, deleted_at, alert_triggered)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            due_date=excluded.due_date,
                            task_status=excluded.task_status,
                            response_status=excluded.response_status,
                            responded_at=excluded.responded_at,
                            is_deleted=excluded.is_deleted,
                            deleted_at=excluded.deleted_at,
                            alert_triggered=excluded.alert_triggered
                    """, (
                        t['id'], t['source'], t['sender'], t['title'], t.get('body', ''),
                        t['sent_at'], t.get('due_date'), t['task_status'], t['response_status'],
                        t.get('responded_at'), 1 if t.get('is_deleted') else 0,
                        t.get('deleted_at'), 1 if t.get('alert_triggered') else 0
                    ))

                c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)',
                          ('permanently_ignored', json.dumps(permanently_ignored)))

                if integrations_data is not None:
                    c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)',
                              ('integrations', json.dumps(integrations_data)))

                conn.commit()
                conn.close()
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
        # اطلاعات وضعیت محیط
        if self.path == '/api/env':
            self.send_json(200, {
                'env': ENV,
                'db': DB_FILENAME,
                'port': PORT,
                'status': 'online'
            })
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
                    'port': PORT
                })
            except Exception as e:
                self.send_json(500, {'error': f'خطا در بارگذاری اطلاعات: {str(e)}'})
            return

        # هدایت مسیر ریشه به tasks.html
        elif self.path in ('/', '/index', '/index.html'):
            self.path = '/tasks.html'

        super().do_GET()


def run_server():
    all_ips = get_network_ips()
    env_label = 'محیط تست (Test / Development)' if ENV == 'test' else 'محیط اصلی و پایدار (Production / Main)'
    print('=' * 65)
    print(f'  سرور میز مدیریت تسک‌ها (sovapp) - {env_label}')
    print(f'  دیتابیس فعال: data/{DB_FILENAME}')
    print(f'  آدرس لوکال: http://localhost:{PORT}/tasks.html')
    print(f'  آدرس برای دسترسی در شبکه وای‌فای (پورت {PORT}):')
    for ip in all_ips:
        hint = ' (وای‌فای اصلی)' if ip.startswith('192.168.') or ip.startswith('10.') else ''
        print(f'    -> http://{ip}:{PORT}/tasks.html{hint}')
    print('=' * 65)

    if os.environ.get('SOVAPP_NO_BROWSER', '0') != '1':
        webbrowser.open(f'http://localhost:{PORT}/tasks.html')

    server = http.server.HTTPServer(('0.0.0.0', PORT), TaskHubHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    run_server()
