import unittest

from wayband.telemetry import DashboardSnapshotStore


class DashboardSnapshotStoreTests(unittest.TestCase):
    def test_starts_empty(self):
        store = DashboardSnapshotStore()

        self.assertIsNone(store.get())

    def test_set_then_get_returns_the_stored_payload(self):
        store = DashboardSnapshotStore()

        store.set({"stats": {"leftSideMm": 850}})

        self.assertEqual(store.get(), {"stats": {"leftSideMm": 850}})

    def test_latest_set_replaces_the_previous_snapshot(self):
        store = DashboardSnapshotStore()
        store.set({"stats": {"leftSideMm": 850}})

        store.set({"stats": {"leftSideMm": 900}})

        self.assertEqual(store.get(), {"stats": {"leftSideMm": 900}})

    def test_mutating_the_returned_top_level_dict_does_not_affect_the_store(self):
        store = DashboardSnapshotStore()
        store.set({"stats": {"leftSideMm": 850}})

        snapshot = store.get()
        snapshot["extra"] = "not part of the store"

        self.assertNotIn("extra", store.get())


if __name__ == "__main__":
    unittest.main()
