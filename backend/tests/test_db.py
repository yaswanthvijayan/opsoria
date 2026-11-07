"""Unit tests for SQLite persistence layer (db.py)."""

import os
import tempfile
import unittest

import db


class TestSQLitePersistence(unittest.TestCase):
    """Test suite for db.py using an isolated temporary database."""

    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.db_path = self.temp_db.name
        db.init_db(self.db_path)

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            p = self.db_path + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass

    def test_self_healing_fresh_empty_database_without_init_db(self):
        """Test a fresh empty database file works without calling init_db."""
        empty_temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        empty_temp.close()
        empty_path = empty_temp.name

        try:
            # Without calling init_db:
            # 1. list returns empty
            items = db.list_incidents_from_db(db_path=empty_path)
            self.assertEqual(items, [])

            # 2. get returns None
            fetched = db.get_incident_by_id("INC-EMPTY-1", db_path=empty_path)
            self.assertIsNone(fetched)

            # 3. stats returns empty aggregates
            stats = db.get_incident_stats(db_path=empty_path)
            self.assertEqual(stats["total"], 0)
            self.assertEqual(stats["recent_incidents"], [])

            # 4. save works
            saved = db.save_or_upsert_incident(
                incident_id="INC-EMPTY-1",
                service="auth-service",
                environment="production",
                status="investigating",
                symptoms="Connection timeout",
                possible_causes=[],
                metadata={},
                confirmed_resolution=None,
                memory_status="not_applicable",
                last_analysis={"summary": "Empty DB test", "steps": []},
                db_path=empty_path,
            )
            self.assertEqual(saved["incident_id"], "INC-EMPTY-1")

            # 5. verify get returns the saved record
            verified = db.get_incident_by_id("INC-EMPTY-1", db_path=empty_path)
            self.assertIsNotNone(verified)
            self.assertEqual(verified["incident_id"], "INC-EMPTY-1")
        finally:
            for suffix in ("", "-wal", "-shm"):
                p = empty_path + suffix
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    def test_self_healing_deleting_database_between_operations_does_not_raise(self):
        """Test deleting database file between operations self-heals without raising OperationalError."""
        del_temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        del_temp.close()
        del_path = del_temp.name

        try:
            # Step 1: Save first incident
            db.save_or_upsert_incident(
                incident_id="INC-PRE-DEL",
                service="payment-service",
                environment="staging",
                status="investigating",
                symptoms="502 Bad Gateway",
                possible_causes=[],
                metadata={},
                confirmed_resolution=None,
                memory_status="not_applicable",
                last_analysis={},
                db_path=del_path,
            )
            self.assertIsNotNone(db.get_incident_by_id("INC-PRE-DEL", db_path=del_path))

            # Step 2: Simulate catastrophic deletion of database and WAL files while running
            for suffix in ("", "-wal", "-shm"):
                p = del_path + suffix
                if os.path.exists(p):
                    os.remove(p)

            # Step 3: Querying the deleted database should not raise OperationalError; recovers cleanly
            items_after_del = db.list_incidents_from_db(db_path=del_path)
            self.assertEqual(items_after_del, [])

            # Step 4: Saving a new incident should self-heal and succeed
            db.save_or_upsert_incident(
                incident_id="INC-POST-DEL",
                service="checkout-service",
                environment="production",
                status="investigating",
                symptoms="Timeout",
                possible_causes=[],
                metadata={},
                confirmed_resolution=None,
                memory_status="not_applicable",
                last_analysis={},
                db_path=del_path,
            )
            saved_post = db.get_incident_by_id("INC-POST-DEL", db_path=del_path)
            self.assertIsNotNone(saved_post)
            self.assertEqual(saved_post["incident_id"], "INC-POST-DEL")
        finally:
            for suffix in ("", "-wal", "-shm"):
                p = del_path + suffix
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    def test_save_and_get_incident(self):
        """Test inserting a new incident and reading it back."""
        res = db.save_or_upsert_incident(
            incident_id="INC-DB-001",
            service="order-service",
            environment="production",
            status="investigating",
            symptoms="Deadlock on order creation",
            possible_causes=["Lock contention on orders table"],
            metadata={"priority": "high", "type": "synthetic_test"},
            confirmed_resolution=None,
            memory_status="not_applicable",
            last_analysis={"summary": "Test summary", "steps": []},
            db_path=self.db_path,
        )

        self.assertEqual(res["incident_id"], "INC-DB-001")
        self.assertEqual(res["status"], "investigating")
        self.assertTrue(res["is_synthetic"])
        self.assertEqual(res["possible_causes"], ["Lock contention on orders table"])

        # Fetch by ID
        fetched = db.get_incident_by_id("INC-DB-001", self.db_path)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["incident_id"], "INC-DB-001")
        self.assertEqual(fetched["service"], "order-service")
        self.assertEqual(fetched["memory_status"], "not_applicable")

    def test_resolve_incident(self):
        """Test resolving an existing incident updates status, resolution, and memory_status."""
        db.save_or_upsert_incident(
            incident_id="INC-DB-002",
            service="payment-service",
            environment="production",
            status="investigating",
            symptoms="Gateway timeout",
            possible_causes=[],
            metadata={},
            confirmed_resolution=None,
            memory_status="not_applicable",
            last_analysis={},
            db_path=self.db_path,
        )

        resolved = db.resolve_incident_in_db(
            incident_id="INC-DB-002",
            confirmed_resolution="Restarted gateway pods and bumped timeout to 60s.",
            memory_status="persisted",
            last_analysis={"summary": "Resolved", "historical_context": []},
            db_path=self.db_path,
        )

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["confirmed_resolution"], "Restarted gateway pods and bumped timeout to 60s.")
        self.assertEqual(resolved["memory_status"], "persisted")

        # Resolve unknown incident returns None
        self.assertIsNone(db.resolve_incident_in_db("INC-NONEXISTENT", "Fix", "persisted", {}, self.db_path))

    def test_upsert_never_downgrades_resolved_incident(self):
        """Test that re-ingesting an already resolved incident never reverts its status or resolution."""
        # 1. Ingest incident
        db.save_or_upsert_incident(
            incident_id="INC-DB-003",
            service="auth-service",
            environment="production",
            status="investigating",
            symptoms="Login failures",
            possible_causes=["Token validation error"],
            metadata={},
            confirmed_resolution=None,
            memory_status="not_applicable",
            last_analysis={"version": 1},
            db_path=self.db_path,
        )

        # 2. Resolve incident
        db.resolve_incident_in_db(
            incident_id="INC-DB-003",
            confirmed_resolution="Renewed expired cert in vault.",
            memory_status="persisted",
            last_analysis={"version": 2},
            db_path=self.db_path,
        )

        # 3. Re-ingest with status="investigating"
        updated = db.save_or_upsert_incident(
            incident_id="INC-DB-003",
            service="auth-service",
            environment="production",
            status="investigating",
            symptoms="Refreshed symptom report",
            possible_causes=["New hypothesis"],
            metadata={},
            confirmed_resolution=None,
            memory_status="not_applicable",
            last_analysis={"version": 3},
            db_path=self.db_path,
        )

        # Status, confirmed_resolution, and memory_status must be preserved!
        self.assertEqual(updated["status"], "resolved")
        self.assertEqual(updated["confirmed_resolution"], "Renewed expired cert in vault.")
        self.assertEqual(updated["memory_status"], "persisted")
        # last_analysis was refreshed
        self.assertEqual(updated["last_analysis"], {"version": 3})

    def test_list_and_filter_incidents(self):
        """Test listing incidents ordered newest first, with optional status filter."""
        for i in range(1, 4):
            db.save_or_upsert_incident(
                incident_id=f"INC-LIST-{i}",
                service="svc",
                environment="prod",
                status="investigating" if i < 3 else "resolved",
                symptoms=f"Symptom {i}",
                possible_causes=[],
                metadata={},
                confirmed_resolution="Fix" if i == 3 else None,
                memory_status="persisted" if i == 3 else "not_applicable",
                last_analysis={},
                db_path=self.db_path,
            )

        all_items = db.list_incidents_from_db(db_path=self.db_path)
        self.assertEqual(len(all_items), 3)

        resolved_items = db.list_incidents_from_db(status="resolved", db_path=self.db_path)
        self.assertEqual(len(resolved_items), 1)
        self.assertEqual(resolved_items[0]["incident_id"], "INC-LIST-3")

    def test_get_stats(self):
        """Test aggregate statistics calculations."""
        # 1 synthetic resolved persisted
        db.save_or_upsert_incident(
            incident_id="INC-STAT-1",
            service="s1",
            environment="prod",
            status="resolved",
            symptoms="err1",
            possible_causes=[],
            metadata={"type": "synthetic_test"},
            confirmed_resolution="res1",
            memory_status="persisted",
            last_analysis={},
            db_path=self.db_path,
        )
        # 1 non-synthetic investigating not_applicable
        db.save_or_upsert_incident(
            incident_id="INC-STAT-2",
            service="s2",
            environment="prod",
            status="investigating",
            symptoms="err2",
            possible_causes=[],
            metadata={},
            confirmed_resolution=None,
            memory_status="not_applicable",
            last_analysis={},
            db_path=self.db_path,
        )
        # 1 resolved not_persisted
        db.save_or_upsert_incident(
            incident_id="INC-STAT-3",
            service="s3",
            environment="prod",
            status="resolved",
            symptoms="err3",
            possible_causes=[],
            metadata={},
            confirmed_resolution="res3",
            memory_status="not_persisted",
            last_analysis={},
            db_path=self.db_path,
        )

        stats = db.get_incident_stats(self.db_path)
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["resolved_count"], 2)
        self.assertEqual(stats["persisted_count"], 1)
        self.assertEqual(stats["not_persisted_count"], 1)
        self.assertEqual(stats["synthetic_count"], 1)
        self.assertEqual(stats["by_status"]["resolved"], 2)
        self.assertEqual(stats["by_status"]["investigating"], 1)
        self.assertEqual(len(stats["recent_incidents"]), 3)


if __name__ == "__main__":
    unittest.main()

