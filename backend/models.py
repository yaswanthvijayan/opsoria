"""Data models for Opsoria incident processing and memory integration."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Incident:
    """Represents an engineering incident within Opsoria."""

    incident_id: str
    service: str
    symptoms: str
    environment: str = "production"
    status: str = "investigating"  # "investigating", "mitigated", "resolved"
    possible_causes: list[str] = field(default_factory=list)
    confirmed_resolution: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, str] = field(default_factory=dict)

    def to_memory_content(self) -> str:
        """Format incident for Hindsight memory retention.

        Distinguishes clearly between confirmed facts and unverified hypotheses.
        """
        lines = [
            f"Incident ID: {self.incident_id}",
            f"Service: {self.service}",
            f"Environment: {self.environment}",
            f"Status: {self.status.upper()}",
            f"Symptoms: {self.symptoms}",
        ]

        if self.possible_causes:
            lines.append("Possible Causes (UNVERIFIED HYPOTHESES):")
            for cause in self.possible_causes:
                lines.append(f"  - [HYPOTHESIS] {cause}")

        if self.confirmed_resolution:
            lines.append(f"Confirmed Resolution: {self.confirmed_resolution}")
        else:
            lines.append("Confirmed Resolution: None confirmed (INVESTIGATION ONGOING)")

        return "\n".join(lines)


@dataclass
class HistoricalIncidentContext:
    """Historical context retrieved from Hindsight memory bank."""

    document_id: str
    text: str
    memory_type: str = "observation"
    scores: dict[str, float] | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    is_synthetic: bool = False


@dataclass
class IncidentAnalysis:
    """Output of Opsoria's incident investigation analysis."""

    incident_id: str
    service: str
    environment: str
    symptoms: str
    status: str
    historical_matches_count: int
    historical_context: list[HistoricalIncidentContext]
    investigation_summary: str
    recommended_steps: list[str]
    confirmed_resolution: str | None = None

