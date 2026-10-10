import unittest
import os
import sys
import json
import sqlite3
import tempfile
import threading
import http.client
from datetime import datetime, timezone, timedelta

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import server


class TestServer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, 'tasks_test_unit.db')
        server.init_db(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_database_initialization(self):
        """Verify tables and columns exist in newly initialized db."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in c.fetchall()]
        self.assertIn('tasks', tables)
        self.assertIn('settings', tables)

        c.execute("PRAGMA table_info(tasks)")
        columns = [row[1] for row in c.fetchall()]
        self.assertIn('last_alert_at', columns)
        self.assertIn('alert_count', columns)
        self.assertIn('updated_at', columns)
        conn.close()

    def test_settings_storage(self):
        success = server.set_setting('test_key', 'test_value', db_path=self.db_path)
        self.assertTrue(success)
        val = server.get_setting('test_key', db_path=self.db_path)
        self.assertEqual(val, 'test_value')

    def test_repeating_alerts_logic_48h_and_3h(self):
        """Verify 48h initial alert and 3h repeating alert triggers."""
        now = datetime.now(timezone.utc)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Task 1: 50 hours old, no alert sent yet -> Should trigger initial alert
        t1_sent = (now - timedelta(hours=50)).isoformat()
        c.execute("""
            INSERT INTO tasks (id, source, sender, title, sent_at, response_status, task_status, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """, ('task-50h', 'Gmail', 'Sender1', '50 Hours Old', t1_sent, 'pending_response', 'pending'))

        # Task 2: 60 hours old, last alert was 4 hours ago -> Should trigger 3h repeating alert
        t2_sent = (now - timedelta(hours=60)).isoformat()
        t2_last_alert = (now - timedelta(hours=4)).isoformat()
        c.execute("""
            INSERT INTO tasks (id, source, sender, title, sent_at, response_status, task_status, is_deleted, alert_triggered, last_alert_at, alert_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, ?, 1)
        """, ('task-repeating', 'Outlook', 'Sender2', '60 Hours Old', t2_sent, 'pending_response', 'pending', t2_last_alert))

        # Task 3: 55 hours old, last alert was 1 hour ago -> Should NOT trigger alert yet (<3h)
        t3_sent = (now - timedelta(hours=55)).isoformat()
        t3_last_alert = (now - timedelta(hours=1)).isoformat()
        c.execute("""
            INSERT INTO tasks (id, source, sender, title, sent_at, response_status, task_status, is_deleted, alert_triggered, last_alert_at, alert_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, ?, 1)
        """, ('task-recent-alert', 'Jira', 'Sender3', 'Recent Alert', t3_sent, 'pending_response', 'pending', t3_last_alert))

        # Task 4: 70 hours old, but ALREADY RESPONDED -> Should NOT trigger alert
        t4_sent = (now - timedelta(hours=70)).isoformat()
        c.execute("""
            INSERT INTO tasks (id, source, sender, title, sent_at, response_status, task_status, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """, ('task-responded', 'Gmail', 'Sender4', 'Responded', t4_sent, 'responded', 'pending'))

        conn.commit()
        conn.close()

        # Run alert check with a dummy notify function that succeeds
        sent_notifications = []
        def mock_notify(title, msg, priority, tags, topic):
            sent_notifications.append({'title': title, 'msg': msg})
            return True

        alerts_count = server.check_and_send_repeating_alerts(db_path=self.db_path, force_notification_fn=mock_notify)

        # Expected: exactly 2 alerts sent (Task 1 and Task 2)
        self.assertEqual(alerts_count, 2)
        self.assertEqual(len(sent_notifications), 2)
        self.assertIn('🔴 هشدار مهلت ۴۸ ساعته', sent_notifications[0]['title'])
        self.assertIn('⏰ یادآوری مکرر', sent_notifications[1]['title'])

        # Verify DB updated
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT alert_triggered, alert_count FROM tasks WHERE id='task-50h'")
        r1 = c.fetchone()
        self.assertEqual(r1[0], 1)
        self.assertEqual(r1[1], 1)

        c.execute("SELECT alert_count FROM tasks WHERE id='task-repeating'")
        r2 = c.fetchone()
        self.assertEqual(r2[0], 2)
        conn.close()


class TestLiveHTTPEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_port = 8992
        server.PORT = cls.test_port
        cls.httpd = server.http.server.HTTPServer(('127.0.0.1', cls.test_port), server.TaskHubHandler)
        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_api_health(self):
        conn = http.client.HTTPConnection('127.0.0.1', self.test_port, timeout=5)
        conn.request('GET', '/api/health')
        res = conn.getresponse()
        self.assertEqual(res.status, 200)
        data = json.loads(res.read().decode('utf-8'))
        self.assertEqual(data.get('status'), 'healthy')
        conn.close()

    def test_api_env_and_network_ips(self):
        conn = http.client.HTTPConnection('127.0.0.1', self.test_port, timeout=5)
        conn.request('GET', '/api/env')
        res = conn.getresponse()
        self.assertEqual(res.status, 200)
        data = json.loads(res.read().decode('utf-8'))
        self.assertIn('network_ips', data)
        self.assertTrue(len(data['network_ips']) > 0)
        conn.close()

    def test_wifi_sync_api(self):
        """Verify POST /api/sync merges mobile tasks with desktop server."""
        conn = http.client.HTTPConnection('127.0.0.1', self.test_port, timeout=5)
        mobile_task = {
            'id': f'mobile-sync-task-{int(datetime.now(timezone.utc).timestamp())}',
            'source': 'MobilePhone',
            'sender': 'PhoneUser',
            'title': 'Task created on Mobile during walk',
            'body': 'Notes taken on phone',
            'sent_at': datetime.now(timezone.utc).isoformat(),
            'due_date': None,
            'task_status': 'pending',
            'response_status': 'pending_response'
        }
        body = json.dumps({'tasks': [mobile_task]}).encode('utf-8')
        conn.request('POST', '/api/sync', body=body, headers={'Content-Type': 'application/json'})
        res = conn.getresponse()
        self.assertEqual(res.status, 200)
        data = json.loads(res.read().decode('utf-8'))
        self.assertTrue(data.get('success'))
        returned_ids = [t['id'] for t in data.get('tasks', [])]
        self.assertIn(mobile_task['id'], returned_ids)
        conn.close()


if __name__ == '__main__':
    unittest.main()
