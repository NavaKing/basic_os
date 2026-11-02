"""Save sync: page loads that arrive together must not read and import the save twice."""
import threading
import time
import unittest
from unittest import mock

import tests  # noqa: F401  (sets up the throwaway database first)
import save_sync


class ConcurrentSync(unittest.TestCase):
    def test_parallel_page_loads_sync_once(self):
        reads = []

        def slow_read(path):
            reads.append(path)
            time.sleep(0.3)  # the real reader takes a minute; long enough for the other request to arrive
            raise RuntimeError("stop after reading")  # skip the import; the version is then left unset

        save_sync.set_state('save_version', None)
        with mock.patch.object(save_sync, "newest_save", return_value=__file__), \
             mock.patch.object(save_sync, "read_save", side_effect=slow_read):
            threads = [threading.Thread(target=save_sync.sync_if_changed) for _ in range(2)]
            start = time.perf_counter()
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        # Both requests read here because the first one failed; what matters is that they took turns
        self.assertEqual(len(reads), 2)
        self.assertGreaterEqual(time.perf_counter() - start, 0.6)

    def test_second_load_skips_after_first_syncs(self):
        version = f"{__file__}|{__import__('os').path.getmtime(__file__)}"
        calls = []

        def first_sync():
            calls.append("synced")
            save_sync.set_state('save_version', version)
            return "Synced"

        save_sync.set_state('save_version', None)
        with mock.patch.object(save_sync, "newest_save", return_value=__file__), \
             mock.patch.object(save_sync, "read_save", side_effect=lambda path: calls.append("read") or time.sleep(0.2) or {}), \
             mock.patch.object(save_sync, "sync_schedule", side_effect=lambda d: (_ for _ in ()).throw(KeyError("skip"))):
            # Simulate: request A is mid-sync (holds the lock) and finishes by recording the version
            with save_sync._sync_lock:
                waiter = threading.Thread(target=save_sync.sync_if_changed)
                waiter.start()
                time.sleep(0.1)
                first_sync()
            waiter.join()
        self.assertEqual(calls, ["synced"])  # the waiting request saw the new version and didn't read the save


if __name__ == "__main__":
    unittest.main()
