import asyncio
import unittest
from unittest.mock import patch

from app.exchanges.public_adapters import PublicExchangeAdapter


class StubPublicAdapter(PublicExchangeAdapter):
    async def _subscribe(self, websocket):
        return


class PublicAdapterLifecycleDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.adapter = StubPublicAdapter("test", True, "wss://example.invalid", "BTCUSDT")

    def test_initial_status_exposes_zero_counters_and_unknown_uptime(self):
        with patch("app.exchanges.public_adapters.time.time", return_value=100.0):
            status = asyncio.run(self.adapter.status())
        self.assertEqual(status["connection_attempt_count"], 0)
        self.assertEqual(status["successful_connection_count"], 0)
        self.assertEqual(status["reconnect_count"], 0)
        self.assertIsNone(status["connected_duration_seconds"])
        self.assertIsNone(status["last_connection_duration_seconds"])
        self.assertIsNone(status["last_connection_attempt_at"])
        self.assertIsNone(status["last_connected_at"])
        self.assertIsNone(status["last_disconnect_at"])
        self.assertIsNone(status["last_reconnect_at"])

    def test_success_and_disconnect_record_attempts_and_session_duration(self):
        self.adapter._record_connection_attempt(now=10.0)
        self.adapter._record_connection_success(now=11.0, monotonic_now=100.0)
        with patch("app.exchanges.public_adapters.time.time", return_value=13.5):
            with patch("app.exchanges.public_adapters.time.monotonic", return_value=102.5):
                connected = asyncio.run(self.adapter.status())
        self.assertEqual(connected["connection_attempt_count"], 1)
        self.assertEqual(connected["successful_connection_count"], 1)
        self.assertEqual(connected["connected_duration_seconds"], 2.5)
        self.assertIsNone(connected["last_connection_duration_seconds"])
        self.assertIsNone(connected["last_reconnect_at"])

        self.adapter._record_connection_end(now=14.0, monotonic_now=103.0)
        with patch("app.exchanges.public_adapters.time.time", return_value=15.0):
            with patch("app.exchanges.public_adapters.time.monotonic", return_value=103.5):
                disconnected = asyncio.run(self.adapter.status())
        self.assertFalse(disconnected["connected"])
        self.assertIsNone(disconnected["connected_duration_seconds"])
        self.assertEqual(disconnected["last_connection_duration_seconds"], 3.0)
        self.assertEqual(disconnected["last_disconnect_at"], 14.0)

    def test_successful_reconnect_records_second_attempt_and_reconnect_time(self):
        self.adapter._record_connection_attempt(now=10.0)
        self.adapter._record_connection_success(now=11.0, monotonic_now=100.0)
        self.adapter._record_connection_end(now=12.0, monotonic_now=101.0)
        self.adapter._record_connection_attempt(now=20.0)
        self.adapter._record_connection_success(now=21.0, monotonic_now=200.0)
        with patch("app.exchanges.public_adapters.time.time", return_value=23.0):
            with patch("app.exchanges.public_adapters.time.monotonic", return_value=202.0):
                status = asyncio.run(self.adapter.status())
        self.assertEqual(status["connection_attempt_count"], 2)
        self.assertEqual(status["successful_connection_count"], 2)
        self.assertEqual(status["last_reconnect_at"], 21.0)
        self.assertEqual(status["connected_duration_seconds"], 2.0)
        self.assertEqual(status["last_connection_duration_seconds"], 1.0)

    def test_message_age_uses_monotonic_clock_when_wall_clock_moves_backward(self):
        self.adapter.last_message_at = 110.0
        self.adapter.last_message_monotonic = 100.0
        with patch("app.exchanges.public_adapters.time.time", return_value=90.0):
            with patch("app.exchanges.public_adapters.time.monotonic", return_value=101.5):
                status = asyncio.run(self.adapter.status())
        self.assertEqual(status["last_message_age_seconds"], 1.5)


    def test_connected_and_completed_session_uptime_use_monotonic_clock_when_wall_clock_moves_backward(self):
        self.adapter._record_connection_success(now=110.0, monotonic_now=100.0)
        with patch("app.exchanges.public_adapters.time.time", return_value=90.0):
            with patch("app.exchanges.public_adapters.time.monotonic", return_value=101.5):
                connected = asyncio.run(self.adapter.status())
        self.assertEqual(connected["connected_duration_seconds"], 1.5)


        self.adapter._record_connection_end(now=90.0, monotonic_now=103.5)
        with patch("app.exchanges.public_adapters.time.time", return_value=91.0):
            with patch("app.exchanges.public_adapters.time.monotonic", return_value=104.0):
                disconnected = asyncio.run(self.adapter.status())
        self.assertEqual(disconnected["last_connection_duration_seconds"], 3.5)
        self.assertEqual(disconnected["last_disconnect_at"], 90.0)

    def test_run_records_actual_connect_and_message_lifecycle(self):
        adapter = self.adapter

        class FakeWebsocket:
            async def __aiter__(self):
                yield '{"type":"test"}'
                adapter._stop.set()

        class FakeConnect:
            async def __aenter__(self):
                return FakeWebsocket()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        async def run():
            with patch("app.exchanges.public_adapters.websockets.connect", return_value=FakeConnect()):
                with patch("app.exchanges.public_adapters.time.time", side_effect=[50.0, 51.0, 52.0, 53.0, 54.0]):
                    with patch("app.exchanges.public_adapters.time.monotonic", side_effect=[100.0, 101.0, 102.0, 103.0]):
                        await adapter._run()
                        return await adapter.status()

        status = asyncio.run(run())
        self.assertEqual(status["connection_attempt_count"], 1)
        self.assertEqual(status["successful_connection_count"], 1)
        self.assertEqual(status["last_connection_attempt_at"], 50.0)
        self.assertEqual(status["last_connected_at"], 51.0)
        self.assertEqual(status["last_disconnect_at"], 53.0)
        self.assertEqual(status["last_connection_duration_seconds"], 2.0)
        self.assertEqual(status["last_message_age_seconds"], 2.0)
        self.assertIsNone(status["connected_duration_seconds"])
        self.assertFalse(status["connected"])


if __name__ == "__main__":
    unittest.main()
