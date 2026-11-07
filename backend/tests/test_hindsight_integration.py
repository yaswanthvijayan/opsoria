"""Comprehensive unit test suite for Opsoria Hindsight integration.

Uses mocked Hindsight SDK responses to test:
- Client initialization and safe fallback
- Successful Retain and Recall operations
- Empty Recall results handling
- API failures and timeout handling
- Duplicate prevention (checksum cache & restart persistence)
- Document grouping and update_mode='replace'
- Hang-free close() lifecycle management
- Integration with Opsoria ingestion workflow and main.py
- Preservation of hypothesis vs confirmed fact distinctions
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import main
from hindsight_memory import HindsightMemoryConfig, HindsightMemoryManager
from incident_processor import IncidentProcessor
from models import HistoricalIncidentContext, Incident


class TestHindsightMemoryManager(unittest.TestCase):
    """Tests for HindsightMemoryManager with mocked Hindsight SDK client."""

    def setUp(self):
        self.temp_cache = tempfile.NamedTemporaryFile(delete=False)
        self.temp_cache.close()
        self.config = HindsightMemoryConfig(
            base_url="https://api.hindsight.vectorize.io",
            bank_id="opsoria-incidents",
            api_key="mock_secret_key_12345",
            timeout=45.0,
            cache_file=self.temp_cache.name,
        )

    def tearDown(self):
        if os.path.exists(self.temp_cache.name):
            try:
                os.remove(self.temp_cache.name)
            except OSError:
                pass

    @patch("hindsight_memory.Hindsight")
    def test_client_initialization_success(self, mock_hindsight_cls):
        """Verify client initializes with expected parameters."""
        mock_instance = MagicMock()
        mock_hindsight_cls.return_value = mock_instance

        manager = HindsightMemoryManager(config=self.config)

        self.assertTrue(manager.is_available)
        mock_hindsight_cls.assert_called_once_with(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
            timeout=45.0,
        )
        manager.close()

    @patch("hindsight_memory.Hindsight")
    def test_client_initialization_missing_api_key(self, mock_hindsight_cls):
        """Verify graceful fallback without crash when API key is missing."""
        no_key_config = HindsightMemoryConfig(api_key=None, cache_file=self.temp_cache.name)
        manager = HindsightMemoryManager(config=no_key_config)

        self.assertFalse(manager.is_available)
        mock_hindsight_cls.assert_not_called()
        manager.close()

    @patch("hindsight_memory.Hindsight")
    def test_client_initialization_failure_does_not_crash(self, mock_hindsight_cls):
        """Verify initialization exceptions are handled safely without leaking credentials."""
        mock_hindsight_cls.side_effect = ConnectionError("Failed to connect with key mock_secret_key_12345")

        manager = HindsightMemoryManager(config=self.config)
        self.assertFalse(manager.is_available)
        manager.close()

    @patch("hindsight_memory.Hindsight")
    def test_retain_incident_success(self, mock_hindsight_cls):
        """Test successful Retain operation using stable document_id and update_mode='replace'."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.success = True
        mock_response.bank_id = "opsoria-incidents"
        mock_client.retain.return_value = mock_response
        mock_hindsight_cls.return_value = mock_client

        manager = HindsightMemoryManager(config=self.config)
        incident = Incident(
            incident_id="INC-101",
            service="auth-service",
            symptoms="Token expiration errors on login",
            environment="production",
            status="investigating",
            possible_causes=["Clock skew on auth cluster node"],
        )

        result = manager.retain_incident(incident)

        self.assertTrue(result)
        mock_client.retain.assert_called_once()
        call_kwargs = mock_client.retain.call_args[1]

        self.assertEqual(call_kwargs["bank_id"], "opsoria-incidents")
        self.assertEqual(call_kwargs["document_id"], "INC-101")
        self.assertEqual(call_kwargs["update_mode"], "replace")
        self.assertIn("auth-service", call_kwargs["tags"])
        self.assertIn("[HYPOTHESIS] Clock skew", call_kwargs["content"])
        self.assertIn("None confirmed", call_kwargs["content"])
        manager.close()

    @patch("hindsight_memory.Hindsight")
    def test_retain_incident_failure_response(self, mock_hindsight_cls):
        """Test Retain returns False when SDK returns success=False."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.success = False
        mock_response.bank_id = "opsoria-incidents"
        mock_client.retain.return_value = mock_response
        mock_hindsight_cls.return_value = mock_client

        manager = HindsightMemoryManager(config=self.config)
        incident = Incident(incident_id="INC-FAIL-1", service="svc", symptoms="err")

        result = manager.retain_incident(incident)
        self.assertFalse(result)
        manager.close()

    @patch("hindsight_memory.Hindsight")
    def test_retain_incident_unexpected_or_missing_success_attribute(self, mock_hindsight_cls):
        """Test Retain returns False (fail-closed) when response lacks a valid success attribute."""
        mock_client = MagicMock()
        # Mock object missing success attribute entirely
        mock_response = MagicMock(spec=["bank_id"])
        mock_response.bank_id = "opsoria-incidents"
        mock_client.retain.return_value = mock_response
        mock_hindsight_cls.return_value = mock_client

        manager = HindsightMemoryManager(config=self.config)
        incident = Incident(incident_id="INC-NO-SUCCESS-ATTR", service="svc", symptoms="err")

        result = manager.retain_incident(incident)
        self.assertFalse(result)
        manager.close()

    @patch("hindsight_memory.Hindsight")
    def test_retain_incident_mismatched_bank_id(self, mock_hindsight_cls):
        """Test Retain returns False when response bank_id does not match configured bank ID."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.success = True
        mock_response.bank_id = "different-unauthorized-bank"
        mock_client.retain.return_value = mock_response
        mock_hindsight_cls.return_value = mock_client

        manager = HindsightMemoryManager(config=self.config)
        incident = Incident(incident_id="INC-MISMATCH-BANK", service="svc", symptoms="err")

        result = manager.retain_incident(incident)
        self.assertFalse(result)
        manager.close()

    @patch("hindsight_memory.Hindsight")
    def test_retain_incident_cache_write_failure_still_reports_success(self, mock_hindsight_cls):
        """Test that local cache write failure does not report remote Retain failure."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.success = True
        mock_response.bank_id = "opsoria-incidents"
        mock_client.retain.return_value = mock_response
        mock_hindsight_cls.return_value = mock_client

        manager = HindsightMemoryManager(config=self.config)
        incident = Incident(incident_id="INC-CACHE-FAIL", service="svc", symptoms="err")

        # Mock os.replace to simulate an atomic write disk error
        with patch("os.replace", side_effect=PermissionError("Disk permission denied")):
            result = manager.retain_incident(incident)
            # Must still report True because Hindsight remote retain succeeded!
            self.assertTrue(result)
            self.assertIn("INC-CACHE-FAIL", manager._retained_hashes)

        manager.close()

    @patch("hindsight_memory.Hindsight")
    def test_retain_incident_duplicate_prevention_and_restart(self, mock_hindsight_cls):
        """Test duplicate prevention works in-memory and persists across manager restarts."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.success = True
        mock_response.bank_id = "opsoria-incidents"
        mock_client.retain.return_value = mock_response
        mock_hindsight_cls.return_value = mock_client

        manager = HindsightMemoryManager(config=self.config)
        incident = Incident(
            incident_id="INC-102",
            service="database-proxy",
            symptoms="Connection pool exhausted",
            environment="production",
        )

        # First retain: invokes API
        first_result = manager.retain_incident(incident)
        self.assertTrue(first_result)
        self.assertEqual(mock_client.retain.call_count, 1)

        # Second retain of identical incident: skips remote API call
        second_result = manager.retain_incident(incident)
        self.assertTrue(second_result)
        self.assertEqual(mock_client.retain.call_count, 1)

        manager.close()

        # Simulate application restart with a fresh manager pointing to the same cache file
        manager_restarted = HindsightMemoryManager(config=self.config)
        restarted_result = manager_restarted.retain_incident(incident)
        self.assertTrue(restarted_result)
        # Should still be 1 (no new remote API call made because cached checksum matched!)
        self.assertEqual(mock_client.retain.call_count, 1)

        # Updating incident (e.g. adding confirmed resolution) triggers a new retain
        incident.confirmed_resolution = "Increased max connection limit in pool config."
        incident.status = "resolved"
        third_result = manager_restarted.retain_incident(incident)
        self.assertTrue(third_result)
        self.assertEqual(mock_client.retain.call_count, 2)
        manager_restarted.close()

    @patch("hindsight_memory.Hindsight")
    def test_retain_incident_api_failure_does_not_crash(self, mock_hindsight_cls):
        """Test API failure / timeout during Retain is caught and returns False."""
        mock_client = MagicMock()
        mock_client.retain.side_effect = TimeoutError("Request timed out to https://api.hindsight.vectorize.io")
        mock_hindsight_cls.return_value = mock_client

        manager = HindsightMemoryManager(config=self.config)
        incident = Incident(
            incident_id="INC-103",
            service="search-service",
            symptoms="Queries returning HTTP 500",
        )

        result = manager.retain_incident(incident)
        self.assertFalse(result)
        manager.close()

    @patch("hindsight_memory.Hindsight")
    def test_recall_incidents_success(self, mock_hindsight_cls):
        """Test Recall returns structured historical context."""
        mock_client = MagicMock()
        mock_result_item = MagicMock()
        mock_result_item.document_id = "INC-099"
        mock_result_item.text = "Incident INC-099: Search index corrupt after rolling restart."
        mock_result_item.type = "observation"
        mock_result_item.scores = {"relevance": 0.94}
        mock_result_item.tags = ["search-service", "production"]
        mock_result_item.metadata = {"incident_id": "INC-099"}

        mock_response = MagicMock()
        mock_response.results = [mock_result_item]
        mock_client.recall.return_value = mock_response
        mock_hindsight_cls.return_value = mock_client

        manager = HindsightMemoryManager(config=self.config)
        results = manager.recall_incidents(
            query="Find previous search service index issues",
            tags=["search-service"],
        )

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], HistoricalIncidentContext)
        self.assertEqual(results[0].document_id, "INC-099")
        self.assertIn("Search index corrupt", results[0].text)
        self.assertEqual(results[0].scores["relevance"], 0.94)
        manager.close()

    @patch("hindsight_memory.Hindsight")
    def test_recall_incidents_normalizes_realistic_sdk_models_and_enums(self, mock_hindsight_cls):
        """Test Recall normalizes realistic Hindsight SDK RecallResult, RecallScores, and Enums."""
        from enum import Enum
        from hindsight_client_api.models.recall_result import RecallResult
        from hindsight_client_api.models.recall_scores import RecallScores

        class MockTypeEnum(Enum):
            OBSERVATION = "observation"

        # Realistic SDK object matching server behavior
        sdk_result = RecallResult(
            id="unit-mem-999",
            document_id="OPS-TEST-001",
            text="Incident OPS-TEST-001: Payment timeout under high concurrency.",
            type=MockTypeEnum.OBSERVATION.value,
            scores=RecallScores(final=0.95, reranker=0.91, semantic=None, keyword=None),
            tags=["synthetic payment-service", "production"],
            metadata={"incident_id": "OPS-TEST-001"},
        )

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.results = [sdk_result]
        mock_client.recall.return_value = mock_response
        mock_hindsight_cls.return_value = mock_client

        manager = HindsightMemoryManager(config=self.config)
        results = manager.recall_incidents(query="payment timeout", tags=["synthetic payment-service"])

        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res.document_id, "OPS-TEST-001")
        self.assertEqual(res.memory_type, "observation")
        # Ensure scores is a dict with float values and None values stripped
        self.assertIsInstance(res.scores, dict)
        self.assertEqual(res.scores["final"], 0.95)
        self.assertEqual(res.scores["reranker"], 0.91)
        self.assertNotIn("semantic", res.scores)
        self.assertNotIn("keyword", res.scores)
        manager.close()

    @patch("hindsight_memory.Hindsight")
    def test_recall_incidents_skips_malformed_item_with_warning(self, mock_hindsight_cls):
        """Test Recall gracefully skips a malformed item while preserving valid items."""
        mock_client = MagicMock()
        valid_item = MagicMock()
        valid_item.document_id = "VALID-01"
        valid_item.text = "Valid incident text."
        valid_item.type = "observation"
        valid_item.scores = None
        valid_item.tags = None
        valid_item.metadata = None

        # Malformed item lacking both document_id and text
        malformed_item = MagicMock()
        malformed_item.document_id = None
        malformed_item.id = None
        malformed_item.text = None

        mock_response = MagicMock()
        mock_response.results = [malformed_item, valid_item]
        mock_client.recall.return_value = mock_response
        mock_hindsight_cls.return_value = mock_client

        manager = HindsightMemoryManager(config=self.config)
        with self.assertLogs("opsoria.hindsight", level="WARNING") as cm:
            results = manager.recall_incidents(query="test query")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].document_id, "VALID-01")
        self.assertTrue(any("malformed" in log for log in cm.output))
        manager.close()

    @patch("hindsight_memory.Hindsight")
    def test_recall_incidents_empty_results(self, mock_hindsight_cls):
        """Test Recall gracefully handles empty search results."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.results = []
        mock_client.recall.return_value = mock_response
        mock_hindsight_cls.return_value = mock_client

        manager = HindsightMemoryManager(config=self.config)
        results = manager.recall_incidents(query="Novel query with no matches")

        self.assertEqual(results, [])
        manager.close()

    @patch("hindsight_memory.Hindsight")
    def test_recall_incidents_api_failure_and_timeout(self, mock_hindsight_cls):
        """Test Recall handles exceptions and timeouts gracefully without crashing."""
        mock_client = MagicMock()
        mock_client.recall.side_effect = TimeoutError("Connection to Hindsight timed out.")
        mock_hindsight_cls.return_value = mock_client

        manager = HindsightMemoryManager(config=self.config)
        results = manager.recall_incidents(query="Query during outage")

        self.assertEqual(results, [])
        manager.close()

    @patch("hindsight_memory.Hindsight")
    def test_client_lifecycle_close_does_not_hang(self, mock_hindsight_cls):
        """Test close() handles hanging client gracefully with timeout."""
        mock_client = MagicMock()
        # Simulate a close() that blocks
        import time
        mock_client.close.side_effect = lambda: time.sleep(5)
        mock_hindsight_cls.return_value = mock_client

        manager = HindsightMemoryManager(config=self.config)
        # Should finish quickly because of the short timeout threshold
        manager.close(timeout=0.1)
        self.assertFalse(manager.is_available)


class TestIncidentProcessorIntegration(unittest.TestCase):
    """Tests for IncidentProcessor integrating with memory and analysis."""

    def test_process_incident_with_memory_recall_and_retention(self):
        """Test that incoming incidents are recalled and retained with unverified hypotheses."""
        mock_memory = MagicMock()
        mock_memory.is_available = True
        mock_memory.recall_incidents.return_value = [
            HistoricalIncidentContext(
                document_id="INC-PREV-01",
                text="Prior payment-service HTTP 503 caused by connection pool starvation.",
                scores={"relevance": 0.88},
            )
        ]

        processor = IncidentProcessor(memory_manager=mock_memory)
        incident = Incident(
            incident_id="INC-202",
            service="payment-service",
            symptoms="HTTP 503 surge post-deploy",
            possible_causes=["Incompatible database connection settings"],
        )

        analysis = processor.process_incident(incident)

        self.assertEqual(analysis.incident_id, "INC-202")
        self.assertEqual(analysis.historical_matches_count, 1)
        self.assertIn("HISTORICAL MEMORY CONTEXT", analysis.investigation_summary)
        self.assertIn("INC-PREV-01", analysis.investigation_summary)
        self.assertIn("Hypothesis (Unverified)", analysis.investigation_summary)
        self.assertIsNone(analysis.confirmed_resolution)

        # Retention policy: unresolved incidents are not retained merely upon submission
        mock_memory.retain_incident.assert_not_called()

    def test_resolve_incident_retains_confirmed_resolution(self):
        """Test that confirming resolution retains the updated incident to Hindsight and reports persisted."""
        mock_memory = MagicMock()
        mock_memory.is_available = True
        mock_memory.recall_incidents.return_value = []
        mock_memory.retain_incident.return_value = True

        processor = IncidentProcessor(memory_manager=mock_memory)
        incident = Incident(
            incident_id="INC-203",
            service="notification-worker",
            symptoms="Message backlog growing",
        )

        analysis = processor.resolve_incident(
            incident=incident,
            confirmed_resolution="Restarted stuck consumer pod and increased consumer concurrency.",
        )

        self.assertEqual(analysis.status, "resolved")
        self.assertEqual(
            analysis.confirmed_resolution,
            "Restarted stuck consumer pod and increased consumer concurrency.",
        )
        mock_memory.retain_incident.assert_called_once_with(incident)
        self.assertIn(
            "Resolution confirmed and persisted in Opsoria memory bank.",
            analysis.recommended_steps,
        )
        self.assertNotIn(
            "Resolution confirmed locally, but NOT persisted to the memory bank (Hindsight unavailable or retain failed).",
            analysis.recommended_steps,
        )

    def test_resolve_incident_retain_failed_handling(self):
        """Test resolve incident when retain returns False (not persisted, warning logged)."""
        mock_memory = MagicMock()
        mock_memory.is_available = True
        mock_memory.recall_incidents.return_value = []
        mock_memory.retain_incident.return_value = False

        processor = IncidentProcessor(memory_manager=mock_memory)
        incident = Incident(
            incident_id="INC-203-FAIL",
            service="notification-worker",
            symptoms="Message backlog growing",
        )

        with self.assertLogs("opsoria.processor", level="WARNING") as cm:
            analysis = processor.resolve_incident(
                incident=incident,
                confirmed_resolution="Restarted stuck consumer pod.",
            )

        self.assertEqual(analysis.status, "resolved")
        mock_memory.retain_incident.assert_called_once_with(incident)
        self.assertIn(
            "Resolution confirmed locally, but NOT persisted to the memory bank (Hindsight unavailable or retain failed).",
            analysis.recommended_steps,
        )
        self.assertNotIn(
            "Resolution confirmed and persisted in Opsoria memory bank.",
            analysis.recommended_steps,
        )
        self.assertTrue(any("retain failed" in log for log in cm.output))

    def test_resolve_incident_when_memory_unavailable(self):
        """Test resolve incident when memory is unavailable (is_available=False)."""
        mock_memory = MagicMock()
        mock_memory.is_available = False

        processor = IncidentProcessor(memory_manager=mock_memory)
        incident = Incident(
            incident_id="INC-203-UNAVAIL",
            service="notification-worker",
            symptoms="Message backlog growing",
        )

        with self.assertLogs("opsoria.processor", level="WARNING") as cm:
            analysis = processor.resolve_incident(
                incident=incident,
                confirmed_resolution="Restarted stuck consumer pod.",
            )

        self.assertEqual(analysis.status, "resolved")
        mock_memory.retain_incident.assert_not_called()
        self.assertIn(
            "Resolution confirmed locally, but NOT persisted to the memory bank (Hindsight unavailable or retain failed).",
            analysis.recommended_steps,
        )
        self.assertNotIn(
            "Resolution confirmed and persisted in Opsoria memory bank.",
            analysis.recommended_steps,
        )
        self.assertTrue(any("unavailable" in log for log in cm.output))

    def test_resolve_incident_when_memory_manager_is_none(self):
        """Test resolve incident when memory_manager is None."""
        processor = IncidentProcessor(memory_manager=None)
        incident = Incident(
            incident_id="INC-203-NONE",
            service="notification-worker",
            symptoms="Message backlog growing",
        )

        with self.assertLogs("opsoria.processor", level="WARNING") as cm:
            analysis = processor.resolve_incident(
                incident=incident,
                confirmed_resolution="Restarted stuck consumer pod.",
            )

        self.assertEqual(analysis.status, "resolved")
        self.assertIn(
            "Resolution confirmed locally, but NOT persisted to the memory bank (Hindsight unavailable or retain failed).",
            analysis.recommended_steps,
        )
        self.assertNotIn(
            "Resolution confirmed and persisted in Opsoria memory bank.",
            analysis.recommended_steps,
        )
        self.assertTrue(any("unavailable" in log for log in cm.output))

    def test_process_incident_when_memory_offline(self):
        """Test that processor executes safely even if memory manager is None or offline."""
        processor = IncidentProcessor(memory_manager=None)
        incident = Incident(
            incident_id="INC-204",
            service="billing-api",
            symptoms="Slow database queries",
            possible_causes=["Missing composite index on invoices table"],
        )

        analysis = processor.process_incident(incident)

        self.assertEqual(analysis.incident_id, "INC-204")
        self.assertEqual(analysis.historical_matches_count, 0)
        self.assertIn("No related historical incidents found", analysis.investigation_summary)

    def test_records_synthetic_tags_vs_non_synthetic(self):
        """Test labeling of synthetic records vs non-synthetic and corresponding warnings."""
        synthetic_record = HistoricalIncidentContext(
            document_id="d1",
            text="Synthetic test payment record.",
            tags=["synthetic payment-service", "staging"],
        )
        non_synthetic_record = HistoricalIncidentContext(
            document_id="d2",
            text="Real production incident record.",
            tags=["payment-service", "production"],
        )

        processor = IncidentProcessor(memory_manager=None)
        incident = Incident(
            incident_id="INC-SYNTH-1",
            service="payment-service",
            symptoms="Timeout",
        )

        analysis = processor._synthesize_analysis(
            incident, [synthetic_record, non_synthetic_record]
        )

        self.assertTrue(synthetic_record.is_synthetic)
        self.assertFalse(non_synthetic_record.is_synthetic)
        self.assertIn(
            "[SYNTHETIC TEST DATA - not a production fix]",
            analysis.investigation_summary,
        )
        self.assertIn(
            "Matched history includes synthetic test data and must NOT be treated as verified production guidance.",
            analysis.recommended_steps,
        )

    def test_grouping_records_by_prior_incident_and_unchanged_count(self):
        """Test grouping 5 records to 1 prior incident while keeping match count = 5."""
        records = [
            HistoricalIncidentContext(
                document_id="c0a80101-0000-0000-0000-00000000000" + str(i),
                text=f"Incident OPS-TEST-001 fact #{i}: Connection pool timeout.",
                metadata={"incident_id": "OPS-TEST-001"},
            )
            for i in range(1, 6)
        ]

        processor = IncidentProcessor(memory_manager=None)
        incident = Incident(
            incident_id="INC-GROUP-1",
            service="payment-service",
            symptoms="Timeout",
        )

        analysis = processor._synthesize_analysis(incident, records)

        self.assertEqual(analysis.historical_matches_count, 5)
        self.assertIn(
            "Found 5 related memory records from 1 prior incident.",
            analysis.investigation_summary,
        )
        # Should reference OPS-TEST-001 and not UUIDs
        self.assertIn(
            "Review historical patterns from prior incidents (OPS-TEST-001).",
            analysis.recommended_steps,
        )

    def test_summary_truncation_to_200_chars_and_top_3_records(self):
        """Test displaying at most top 3 records and truncating long text to ~200 chars."""
        long_text = "A" * 250
        records = [
            HistoricalIncidentContext(
                document_id=f"INC-TOP-{i}",
                text=f"Match item {i}: {long_text}",
            )
            for i in range(1, 6)
        ]

        processor = IncidentProcessor(memory_manager=None)
        incident = Incident(
            incident_id="INC-TRUNC-1",
            service="order-service",
            symptoms="Deadlock",
        )

        analysis = processor._synthesize_analysis(incident, records)

        # Match #1, #2, #3 are present
        self.assertIn("Match #1 [INC-TOP-1]", analysis.investigation_summary)
        self.assertIn("Match #2 [INC-TOP-2]", analysis.investigation_summary)
        self.assertIn("Match #3 [INC-TOP-3]", analysis.investigation_summary)
        # Match #4 and #5 should NOT be present in summary
        self.assertNotIn("Match #4", analysis.investigation_summary)
        self.assertNotIn("Match #5", analysis.investigation_summary)
        # Long text truncated with ...
        self.assertIn("...", analysis.investigation_summary)

    def test_uuid_document_ids_excluded_from_steps(self):
        """Test UUID document IDs are excluded from recommended_steps."""
        import uuid
        uuid_str = str(uuid.uuid4())
        record = HistoricalIncidentContext(
            document_id=uuid_str,
            text="Extracted fact with no prior incident ID.",
        )

        processor = IncidentProcessor(memory_manager=None)
        incident = Incident(
            incident_id="INC-UUID-1",
            service="auth-service",
            symptoms="Crash",
        )

        analysis = processor._synthesize_analysis(incident, [record])

        # UUID must never appear in recommended_steps
        for step in analysis.recommended_steps:
            self.assertNotIn(uuid_str, step)
        self.assertIn(
            "Review historical patterns from prior incidents.",
            analysis.recommended_steps,
        )

    def test_recalled_resolution_wording(self):
        """Test that recalled resolutions are worded carefully and not marked verified for current incident."""
        record = HistoricalIncidentContext(
            document_id="INC-RESOLVED-PRIOR",
            text="Incident OPS-TEST-001: Connection exhausted. Confirmed Resolution: Scaled connection pool to 50.",
            metadata={"incident_id": "OPS-TEST-001"},
        )

        processor = IncidentProcessor(memory_manager=None)
        incident = Incident(
            incident_id="INC-RES-CURRENT",
            service="db-service",
            symptoms="Connection pool exhausted",
        )

        analysis = processor._synthesize_analysis(incident, [record])

        expected_resolution_step = (
            "Prior incident OPS-TEST-001 reported resolution: Scaled connection pool to 50. "
            "Validate against current telemetry before applying."
        )
        self.assertIn(expected_resolution_step, analysis.recommended_steps)


class TestMainWorkflowIntegration(unittest.TestCase):
    """Tests for main.py incident ingestion workflow."""

    @patch("main.get_processor")
    def test_ingest_incident_dict(self, mock_get_processor):
        """Test main.ingest_incident accepts a dict and routes to processor."""
        mock_processor = MagicMock()
        mock_analysis = MagicMock()
        mock_processor.process_incident.return_value = mock_analysis
        mock_get_processor.return_value = mock_processor

        payload = {
            "incident_id": "INC-DICT-1",
            "service": "checkout-service",
            "symptoms": "Checkout timeouts",
            "possible_causes": ["Redis lock timeout"],
        }
        res = main.ingest_incident(payload)

        self.assertEqual(res, mock_analysis)
        mock_processor.process_incident.assert_called_once()
        called_incident = mock_processor.process_incident.call_args[0][0]
        self.assertEqual(called_incident.incident_id, "INC-DICT-1")
        self.assertEqual(called_incident.service, "checkout-service")

    @patch("main.get_processor")
    def test_resolve_incident_workflow(self, mock_get_processor):
        """Test main.resolve_incident routes to processor."""
        mock_processor = MagicMock()
        mock_analysis = MagicMock()
        mock_processor.resolve_incident.return_value = mock_analysis
        mock_get_processor.return_value = mock_processor

        incident = Incident(incident_id="INC-RES-1", service="auth", symptoms="Crash")
        res = main.resolve_incident(incident, "Applied patch v1.2")

        self.assertEqual(res, mock_analysis)
        mock_processor.resolve_incident.assert_called_once_with(incident, "Applied patch v1.2")


if __name__ == "__main__":
    unittest.main()
