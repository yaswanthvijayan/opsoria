"""Unit tests for Groq AI reasoning layer (groq_analyst.py)."""

import os
import unittest
from unittest.mock import MagicMock, patch

import groq_analyst
from models import HistoricalIncidentContext, Incident


class TestGroqAnalyst(unittest.TestCase):
    """Test suite for Groq AI reasoning layer with mocked Groq SDK client."""

    def setUp(self):
        self.incident = Incident(
            incident_id="INC-AI-01",
            service="checkout-service",
            environment="production",
            symptoms="HTTP 504 Gateway Timeout during checkout",
            possible_causes=["Slow upstream inventory service"],
        )
        self.recalled_records = [
            HistoricalIncidentContext(
                document_id="INC-PAST-01",
                text="Prior checkout timeout caused by inventory database locking.",
                is_synthetic=False,
            ),
            HistoricalIncidentContext(
                document_id="INC-SYNTH-99",
                text="Synthetic test data for load testing payment gateway.",
                is_synthetic=True,
            ),
        ]

    def test_missing_api_key_returns_not_configured(self):
        """Test missing GROQ_API_KEY returns ai_status='not_configured' without calling SDK."""
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            result = groq_analyst.analyze(self.incident, self.recalled_records)
            self.assertEqual(result["ai_status"], "not_configured")
            self.assertEqual(result["ai_hypotheses"], [])

    @patch("groq_analyst.Groq")
    def test_successful_analysis_and_prompt_delimiters(self, mock_groq_cls):
        """Test successful Groq response parsing and presence of security delimiters."""
        mock_client = MagicMock()
        mock_completion = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()

        json_response = """
        {
          "hypotheses": [
            {
              "title": "Inventory Service Thread Pool Starvation",
              "reasoning": "Upstream inventory latency cascades into 504s on checkout.",
              "evidence_refs": ["INC-PAST-01"],
              "confidence": "high",
              "suggested_checks": ["Inspect thread dump of inventory pod"]
            }
          ],
          "investigation_plan": [
            "Check inventory service response time metrics",
            "Verify connection pool saturation"
          ],
          "caveats": [
            "Synthetic test data INC-SYNTH-99 is not verified production guidance."
          ]
        }
        """
        mock_message.content = json_response
        mock_choice.message = mock_message
        mock_completion.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_completion
        mock_groq_cls.return_value = mock_client

        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_secret_mock_key_999"}):
            result = groq_analyst.analyze(self.incident, self.recalled_records)

            self.assertEqual(result["ai_status"], "success")
            self.assertEqual(len(result["ai_hypotheses"]), 1)
            hypo = result["ai_hypotheses"][0]
            self.assertEqual(hypo["title"], "Inventory Service Thread Pool Starvation")
            self.assertEqual(hypo["confidence"], "high")
            self.assertEqual(hypo["evidence_refs"], ["INC-PAST-01"])
            self.assertEqual(len(result["ai_investigation_plan"]), 2)
            self.assertEqual(len(result["ai_caveats"]), 1)

            mock_groq_cls.assert_called_once_with(
                api_key="gsk_secret_mock_key_999", timeout=20.0, max_retries=0
            )

            # Verify prompt contents: security delimiters & synthetic warning
            called_kwargs = mock_client.chat.completions.create.call_args[1]
            messages = called_kwargs["messages"]
            system_msg = messages[0]["content"]
            user_msg = messages[1]["content"]

            self.assertIn("<<<UNTRUSTED_INCIDENT_DATA>>>", user_msg)
            self.assertIn("<<</UNTRUSTED_INCIDENT_DATA>>>", user_msg)
            self.assertIn("SYNTHETIC TEST DATA", user_msg)
            self.assertIn("UNTRUSTED USER DATA", system_msg)
            self.assertIn(
                "Only cite an evidence_ref when the recalled record's text directly supports that specific hypothesis",
                system_msg,
            )
            self.assertIn(
                "Never use confidence 'medium' or 'high' when the only supporting evidence is synthetic test data; use 'low'.",
                system_msg,
            )
            self.assertEqual(called_kwargs["temperature"], 0.2)
            self.assertEqual(called_kwargs["max_tokens"], 1500)

    @patch("groq_analyst.Groq")
    def test_markdown_code_fences_and_malformed_items_dropped(self, mock_groq_cls):
        """Test markdown code fences are stripped and malformed items dropped gracefully."""
        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()

        # Wrapped in code fence with 1 valid and 1 malformed item missing required title
        fenced_response = """```json
        {
          "hypotheses": [
            {
              "title": "Valid Hypothesis",
              "reasoning": "Reasonable explanation",
              "confidence": "medium",
              "suggested_checks": ["Check logs"]
            },
            {
              "malformed_field": "Missing title and reasoning"
            }
          ],
          "investigation_plan": ["Step 1"],
          "caveats": ["Caveat 1"]
        }
        ```"""
        mock_message.content = fenced_response
        mock_choice.message = mock_message
        mock_choice_list = [mock_choice]
        mock_completion = MagicMock(choices=mock_choice_list)
        mock_client.chat.completions.create.return_value = mock_completion
        mock_groq_cls.return_value = mock_client

        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test_key"}):
            result = groq_analyst.analyze(self.incident, self.recalled_records)
            self.assertEqual(result["ai_status"], "success")
            # Malformed hypothesis was dropped, only valid one kept
            self.assertEqual(len(result["ai_hypotheses"]), 1)
            self.assertEqual(result["ai_hypotheses"][0]["title"], "Valid Hypothesis")

    @patch("groq_analyst.Groq")
    def test_timeout_or_api_error_returns_unavailable_with_sanitized_log(self, mock_groq_cls):
        """Test timeout/API exception returns ai_status='unavailable' and sanitizes credentials in logs."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = TimeoutError(
            "Request timed out using key gsk_secret_super_private_token_123"
        )
        mock_groq_cls.return_value = mock_client

        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_secret_super_private_token_123"}):
            with self.assertLogs("opsoria.groq", level="WARNING") as cm:
                result = groq_analyst.analyze(self.incident, self.recalled_records)

            self.assertEqual(result["ai_status"], "unavailable")
            self.assertEqual(result["ai_hypotheses"], [])

            # Verify API key was sanitized in log
            log_output = "\n".join(cm.output)
            self.assertNotIn("gsk_secret_super_private_token_123", log_output)
            self.assertIn("[REDACTED_GROQ_KEY]", log_output)

    @patch("groq_analyst.Groq")
    def test_all_synthetic_records_forces_confidence_to_low(self, mock_groq_cls):
        """Test that confidence is forced to 'low' for all hypotheses if every recalled record is synthetic."""
        synthetic_records = [
            HistoricalIncidentContext(
                document_id="INC-SYNTH-01",
                text="Synthetic test data record 1",
                is_synthetic=True,
            ),
            HistoricalIncidentContext(
                document_id="INC-SYNTH-02",
                text="Synthetic test data record 2",
                is_synthetic=True,
            ),
        ]

        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()

        json_response = """
        {
          "hypotheses": [
            {
              "title": "Hypothesis 1",
              "reasoning": "Reasoning based on synthetic data",
              "evidence_refs": ["INC-SYNTH-01"],
              "confidence": "high",
              "suggested_checks": ["Check 1"]
            },
            {
              "title": "Hypothesis 2",
              "reasoning": "Another reasoning",
              "evidence_refs": ["INC-SYNTH-02"],
              "confidence": "medium",
              "suggested_checks": ["Check 2"]
            }
          ],
          "investigation_plan": ["Verify telemetry"],
          "caveats": ["All data is synthetic"]
        }
        """
        mock_message.content = json_response
        mock_choice.message = mock_message
        mock_completion = MagicMock(choices=[mock_choice])
        mock_client.chat.completions.create.return_value = mock_completion
        mock_groq_cls.return_value = mock_client

        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test_key"}):
            result = groq_analyst.analyze(self.incident, synthetic_records)

            self.assertEqual(result["ai_status"], "success")
            self.assertEqual(len(result["ai_hypotheses"]), 2)
            # Both hypotheses must have confidence forced to "low"
            self.assertEqual(result["ai_hypotheses"][0]["confidence"], "low")
            self.assertEqual(result["ai_hypotheses"][1]["confidence"], "low")
            # Evidence refs that were present in recalled history remain
            self.assertEqual(result["ai_hypotheses"][0]["evidence_refs"], ["INC-SYNTH-01"])
            self.assertEqual(result["ai_hypotheses"][1]["evidence_refs"], ["INC-SYNTH-02"])

    @patch("groq_analyst.Groq")
    def test_drop_evidence_refs_not_in_recalled_history(self, mock_groq_cls):
        """Test dropping evidence_refs that are not prior_incident_ids present in recalled history."""
        recalled = [
            HistoricalIncidentContext(
                document_id="INC-REAL-01",
                text="Real production incident with database lock.",
                is_synthetic=False,
            )
        ]

        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()

        json_response = """
        {
          "hypotheses": [
            {
              "title": "Database Deadlock",
              "reasoning": "Locks detected in past incident.",
              "evidence_refs": ["INC-REAL-01", "INC-NONEXISTENT", "HALLUCINATED-UUID-1234"],
              "confidence": "high",
              "suggested_checks": ["Inspect pg_stat_activity"]
            }
          ],
          "investigation_plan": ["Query locks"],
          "caveats": []
        }
        """
        mock_message.content = json_response
        mock_choice.message = mock_message
        mock_completion = MagicMock(choices=[mock_choice])
        mock_client.chat.completions.create.return_value = mock_completion
        mock_groq_cls.return_value = mock_client

        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test_key"}):
            result = groq_analyst.analyze(self.incident, recalled)

            self.assertEqual(result["ai_status"], "success")
            self.assertEqual(len(result["ai_hypotheses"]), 1)
            hypo = result["ai_hypotheses"][0]
            # INC-REAL-01 kept; INC-NONEXISTENT and HALLUCINATED-UUID-1234 dropped
            self.assertEqual(hypo["evidence_refs"], ["INC-REAL-01"])
            # Non-synthetic record present, so high confidence is preserved
            self.assertEqual(hypo["confidence"], "high")

    @patch("groq_analyst.Groq")
    def test_empty_recalled_history_drops_all_evidence_refs(self, mock_groq_cls):
        """Test that when recalled history is empty, all hallucinated evidence_refs are dropped."""
        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()

        json_response = """
        {
          "hypotheses": [
            {
              "title": "Memory Leak",
              "reasoning": "OOM killer invoked.",
              "evidence_refs": ["INC-GHOST-99"],
              "confidence": "medium",
              "suggested_checks": ["Check dmesg"]
            }
          ],
          "investigation_plan": ["Check memory metrics"],
          "caveats": []
        }
        """
        mock_message.content = json_response
        mock_choice.message = mock_message
        mock_completion = MagicMock(choices=[mock_choice])
        mock_client.chat.completions.create.return_value = mock_completion
        mock_groq_cls.return_value = mock_client

        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test_key"}):
            result = groq_analyst.analyze(self.incident, [])

            self.assertEqual(result["ai_status"], "success")
            self.assertEqual(len(result["ai_hypotheses"]), 1)
            hypo = result["ai_hypotheses"][0]
            self.assertEqual(hypo["evidence_refs"], [])
            self.assertEqual(hypo["confidence"], "medium")


    @patch("groq_analyst.Groq")
    def test_derive_prior_incident_id_from_metadata_and_text_and_reject_uuids(self, mock_groq_cls):
        """Test that prior incident IDs are derived from metadata or text, and UUIDs are never accepted as evidence refs."""
        uuid_doc_1 = "c18f3a8b-1111-4444-8888-abcdefabcdef"
        uuid_doc_2 = "e29a4b9c-2222-4444-8888-fedcbafedcba"

        recalled = [
            # Item 1: UUID document_id, but has metadata.incident_id = "INC-META-101"
            HistoricalIncidentContext(
                document_id=uuid_doc_1,
                text="Database timeout during peak hours.",
                metadata={"incident_id": "INC-META-101"},
                is_synthetic=False,
            ),
            # Item 2: UUID document_id, no metadata, but text contains "Incident INC-TEXT-202"
            HistoricalIncidentContext(
                document_id=uuid_doc_2,
                text="Prior report: Incident INC-TEXT-202 observed connection pool saturation.",
                metadata={},
                is_synthetic=False,
            ),
        ]

        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()

        json_response = f"""
        {{
          "hypotheses": [
            {{
              "title": "Pool Saturation",
              "reasoning": "Connection exhaustion observed.",
              "evidence_refs": ["INC-META-101", "INC-TEXT-202", "{uuid_doc_1}", "00000000-0000-0000-0000-000000000000"],
              "confidence": "high",
              "suggested_checks": ["Check pool metrics"]
            }}
          ],
          "investigation_plan": ["Verify metrics"],
          "caveats": []
        }}
        """
        mock_message.content = json_response
        mock_choice.message = mock_message
        mock_completion = MagicMock(choices=[mock_choice])
        mock_client.chat.completions.create.return_value = mock_completion
        mock_groq_cls.return_value = mock_client

        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test_key"}):
            result = groq_analyst.analyze(self.incident, recalled)

            self.assertEqual(result["ai_status"], "success")
            self.assertEqual(len(result["ai_hypotheses"]), 1)
            hypo = result["ai_hypotheses"][0]
            # Derived IDs INC-META-101 and INC-TEXT-202 are accepted
            # Both UUIDs (including uuid_doc_1 matching item's document_id) are strictly dropped
            self.assertEqual(hypo["evidence_refs"], ["INC-META-101", "INC-TEXT-202"])
            self.assertEqual(hypo["confidence"], "high")


if __name__ == "__main__":
    unittest.main()

