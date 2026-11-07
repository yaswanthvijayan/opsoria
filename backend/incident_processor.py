"""Opsoria Incident Investigation and Processing Workflow.

Integrates incoming incident data with Hindsight Cloud memory bank to
surface historical context, synthesize investigations, retain incoming incidents,
and update memories with confirmed resolutions.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import TYPE_CHECKING

from models import HistoricalIncidentContext, Incident, IncidentAnalysis

if TYPE_CHECKING:
    from hindsight_memory import HindsightMemoryManager

logger = logging.getLogger("opsoria.processor")


class IncidentProcessor:
    """Orchestrates incident ingestion, historical memory recall, and analysis."""

    def __init__(self, memory_manager: HindsightMemoryManager | None = None):
        self.memory = memory_manager

    def process_incident(self, incident: Incident) -> IncidentAnalysis:
        """Process an incoming incident through Opsoria's investigation workflow.

        Steps:
        1. Extract relevant incident information.
        2. Query Hindsight for similar historical incidents (Recall).
        3. Persist confirmed resolution to Hindsight memory bank (if resolved).
        4. Synthesize incident analysis with strict distinction between facts & hypotheses.
        """
        logger.info(
            "Processing incident %s (service: '%s', env: '%s', status: '%s').",
            incident.incident_id,
            incident.service,
            incident.environment,
            incident.status,
        )

        # 1 & 2. Extract information and query Hindsight for historical incidents
        historical_contexts: list[HistoricalIncidentContext] = []
        if self.memory and self.memory.is_available:
            recall_query = (
                f"Incident involving service '{incident.service}' in environment '{incident.environment}': "
                f"{incident.symptoms}"
            )
            historical_contexts = self.memory.recall_incidents(
                query=recall_query,
                tags=[incident.service],
            )
            for ctx in historical_contexts:
                if not ctx.is_synthetic:
                    ctx.is_synthetic = self._check_is_synthetic(ctx, incident)
        else:
            logger.info("Memory manager unavailable; proceeding without historical context.")

        # 3. Retention policy: Retain when confirmed resolution is present BEFORE synthesizing analysis
        retain_success: bool | None = None
        if incident.confirmed_resolution:
            if self.memory and self.memory.is_available:
                logger.info(
                    "Persisting incident %s with confirmed resolution to Hindsight memory bank...",
                    incident.incident_id,
                )
                retain_success = self.memory.retain_incident(incident)
                if not retain_success:
                    logger.warning(
                        "Confirmed resolution for incident %s received, but Hindsight retain failed.",
                        incident.incident_id,
                    )
            else:
                retain_success = False
                logger.warning(
                    "Confirmed resolution for incident %s received, but Hindsight memory is unavailable.",
                    incident.incident_id,
                )

        # 4. Include retrieved context in the analysis (never treat hypotheses as facts)
        analysis = self._synthesize_analysis(
            incident, historical_contexts, retain_success=retain_success
        )

        return analysis

    def resolve_incident(
        self, incident: Incident, confirmed_resolution: str
    ) -> IncidentAnalysis:
        """Confirm the resolution of an incident, synthesize updated analysis, and persist to memory."""
        logger.info(
            "Confirming resolution for incident %s (resolution length: %d chars).",
            incident.incident_id,
            len(confirmed_resolution),
        )
        incident.status = "resolved"
        incident.confirmed_resolution = confirmed_resolution

        # process_incident performs synthesis and persists updated confirmed resolution to memory
        return self.process_incident(incident)

    @staticmethod
    def _check_is_synthetic(
        item: HistoricalIncidentContext, incident: Incident | None = None
    ) -> bool:
        """Determine if a historical record is synthetic test data."""
        # 1. metadata.type is "synthetic_test"
        if str(item.metadata.get("type", "")).strip().lower() == "synthetic_test":
            return True

        # 2. any tag contains "synthetic" (case-insensitive)
        for tag in item.tags:
            if "synthetic" in tag.lower():
                return True

        # 3. incident or metadata service/environment contains "synthetic"
        if "synthetic" in str(item.metadata.get("service", "")).lower():
            return True
        if "synthetic" in str(item.metadata.get("environment", "")).lower():
            return True
        if incident:
            if "synthetic" in incident.service.lower():
                return True
            if "synthetic" in incident.environment.lower():
                return True

        return False

    @staticmethod
    def _extract_prior_incident_id(item: HistoricalIncidentContext) -> str:
        """Extract prior incident identifier from metadata, text regex, or document_id."""
        meta_id = item.metadata.get("incident_id")
        if meta_id and str(meta_id).strip():
            return str(meta_id).strip()

        match = re.search(r"Incident\s+([A-Za-z0-9._-]+)", item.text, re.IGNORECASE)
        if match:
            extracted = match.group(1).rstrip(".,:;").strip()
            if extracted and extracted.lower() not in (
                "id",
                "identifier",
                "report",
                "fact",
                "record",
            ):
                return extracted

        return item.document_id

    @staticmethod
    def _is_uuid(val: str) -> bool:
        """Check if an identifier is a UUID string."""
        if not val:
            return False
        try:
            uuid.UUID(str(val).strip())
            return True
        except (ValueError, AttributeError, TypeError):
            return False

    def _synthesize_analysis(
        self,
        incident: Incident,
        history: list[HistoricalIncidentContext],
        retain_success: bool | None = None,
    ) -> IncidentAnalysis:
        """Synthesize analysis from incident symptoms and retrieved historical memory."""
        summary_lines = [
            f"Investigation for {incident.incident_id} ({incident.service} - {incident.environment}):",
            f"Reported Symptoms: {incident.symptoms}",
            f"Current Status: {incident.status.upper()}",
        ]

        recommended_steps: list[str] = []

        # Analyze historical matches
        if history:
            # Mark records as synthetic if not already marked
            for item in history:
                if not item.is_synthetic:
                    item.is_synthetic = self._check_is_synthetic(item, incident)

            # Group records by prior incident id
            prior_ids = [self._extract_prior_incident_id(item) for item in history]
            distinct_prior_ids = list(dict.fromkeys(prior_ids))

            records_count = len(history)
            prior_count = len(distinct_prior_ids)
            records_word = (
                "1 related memory record"
                if records_count == 1
                else f"{records_count} related memory records"
            )
            incident_word = (
                "1 prior incident"
                if prior_count == 1
                else f"{prior_count} prior incidents"
            )

            summary_lines.append(
                f"\n[HISTORICAL MEMORY CONTEXT]: Found {records_word} from {incident_word}."
            )

            # Show at most the top 3 records, truncated to about 200 characters
            display_records = history[:3]
            for idx, item in enumerate(display_records, 1):
                clean_text = item.text.replace("\n", " ").strip()
                if len(clean_text) > 200:
                    clean_text = clean_text[:200] + "..."
                prior_id = self._extract_prior_incident_id(item)
                prefix = (
                    "[SYNTHETIC TEST DATA - not a production fix] "
                    if item.is_synthetic
                    else ""
                )
                summary_lines.append(
                    f"  - Match #{idx} [{prior_id}]: {prefix}{clean_text}"
                )

            # In recommended_steps, reference distinct prior incident IDs only (never UUIDs)
            valid_prior_ids = [
                pid for pid in distinct_prior_ids if pid and not self._is_uuid(pid)
            ]
            if valid_prior_ids:
                recommended_steps.append(
                    f"Review historical patterns from prior incidents ({', '.join(valid_prior_ids)})."
                )
            else:
                recommended_steps.append(
                    "Review historical patterns from prior incidents."
                )

            # If any matched record is synthetic, add warning step
            if any(item.is_synthetic for item in history):
                recommended_steps.append(
                    "Matched history includes synthetic test data and must NOT be treated as verified production guidance."
                )

            # Recalled resolutions wording: always phrased as hypothesis/prior report, never current verified fix
            for item in history:
                resolution_text = None
                meta_res = item.metadata.get("confirmed_resolution")
                if meta_res and str(meta_res).strip():
                    resolution_text = str(meta_res).strip()
                else:
                    res_match = re.search(
                        r"(?:Confirmed Resolution|reported resolution|resolution):\s*([^\n]+)",
                        item.text,
                        re.IGNORECASE,
                    )
                    if res_match:
                        candidate = res_match.group(1).strip()
                        if candidate.lower() not in (
                            "none confirmed (investigation ongoing)",
                            "none",
                            "unknown",
                        ):
                            resolution_text = candidate

                if resolution_text:
                    cleaned_res = resolution_text.rstrip(".").strip()
                    prior_id = self._extract_prior_incident_id(item)
                    id_label = f" {prior_id}" if not self._is_uuid(prior_id) else ""
                    step_msg = (
                        f"Prior incident{id_label} reported resolution: {cleaned_res}. "
                        "Validate against current telemetry before applying."
                    )
                    if step_msg not in recommended_steps:
                        recommended_steps.append(step_msg)
        else:
            summary_lines.append(
                "\n[HISTORICAL MEMORY CONTEXT]: No related historical incidents found. Treating as novel issue."
            )
            recommended_steps.append(
                "Establish initial diagnostic baseline as no matching historical patterns were found."
            )

        # Formulate recommended steps based on status
        if incident.confirmed_resolution:
            summary_lines.append(
                f"\n[CONFIRMED RESOLUTION]: {incident.confirmed_resolution}"
            )
            recommended_steps.append(
                "Verify post-incident monitoring metrics to ensure system stability."
            )
            if retain_success is True:
                recommended_steps.append(
                    "Resolution confirmed and persisted in Opsoria memory bank."
                )
            else:
                recommended_steps.append(
                    "Resolution confirmed locally, but NOT persisted to the memory bank (Hindsight unavailable or retain failed)."
                )
        else:
            if incident.possible_causes:
                summary_lines.append("\n[UNCONFIRMED HYPOTHESES TO INVESTIGATE]:")
                for cause in incident.possible_causes:
                    summary_lines.append(f"  - Hypothesis (Unverified): {cause}")
                    recommended_steps.append(
                        f"Investigate hypothesis: '{cause}' (Do not treat as confirmed until validated)."
                    )
            recommended_steps.append(
                "Inspect live telemetry, container logs, and recent deployment changes."
            )

        return IncidentAnalysis(
            incident_id=incident.incident_id,
            service=incident.service,
            environment=incident.environment,
            symptoms=incident.symptoms,
            status=incident.status,
            historical_matches_count=len(history),
            historical_context=history,
            investigation_summary="\n".join(summary_lines),
            recommended_steps=recommended_steps,
            confirmed_resolution=incident.confirmed_resolution,
        )
