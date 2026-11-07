"""FastAPI HTTP-level test suite for Opsoria REST API.

Uses HTTPX AsyncClient and ASGITransport with explicit FastAPI lifespan management:
- Health endpoint (read-only, no Retain/Recall)
- Valid incident ingestion
- Missing / empty required fields validation (HTTP 422)
- Resolution of known incident
- 404 for unknown incident resolution
- 422 for empty resolution
- Internal error handling (HTTP 500)
- Graceful degradation when Hindsight is unavailable
- Service lifespan initialization and shutdown cleanup
- Configurable API key authentication
"""

import asyncio
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import httpx

import db
from api import create_app
from hindsight_memory import HindsightMemoryConfig, HindsightMemoryManager
from incident_processor import IncidentProcessor
from models import HistoricalIncidentContext, Incident, IncidentAnalysis


class TestOpsoriaAPIAsync(unittest.IsolatedAsyncioTestCase):
    """HTTP-level async test suite for Opsoria REST API using HTTPX AsyncClient."""

    async def asyncSetUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.db_path = self.temp_db.name

        self.app = create_app()

        # Mock memory manager & processor for state isolation
        self.mock_memory = MagicMock()
        self.mock_memory.is_available = True
        self.mock_memory.config.bank_id = "opsoria-incidents"
        self.mock_processor = MagicMock()

        self.app.state.memory_manager = self.mock_memory
        self.app.state.processor = self.mock_processor
        self.app.state.db_path = self.db_path
        db.init_db(self.db_path)
        self.app.state.incident_registry = {}

        self.transport = httpx.ASGITransport(app=self.app)

    async def asyncTearDown(self):
        if hasattr(self, "db_path") and os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    async def test_health_endpoint(self):
        """Test GET /health returns status and memory status without calling Retain/Recall."""
        async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
            response = await client.get("/health")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "healthy")
            self.assertTrue(data["hindsight_available"])
            self.assertEqual(data["hindsight_bank_id"], "opsoria-incidents")

            # Must not call retain or recall
            self.mock_memory.retain_incident.assert_not_called()
            self.mock_memory.recall_incidents.assert_not_called()

    async def test_health_endpoint_when_hindsight_unavailable(self):
        """Test GET /health accurately reflects when Hindsight is unavailable."""
        self.mock_memory.is_available = False
        async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
            response = await client.get("/health")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "healthy")
            self.assertFalse(data["hindsight_available"])

    async def test_valid_incident_ingestion(self):
        """Test POST /incidents with valid payload successfully processes incident."""
        mock_analysis = IncidentAnalysis(
            incident_id="INC-API-001",
            service="order-service",
            environment="production",
            symptoms="Deadlock on order creation table",
            status="investigating",
            historical_matches_count=1,
            historical_context=[
                HistoricalIncidentContext(
                    document_id="INC-PAST-10",
                    text="Prior database lock issue",
                    scores={"relevance": 0.91},
                )
            ],
            investigation_summary="Investigation for INC-API-001: Deadlock identified.",
            recommended_steps=["Check active transactions in database."],
            confirmed_resolution=None,
        )
        self.mock_processor.process_incident.return_value = mock_analysis

        payload = {
            "incident_id": "INC-API-001",
            "service": "order-service",
            "symptoms": "Deadlock on order creation table",
            "environment": "production",
            "possible_causes": ["High concurrency without row locks"],
        }

        async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
            response = await client.post("/incidents", json=payload)
            self.assertEqual(response.status_code, 200)
            data = response.json()

            self.assertEqual(data["incident_id"], "INC-API-001")
            self.assertEqual(data["service"], "order-service")
            self.assertEqual(data["historical_match_count"], 1)
            self.assertEqual(len(data["historical_context"]), 1)
            self.assertEqual(data["historical_context"][0]["document_id"], "INC-PAST-10")
            self.assertIsNone(data["confirmed_resolution"])

            # Stored in process-local registry
            self.assertIn("INC-API-001", self.app.state.incident_registry)
            self.mock_processor.process_incident.assert_called_once()

    async def test_missing_and_empty_required_fields_422(self):
        """Test POST /incidents rejects missing, empty, or whitespace-only fields with HTTP 422."""
        async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
            # Missing service
            res1 = await client.post(
                "/incidents",
                json={"incident_id": "INC-BAD-1", "symptoms": "High CPU"},
            )
            self.assertEqual(res1.status_code, 422)

            # Empty string incident_id
            res2 = await client.post(
                "/incidents",
                json={"incident_id": "   ", "service": "api", "symptoms": "Error"},
            )
            self.assertEqual(res2.status_code, 422)

            # Empty symptoms
            res3 = await client.post(
                "/incidents",
                json={"incident_id": "INC-BAD-3", "service": "api", "symptoms": ""},
            )
            self.assertEqual(res3.status_code, 422)

    async def test_resolve_known_incident(self):
        """Test POST /incidents/{incident_id}/resolve successfully resolves an existing incident."""
        incident = Incident(
            incident_id="INC-RESOLVE-1",
            service="auth-service",
            symptoms="JWT signature errors",
        )
        stored = db.save_or_upsert_incident(
            incident_id="INC-RESOLVE-1",
            service="auth-service",
            environment="production",
            status="investigating",
            symptoms="JWT signature errors",
            possible_causes=[],
            metadata={},
            confirmed_resolution=None,
            memory_status="not_applicable",
            last_analysis={},
            db_path=self.db_path,
        )
        incident.created_at = stored["created_at"]

        resolved_analysis = IncidentAnalysis(
            incident_id="INC-RESOLVE-1",
            service="auth-service",
            environment="production",
            symptoms="JWT signature errors",
            status="resolved",
            historical_matches_count=0,
            historical_context=[],
            investigation_summary="Resolved JWT issue.",
            recommended_steps=["Monitor authentication success rate."],
            confirmed_resolution="Rotated expired signing key in vault.",
        )
        self.mock_processor.resolve_incident.return_value = resolved_analysis

        payload = {"confirmed_resolution": "Rotated expired signing key in vault."}
        async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
            response = await client.post("/incidents/INC-RESOLVE-1/resolve", json=payload)
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "resolved")
            self.assertEqual(data["confirmed_resolution"], "Rotated expired signing key in vault.")
            self.mock_processor.resolve_incident.assert_called_once_with(
                incident, "Rotated expired signing key in vault."
            )

    async def test_resolve_unknown_incident_returns_404(self):
        """Test POST /incidents/{id}/resolve returns HTTP 404 for incident not in registry."""
        payload = {"confirmed_resolution": "Fixed bug."}
        async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
            response = await client.post("/incidents/INC-NONEXISTENT/resolve", json=payload)
            self.assertEqual(response.status_code, 404)
            self.assertIn("not found in registry", response.json()["detail"])

    async def test_resolve_empty_resolution_returns_422(self):
        """Test POST /incidents/{id}/resolve rejects empty resolution text."""
        db.save_or_upsert_incident(
            incident_id="INC-EMPTY-RES",
            service="svc",
            environment="production",
            status="investigating",
            symptoms="err",
            possible_causes=[],
            metadata={},
            confirmed_resolution=None,
            memory_status="not_applicable",
            last_analysis={},
            db_path=self.db_path,
        )

        async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
            response = await client.post(
                "/incidents/INC-EMPTY-RES/resolve",
                json={"confirmed_resolution": "   "},
            )
            self.assertEqual(response.status_code, 422)

    async def test_processor_failure_returns_500(self):
        """Test processor exception returns safe HTTP 500 without crashing."""
        self.mock_processor.process_incident.side_effect = RuntimeError("Database offline")

        payload = {
            "incident_id": "INC-ERR-1",
            "service": "billing",
            "symptoms": "Charges failing",
        }
        async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
            response = await client.post("/incidents", json=payload)
            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.json()["detail"], "Internal error processing incident.")

    async def test_authentication_enforcement(self):
        """Test configurable API key check when OPSORIA_API_KEY is configured."""
        with patch.dict(os.environ, {"OPSORIA_API_KEY": "secret-opsoria-token-777"}):
            async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
                # Health is unauthenticated
                health_res = await client.get("/health")
                self.assertEqual(health_res.status_code, 200)

                payload = {
                    "incident_id": "INC-AUTH-1",
                    "service": "api",
                    "symptoms": "Test symptoms",
                }

                # Unauthenticated request fails with 401
                unauth_res = await client.post("/incidents", json=payload)
                self.assertEqual(unauth_res.status_code, 401)

                # Invalid key fails with 401
                wrong_res = await client.post(
                    "/incidents",
                    json=payload,
                    headers={"Authorization": "Bearer wrong-token"},
                )
                self.assertEqual(wrong_res.status_code, 401)

                # Valid Bearer token succeeds
                valid_analysis = IncidentAnalysis(
                    incident_id="INC-AUTH-1",
                    service="api",
                    environment="production",
                    symptoms="Test symptoms",
                    status="investigating",
                    historical_matches_count=0,
                    historical_context=[],
                    investigation_summary="Summary",
                    recommended_steps=[],
                )
                self.mock_processor.process_incident.return_value = valid_analysis
                valid_res = await client.post(
                    "/incidents",
                    json=payload,
                    headers={"Authorization": "Bearer secret-opsoria-token-777"},
                )
                self.assertEqual(valid_res.status_code, 200)

                # Valid X-API-Key header succeeds
                valid_x_res = await client.post(
                    "/incidents",
                    json=payload,
                    headers={"X-API-Key": "secret-opsoria-token-777"},
                )
                self.assertEqual(valid_x_res.status_code, 200)

    async def test_process_incident_runs_without_running_event_loop_in_worker_thread(self):
        """Regression test: processor.process_incident runs off the event loop in a worker thread.

        If called directly on FastAPI's main event loop, Hindsight SDK's synchronous
        recall/retain calls raise RuntimeError: 'This event loop is already running'.
        """
        thread_has_running_loop = None

        def mock_process(incident):
            nonlocal thread_has_running_loop
            try:
                asyncio.get_running_loop()
                thread_has_running_loop = True
            except RuntimeError:
                thread_has_running_loop = False

            if thread_has_running_loop:
                raise RuntimeError("This event loop is already running")

            return IncidentAnalysis(
                incident_id=incident.incident_id,
                service=incident.service,
                environment=incident.environment,
                symptoms=incident.symptoms,
                status=incident.status,
                historical_matches_count=0,
                historical_context=[],
                investigation_summary="OK",
                recommended_steps=[],
            )

        self.mock_processor.process_incident.side_effect = mock_process

        payload = {
            "incident_id": "INC-THREAD-01",
            "service": "checkout",
            "symptoms": "Latency spike",
        }

        async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
            res = await client.post("/incidents", json=payload)
            self.assertEqual(res.status_code, 200)
            self.assertFalse(thread_has_running_loop)

    async def test_resolve_incident_runs_without_running_event_loop_in_worker_thread(self):
        """Regression test: processor.resolve_incident runs off the event loop in a worker thread."""
        incident = Incident(
            incident_id="INC-THREAD-02",
            service="payment",
            symptoms="Card errors",
        )
        db.save_or_upsert_incident(
            incident_id="INC-THREAD-02",
            service="payment",
            environment="production",
            status="investigating",
            symptoms="Card errors",
            possible_causes=[],
            metadata={},
            confirmed_resolution=None,
            memory_status="not_applicable",
            last_analysis={},
            db_path=self.db_path,
        )

        thread_has_running_loop = None

        def mock_resolve(inc, resolution):
            nonlocal thread_has_running_loop
            try:
                asyncio.get_running_loop()
                thread_has_running_loop = True
            except RuntimeError:
                thread_has_running_loop = False

            if thread_has_running_loop:
                raise RuntimeError("This event loop is already running")

            return IncidentAnalysis(
                incident_id=inc.incident_id,
                service=inc.service,
                environment=inc.environment,
                symptoms=inc.symptoms,
                status="resolved",
                historical_matches_count=0,
                historical_context=[],
                investigation_summary="Resolved",
                recommended_steps=["Monitor"],
                confirmed_resolution=resolution,
            )

        self.mock_processor.resolve_incident.side_effect = mock_resolve

        payload = {"confirmed_resolution": "Fixed timeout config."}

        async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
            res = await client.post("/incidents/INC-THREAD-02/resolve", json=payload)
            self.assertEqual(res.status_code, 200)
            self.assertFalse(thread_has_running_loop)

    async def test_post_incidents_with_realistic_recalled_sdk_item(self):
        """Regression test: POST /incidents returns 200 with realistic SDK RecallResult/RecallScores."""
        from enum import Enum
        from hindsight_client_api.models.recall_result import RecallResult
        from hindsight_client_api.models.recall_scores import RecallScores

        class MockTypeEnum(Enum):
            OBSERVATION = "observation"

        sdk_item = RecallResult(
            id="unit-mem-101",
            document_id="OPS-TEST-001",
            text="Incident OPS-TEST-001: Synthetic payment timeout.",
            type=MockTypeEnum.OBSERVATION.value,
            scores=RecallScores(final=0.94, reranker=0.88, semantic=None, keyword=None),
            tags=["synthetic payment-service", "production"],
            metadata={"incident_id": "OPS-TEST-001"},
        )

        with patch("hindsight_memory.Hindsight") as mock_hindsight_cls:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.results = [sdk_item]
            mock_client.recall.return_value = mock_response
            mock_hindsight_cls.return_value = mock_client

            config = HindsightMemoryConfig(api_key="mock-api-key")
            real_memory = HindsightMemoryManager(config=config)
            real_processor = IncidentProcessor(memory_manager=real_memory)

            self.app.state.memory_manager = real_memory
            self.app.state.processor = real_processor

            payload = {
                "incident_id": "OPS-TEST-002",
                "service": "synthetic payment-service",
                "symptoms": "Payment gateway timeout in production",
            }

            async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
                res = await client.post("/incidents", json=payload)
                self.assertEqual(res.status_code, 200)
                data = res.json()
                self.assertEqual(data["incident_id"], "OPS-TEST-002")
                self.assertEqual(data["historical_match_count"], 1)
                self.assertEqual(data["historical_context"][0]["document_id"], "OPS-TEST-001")
                self.assertEqual(data["historical_context"][0]["scores"]["final"], 0.94)

            real_memory.close()

    async def test_post_incidents_with_malformed_recalled_item_skipped(self):
        """Regression test: POST /incidents succeeds and skips malformed recalled items with warning."""
        from hindsight_client_api.models.recall_result import RecallResult
        from hindsight_client_api.models.recall_scores import RecallScores

        valid_item = RecallResult(
            id="unit-mem-102",
            document_id="OPS-TEST-001",
            text="Valid historical incident text.",
            type="observation",
            scores=RecallScores(final=0.89, reranker=None, semantic=None, keyword=None),
            tags=["service"],
            metadata={},
        )

        # Malformed item lacking text and document_id
        malformed_item = MagicMock()
        malformed_item.document_id = None
        malformed_item.id = None
        malformed_item.text = None

        with patch("hindsight_memory.Hindsight") as mock_hindsight_cls:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.results = [malformed_item, valid_item]
            mock_client.recall.return_value = mock_response
            mock_hindsight_cls.return_value = mock_client

            config = HindsightMemoryConfig(api_key="mock-api-key")
            real_memory = HindsightMemoryManager(config=config)
            real_processor = IncidentProcessor(memory_manager=real_memory)

            self.app.state.memory_manager = real_memory
            self.app.state.processor = real_processor

            payload = {
                "incident_id": "OPS-TEST-003",
                "service": "synthetic payment-service",
                "symptoms": "Payment gateway timeout in production",
            }

            async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
                res = await client.post("/incidents", json=payload)
                self.assertEqual(res.status_code, 200)
                data = res.json()
                self.assertEqual(data["incident_id"], "OPS-TEST-003")
                # Malformed item was skipped, only valid item is present
                self.assertEqual(data["historical_match_count"], 1)
                self.assertEqual(data["historical_context"][0]["document_id"], "OPS-TEST-001")

            real_memory.close()

    async def test_resolve_after_simulated_restart(self):
        """Test incident survives process restart: resolved on a fresh app instance via SQLite."""
        # 1. Ingest incident on current app
        mock_analysis = IncidentAnalysis(
            incident_id="INC-RESTART-01",
            service="catalog-service",
            environment="production",
            symptoms="Slow product search",
            status="investigating",
            historical_matches_count=0,
            historical_context=[],
            investigation_summary="Slow catalog queries.",
            recommended_steps=["Check cache"],
        )
        self.mock_processor.process_incident.return_value = mock_analysis

        payload = {
            "incident_id": "INC-RESTART-01",
            "service": "catalog-service",
            "symptoms": "Slow product search",
        }
        async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
            res1 = await client.post("/incidents", json=payload)
            self.assertEqual(res1.status_code, 200)

        # 2. Simulate process restart: fresh app instance using the same database file
        app_restarted = create_app()
        mock_processor_2 = MagicMock()
        mock_resolved_analysis = IncidentAnalysis(
            incident_id="INC-RESTART-01",
            service="catalog-service",
            environment="production",
            symptoms="Slow product search",
            status="resolved",
            historical_matches_count=0,
            historical_context=[],
            investigation_summary="Resolved catalog issue.",
            recommended_steps=[
                "Resolution confirmed and persisted in Opsoria memory bank."
            ],
            confirmed_resolution="Added Redis cache in front of DB.",
        )
        mock_processor_2.resolve_incident.return_value = mock_resolved_analysis

        app_restarted.state.processor = mock_processor_2
        app_restarted.state.memory_manager = self.mock_memory
        app_restarted.state.db_path = self.db_path

        transport_restarted = httpx.ASGITransport(app=app_restarted)
        async with httpx.AsyncClient(transport=transport_restarted, base_url="http://testserver") as client2:
            res2 = await client2.post(
                "/incidents/INC-RESTART-01/resolve",
                json={"confirmed_resolution": "Added Redis cache in front of DB."},
            )
            self.assertEqual(res2.status_code, 200)
            data2 = res2.json()
            self.assertEqual(data2["status"], "resolved")
            self.assertEqual(data2["confirmed_resolution"], "Added Redis cache in front of DB.")

        # Verify directly in SQLite
        row = db.get_incident_by_id("INC-RESTART-01", self.db_path)
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "resolved")
        self.assertEqual(row["confirmed_resolution"], "Added Redis cache in front of DB.")
        self.assertEqual(row["memory_status"], "persisted")

    async def test_memory_status_persisted_vs_not_persisted(self):
        """Test memory_status is 'persisted' when retain succeeds, 'not_persisted' when it fails."""
        # Setup 2 incidents in SQLite
        db.save_or_upsert_incident(
            incident_id="INC-MEM-PASS",
            service="s1",
            environment="prod",
            status="investigating",
            symptoms="err",
            possible_causes=[],
            metadata={},
            confirmed_resolution=None,
            memory_status="not_applicable",
            last_analysis={},
            db_path=self.db_path,
        )
        db.save_or_upsert_incident(
            incident_id="INC-MEM-FAIL",
            service="s2",
            environment="prod",
            status="investigating",
            symptoms="err",
            possible_causes=[],
            metadata={},
            confirmed_resolution=None,
            memory_status="not_applicable",
            last_analysis={},
            db_path=self.db_path,
        )

        # 1. Resolve where retain succeeds
        self.mock_processor.resolve_incident.return_value = IncidentAnalysis(
            incident_id="INC-MEM-PASS",
            service="s1",
            environment="prod",
            symptoms="err",
            status="resolved",
            historical_matches_count=0,
            historical_context=[],
            investigation_summary="Resolved",
            recommended_steps=["Resolution confirmed and persisted in Opsoria memory bank."],
            confirmed_resolution="Fix 1",
        )
        async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
            res_pass = await client.post(
                "/incidents/INC-MEM-PASS/resolve", json={"confirmed_resolution": "Fix 1"}
            )
            self.assertEqual(res_pass.status_code, 200)

        # 2. Resolve where retain fails
        self.mock_processor.resolve_incident.return_value = IncidentAnalysis(
            incident_id="INC-MEM-FAIL",
            service="s2",
            environment="prod",
            symptoms="err",
            status="resolved",
            historical_matches_count=0,
            historical_context=[],
            investigation_summary="Resolved",
            recommended_steps=[
                "Resolution confirmed locally, but NOT persisted to the memory bank (Hindsight unavailable or retain failed)."
            ],
            confirmed_resolution="Fix 2",
        )
        async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
            res_fail = await client.post(
                "/incidents/INC-MEM-FAIL/resolve", json={"confirmed_resolution": "Fix 2"}
            )
            self.assertEqual(res_fail.status_code, 200)

        # Verify SQLite values
        rec_pass = db.get_incident_by_id("INC-MEM-PASS", self.db_path)
        rec_fail = db.get_incident_by_id("INC-MEM-FAIL", self.db_path)
        self.assertEqual(rec_pass["memory_status"], "persisted")
        self.assertEqual(rec_fail["memory_status"], "not_persisted")

    async def test_get_incidents_list_endpoint(self):
        """Test GET /incidents lists incidents ordered newest first and supports ?status= filter."""
        db.save_or_upsert_incident(
            incident_id="INC-EP-1",
            service="s1",
            environment="prod",
            status="investigating",
            symptoms="err",
            possible_causes=[],
            metadata={},
            confirmed_resolution=None,
            memory_status="not_applicable",
            last_analysis={},
            db_path=self.db_path,
        )
        db.save_or_upsert_incident(
            incident_id="INC-EP-2",
            service="s2",
            environment="prod",
            status="resolved",
            symptoms="err",
            possible_causes=[],
            metadata={},
            confirmed_resolution="fixed",
            memory_status="persisted",
            last_analysis={},
            db_path=self.db_path,
        )

        async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
            # List all
            res_all = await client.get("/incidents")
            self.assertEqual(res_all.status_code, 200)
            items = res_all.json()
            self.assertEqual(len(items), 2)

            # Filter by status
            res_filtered = await client.get("/incidents?status=resolved")
            self.assertEqual(res_filtered.status_code, 200)
            filtered_items = res_filtered.json()
            self.assertEqual(len(filtered_items), 1)
            self.assertEqual(filtered_items[0]["incident_id"], "INC-EP-2")

    async def test_get_incident_detail_endpoint(self):
        """Test GET /incidents/{incident_id} returns full record with parsed last_analysis or 404."""
        db.save_or_upsert_incident(
            incident_id="INC-DETAIL-1",
            service="order-svc",
            environment="prod",
            status="investigating",
            symptoms="timeouts",
            possible_causes=["db lock"],
            metadata={"source": "pagerduty"},
            confirmed_resolution=None,
            memory_status="not_applicable",
            last_analysis={"summary": "Detailed summary", "historical_context": [{"document_id": "P-1", "is_synthetic": False}]},
            db_path=self.db_path,
        )

        async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
            # 200 for known
            res = await client.get("/incidents/INC-DETAIL-1")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["incident_id"], "INC-DETAIL-1")
            self.assertEqual(data["service"], "order-svc")
            self.assertEqual(data["last_analysis"]["summary"], "Detailed summary")
            self.assertEqual(data["last_analysis"]["historical_context"][0]["document_id"], "P-1")

            # 404 for unknown
            res_404 = await client.get("/incidents/INC-UNKNOWN")
            self.assertEqual(res_404.status_code, 404)

    async def test_get_stats_endpoint(self):
        """Test GET /stats returns counts by status, resolved, persisted, and recent 5."""
        for i in range(1, 4):
            db.save_or_upsert_incident(
                incident_id=f"INC-STAT-API-{i}",
                service="svc",
                environment="prod",
                status="resolved" if i == 1 else "investigating",
                symptoms="err",
                possible_causes=[],
                metadata={"type": "synthetic_test"} if i == 1 else {},
                confirmed_resolution="done" if i == 1 else None,
                memory_status="persisted" if i == 1 else "not_applicable",
                last_analysis={},
                db_path=self.db_path,
            )

        async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
            res = await client.get("/stats")
            self.assertEqual(res.status_code, 200)
            stats = res.json()
            self.assertEqual(stats["total"], 3)
            self.assertEqual(stats["resolved_count"], 1)
            self.assertEqual(stats["persisted_count"], 1)
            self.assertEqual(stats["synthetic_count"], 1)
            self.assertEqual(len(stats["recent_incidents"]), 3)

    async def test_upsert_never_downgrades_resolved_incident_via_api(self):
        """Test POST /incidents with existing resolved ID refreshes analysis but never reverts resolved status."""
        # 1. Save and resolve incident
        db.save_or_upsert_incident(
            incident_id="INC-NO-DOWNGRADE",
            service="billing",
            environment="production",
            status="resolved",
            symptoms="Card declined surge",
            possible_causes=[],
            metadata={},
            confirmed_resolution="Updated gateway credentials in vault.",
            memory_status="persisted",
            last_analysis={"version": 1},
            db_path=self.db_path,
        )

        # 2. Ingest again via POST /incidents with status="investigating"
        refreshed_analysis = IncidentAnalysis(
            incident_id="INC-NO-DOWNGRADE",
            service="billing",
            environment="production",
            symptoms="Card declined surge",
            status="investigating",
            historical_matches_count=0,
            historical_context=[],
            investigation_summary="Refreshed analysis",
            recommended_steps=[],
        )
        self.mock_processor.process_incident.return_value = refreshed_analysis

        payload = {
            "incident_id": "INC-NO-DOWNGRADE",
            "service": "billing",
            "symptoms": "Card declined surge",
            "status": "investigating",
        }
        async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
            res = await client.post("/incidents", json=payload)
            self.assertEqual(res.status_code, 200)

        # 3. Check SQLite record: status, confirmed_resolution, and memory_status are unchanged!
        stored = db.get_incident_by_id("INC-NO-DOWNGRADE", self.db_path)
        self.assertEqual(stored["status"], "resolved")
        self.assertEqual(stored["confirmed_resolution"], "Updated gateway credentials in vault.")
        self.assertEqual(stored["memory_status"], "persisted")

    async def test_cors_headers(self):
        """Test CORS headers allow http://localhost:5173."""
        async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
            res = await client.get("/health", headers={"Origin": "http://localhost:5173"})
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.headers.get("access-control-allow-origin"), "http://localhost:5173")

    @patch("groq_analyst.Groq")
    async def test_post_incidents_with_groq_ai_reasoning(self, mock_groq_cls):
        """Test POST /incidents enriches response with AI hypotheses and persists into SQLite."""
        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()
        mock_message.content = """
        {
          "hypotheses": [
            {
              "title": "Database Connection Pool Starvation",
              "reasoning": "Checkout timeouts typically stem from database exhaustion.",
              "confidence": "high",
              "suggested_checks": ["Check pg_stat_activity"]
            }
          ],
          "investigation_plan": ["Verify active connections"],
          "caveats": ["AI output is unverified hypothesis."]
        }
        """
        mock_choice.message = mock_message
        mock_completion = MagicMock(choices=[mock_choice])
        mock_client.chat.completions.create.return_value = mock_completion
        mock_groq_cls.return_value = mock_client

        mock_analysis = IncidentAnalysis(
            incident_id="INC-AI-API-01",
            service="checkout",
            environment="production",
            symptoms="Timeouts",
            status="investigating",
            historical_matches_count=0,
            historical_context=[],
            investigation_summary="Summary",
            recommended_steps=["Check logs"],
        )
        self.mock_processor.process_incident.return_value = mock_analysis

        payload = {
            "incident_id": "INC-AI-API-01",
            "service": "checkout",
            "symptoms": "Timeouts",
        }

        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_valid_mock_token"}):
            async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
                res = await client.post("/incidents", json=payload)
                self.assertEqual(res.status_code, 200)
                data = res.json()

                # Verify additive AI fields
                self.assertEqual(data["ai_status"], "success")
                self.assertEqual(
                    data["ai_label"],
                    "AI-generated hypotheses - UNVERIFIED. Not a confirmed root cause.",
                )
                self.assertEqual(len(data["ai_hypotheses"]), 1)
                self.assertEqual(data["ai_hypotheses"][0]["title"], "Database Connection Pool Starvation")
                self.assertEqual(data["ai_investigation_plan"], ["Verify active connections"])

                # Verify persistence into SQLite last_analysis
                stored = db.get_incident_by_id("INC-AI-API-01", self.db_path)
                self.assertIsNotNone(stored)
                self.assertEqual(stored["last_analysis"]["ai_status"], "success")
                self.assertEqual(
                    stored["last_analysis"]["ai_hypotheses"][0]["title"],
                    "Database Connection Pool Starvation",
                )

                # Verify Retain was not called by Groq reasoning
                self.mock_memory.retain_incident.assert_not_called()

    @patch("groq_analyst.Groq")
    async def test_post_incidents_groq_failure_still_returns_200(self, mock_groq_cls):
        """Test POST /incidents still returns HTTP 200 with ai_status='unavailable' when Groq times out."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = TimeoutError("Groq API timed out")
        mock_groq_cls.return_value = mock_client

        mock_analysis = IncidentAnalysis(
            incident_id="INC-AI-FAIL-01",
            service="order",
            environment="production",
            symptoms="Slow queries",
            status="investigating",
            historical_matches_count=0,
            historical_context=[],
            investigation_summary="Summary",
            recommended_steps=["Check logs"],
        )
        self.mock_processor.process_incident.return_value = mock_analysis

        payload = {
            "incident_id": "INC-AI-FAIL-01",
            "service": "order",
            "symptoms": "Slow queries",
        }

        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_mock_token"}):
            async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
                res = await client.post("/incidents", json=payload)
                self.assertEqual(res.status_code, 200)
                data = res.json()
                self.assertEqual(data["ai_status"], "unavailable")
                self.assertEqual(data["ai_hypotheses"], [])


class TestLifespanAsync(unittest.IsolatedAsyncioTestCase):
    """Test FastAPI lifespan lifecycle setup and teardown explicitly."""

    @patch("api.HindsightMemoryManager")
    async def test_lifespan_initializes_and_closes_resources(self, mock_manager_cls):
        temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        temp_db.close()
        temp_db_path = temp_db.name
        try:
            mock_instance = MagicMock()
            mock_instance.is_available = True
            mock_instance.config.bank_id = "opsoria-incidents"
            mock_manager_cls.return_value = mock_instance

            app_instance = create_app()
            app_instance.state.db_path = temp_db_path

            # Explicitly manage lifespan using the app's lifespan_context
            async with app_instance.router.lifespan_context(app_instance):
                self.assertTrue(hasattr(app_instance.state, "memory_manager"))
                self.assertTrue(hasattr(app_instance.state, "processor"))
                self.assertEqual(app_instance.state.incident_registry, {})
                mock_manager_cls.assert_called_once()

                transport = httpx.ASGITransport(app=app_instance)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                    res = await client.get("/health")
                    self.assertEqual(res.status_code, 200)
                    data = res.json()
                    self.assertEqual(data["status"], "healthy")

            # After exiting lifespan context, close() has been called
            mock_instance.close.assert_called_once()
        finally:
            for suffix in ("", "-wal", "-shm"):
                p = temp_db_path + suffix
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass


if __name__ == "__main__":
    unittest.main()
