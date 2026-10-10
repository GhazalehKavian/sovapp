import unittest
import os
import sys
import json
import sqlite3
import tempfile
import threading
import http.client
from datetime import datetime, timezone

# Add project root to sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import server


class TestServer(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory and test database
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, 'tasks_test_unit.db')
        server.init_db(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_database_initialization(self):
        """Verify tables and default topic exist in newly initialized db."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in c.fetchall()]
        self.assertIn('tasks', tables)
        self.assertIn('settings', tables)

        c.execute("SELECT value FROM settings WHERE key='ntfy_topic'")
        topic_row = c.fetchone()
        self.assertIsNotNone(topic_row)
        conn.close()

    def test_settings_storage(self):
        """Verify settings get/set functionality."""
        success = server.set_setting('test_key', 'test_value', db_path=self.db_path)
        self.assertTrue(success)
        val = server.get_setting('test_key', db_path=self.db_path)
        self.assertEqual(val, 'test_value')

    def test_environment_values(self):
        """Verify environment variable detection."""
        self.assertIn(server.ENV, ['production', 'test'])
        self.assertIn(server.DB_FILENAME, ['tasks.db', 'tasks_test.db'])

    def test_task_insertion_and_query(self):
        """Verify tasks can be inserted and queried properly."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        task_id = 'task-test-001'
        c.execute("""
            INSERT INTO tasks (id, source, sender, title, body, sent_at, task_status, response_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (task_id, 'Manual', 'Tester', 'Test Task', 'Body content', datetime.now(timezone.utc).isoformat(), 'pending', 'pending_response'))
        conn.commit()

        c.execute("SELECT title, sender FROM tasks WHERE id = ?", (task_id,))
        row = c.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 'Test Task')
        self.assertEqual(row[1], 'Tester')
        conn.close()


class TestLiveHTTPEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Run live HTTP server on a test port
        cls.test_port = 8991
        server.PORT = cls.test_port
        cls.httpd = server.http.server.HTTPServer(('127.0.0.1', cls.test_port), server.TaskHubHandler)
        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_api_health(self):
        """Verify /api/health returns 200 with healthy status."""
        conn = http.client.HTTPConnection('127.0.0.1', self.test_port, timeout=5)
        conn.request('GET', '/api/health')
        res = conn.getresponse()
        self.assertEqual(res.status, 200)
        data = json.loads(res.read().decode('utf-8'))
        self.assertEqual(data.get('status'), 'healthy')
        self.assertIn('env', data)
        conn.close()

    def test_api_env(self):
        """Verify /api/env returns environment info."""
        conn = http.client.HTTPConnection('127.0.0.1', self.test_port, timeout=5)
        conn.request('GET', '/api/env')
        res = conn.getresponse()
        self.assertEqual(res.status, 200)
        data = json.loads(res.read().decode('utf-8'))
        self.assertIn('env', data)
        self.assertIn('db', data)
        conn.close()

    def test_security_headers(self):
        """Verify security headers are attached in responses."""
        conn = http.client.HTTPConnection('127.0.0.1', self.test_port, timeout=5)
        conn.request('GET', '/api/health')
        res = conn.getresponse()
        self.assertEqual(res.getheader('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(res.getheader('X-Frame-Options'), 'SAMEORIGIN')
        self.assertEqual(res.getheader('Referrer-Policy'), 'strict-origin-when-cross-origin')
        res.read()
        conn.close()

    def test_save_and_load_api(self):
        """Verify /api/save and /api/load roundtrip."""
        conn = http.client.HTTPConnection('127.0.0.1', self.test_port, timeout=5)
        new_task = {
            'id': f'auto-unit-test-{int(datetime.now(timezone.utc).timestamp())}',
            'source': 'UnitTest',
            'sender': 'AutoRunner',
            'title': 'Automated Test Task',
            'body': 'Automated test task body',
            'sent_at': datetime.now(timezone.utc).isoformat(),
            'due_date': None,
            'task_status': 'pending',
            'response_status': 'pending_response',
            'responded_at': None,
            'is_deleted': False,
            'deleted_at': None,
            'alert_triggered': False
        }
        body = json.dumps({'tasks': [new_task], 'permanentlyIgnoredIds': []}).encode('utf-8')
        conn.request('POST', '/api/save', body=body, headers={'Content-Type': 'application/json'})
        save_res = conn.getresponse()
        self.assertEqual(save_res.status, 200)
        save_res.read()

        # Load
        conn.request('GET', '/api/load')
        load_res = conn.getresponse()
        self.assertEqual(load_res.status, 200)
        load_data = json.loads(load_res.read().decode('utf-8'))
        task_ids = [t['id'] for t in load_data.get('tasks', [])]
        self.assertIn(new_task['id'], task_ids)
        conn.close()


if __name__ == '__main__':
    unittest.main()
