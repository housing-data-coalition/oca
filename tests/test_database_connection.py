import unittest
from unittest import mock

from psycopg2 import OperationalError

from lib.database import Database, _connect_params


class ConnectParamsTests(unittest.TestCase):
    def test_default_keepalive_params(self):
        with mock.patch.dict('os.environ', {}, clear=True):
            params = _connect_params()
        self.assertEqual(params['keepalives'], 1)
        self.assertEqual(params['keepalives_idle'], 60)
        self.assertEqual(params['keepalives_interval'], 10)
        self.assertEqual(params['keepalives_count'], 5)

    def test_keepalive_env_overrides(self):
        with mock.patch.dict('os.environ', {
            'DB_KEEPALIVES_IDLE': '120',
            'DB_KEEPALIVES_INTERVAL': '20',
        }, clear=True):
            params = _connect_params()
        self.assertEqual(params['keepalives_idle'], 120)
        self.assertEqual(params['keepalives_interval'], 20)


class EnsureConnectionTests(unittest.TestCase):
    @staticmethod
    def _mock_connection():
        conn = mock.Mock()
        cursor = mock.MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.__exit__.return_value = False
        conn.cursor.return_value = cursor
        return conn

    @mock.patch('lib.database.psycopg2.connect')
    def test_ensure_connection_returns_false_when_healthy(self, connect_mock):
        conn = self._mock_connection()
        connect_mock.return_value = conn
        db = Database(db_url='postgres://example')
        connect_mock.reset_mock()

        reconnected = db.ensure_connection()

        self.assertFalse(reconnected)
        connect_mock.assert_not_called()
        conn.cursor.assert_called()

    @mock.patch('lib.database.psycopg2.connect')
    def test_ensure_connection_reconnects_on_operational_error(self, connect_mock):
        dead_conn = self._mock_connection()
        dead_cursor = dead_conn.cursor.return_value.__enter__.return_value
        dead_cursor.execute.side_effect = OperationalError('SSL SYSCALL error: EOF detected')

        live_conn = self._mock_connection()
        connect_mock.side_effect = [dead_conn, live_conn]

        db = Database(db_url='postgres://example')
        connect_mock.reset_mock()
        connect_mock.side_effect = [live_conn]

        reconnected = db.ensure_connection()

        self.assertTrue(reconnected)
        self.assertIs(db.conn, live_conn)
        connect_mock.assert_called_once()
        self.assertEqual(
            connect_mock.call_args,
            mock.call('postgres://example', **_connect_params()),
        )

    @mock.patch('lib.database.psycopg2.connect')
    def test_ensure_connection_restores_search_path_after_reconnect(self, connect_mock):
        initial_conn = self._mock_connection()
        connect_mock.return_value = initial_conn

        db = Database(db_url='postgres://example', schema='oca_refactor')

        dead_cursor = initial_conn.cursor.return_value.__enter__.return_value
        dead_cursor.execute.side_effect = OperationalError('connection closed')

        live_conn = self._mock_connection()
        connect_mock.side_effect = [live_conn]

        db.ensure_connection()

        live_cursor = live_conn.cursor.return_value.__enter__.return_value
        execute_calls = [str(call.args[0]) for call in live_cursor.execute.call_args_list]
        self.assertTrue(any('search_path' in call for call in execute_calls))

    @mock.patch('lib.database.psycopg2.connect')
    def test_sql_uses_reconnected_connection(self, connect_mock):
        dead_conn = self._mock_connection()
        dead_cursor = dead_conn.cursor.return_value.__enter__.return_value
        dead_cursor.execute.side_effect = [
            OperationalError('EOF detected'),
        ]

        live_conn = self._mock_connection()
        connect_mock.side_effect = [dead_conn, live_conn]

        db = Database(db_url='postgres://example')
        connect_mock.reset_mock()
        connect_mock.side_effect = [live_conn]

        db.ensure_connection()
        db.sql('SELECT 2')

        live_conn.commit.assert_called()


if __name__ == '__main__':
    unittest.main()
