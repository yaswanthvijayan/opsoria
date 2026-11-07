"""Opsoria - AI-Powered Engineering Incident Investigation Assistant.

Main entry point and incident ingestion workflow for Opsoria backend.
"""

from __future__ import annotations

import logging
from typing import Any

from hindsight_memory import HindsightMemoryConfig, HindsightMemoryManager
from incident_processor import IncidentProcessor
from models import Incident, IncidentAnalysis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("opsoria")

# Global singleton application services
_memory_manager: HindsightMemoryManager | None = None
_incident_processor: IncidentProcessor | None = None


def get_processor() -> IncidentProcessor:
    """Retrieve or initialize the singleton IncidentProcessor."""
    global _memory_manager, _incident_processor
    if _incident_processor is None:
        _memory_manager = HindsightMemoryManager(HindsightMemoryConfig.from_env())
        _incident_processor = IncidentProcessor(memory_manager=_memory_manager)
    return _incident_processor


def ingest_incident(incident_data: Incident | dict[str, Any]) -> IncidentAnalysis:
    """Ingest and investigate an incident through Opsoria's core workflow.

    Accepts an Incident instance or a raw dictionary with incident fields.
    Recalls historical context, synthesizes investigation analysis,
    and retains the incident in memory.
    """
    if isinstance(incident_data, dict):
        incident = Incident(
            incident_id=incident_data["incident_id"],
            service=incident_data["service"],
            symptoms=incident_data["symptoms"],
            environment=incident_data.get("environment", "production"),
            status=incident_data.get("status", "investigating"),
            possible_causes=incident_data.get("possible_causes", []),
            confirmed_resolution=incident_data.get("confirmed_resolution"),
            metadata=incident_data.get("metadata", {}),
        )
    else:
        incident = incident_data

    processor = get_processor()
    return processor.process_incident(incident)


def resolve_incident(incident: Incident, confirmed_resolution: str) -> IncidentAnalysis:
    """Confirm an incident's resolution and update persistent memory."""
    processor = get_processor()
    return processor.resolve_incident(incident, confirmed_resolution)


def main():
    """Startup verification."""
    print("Opsoria backend environment is ready.")
    processor = get_processor()
    logger.info(
        "Opsoria incident ingestion engine ready. Memory connected: %s",
        processor.memory.is_available if processor.memory else False,
    )


if __name__ == "__main__":
    main()
