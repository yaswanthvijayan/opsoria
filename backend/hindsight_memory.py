"""Production integration layer for Hindsight Cloud memory bank.

Manages persistent incident memory (Retain & Recall) with safety controls,
duplicate prevention, credential protection, non-blocking failure modes,
and hang-free client lifecycle management.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

try:
    from hindsight_client import Hindsight
except ImportError:
    Hindsight = None  # Handled gracefully if SDK not present

from models import HistoricalIncidentContext, Incident

logger = logging.getLogger("opsoria.hindsight")


@dataclass
class HindsightMemoryConfig:
    """Configuration for Hindsight Cloud connection."""

    base_url: str = "https://api.hindsight.vectorize.io"
    bank_id: str = "opsoria-incidents"
    api_key: str | None = None
    timeout: float = 90.0
    cache_file: str = ".retained_cache.json"

    @classmethod
    def from_env(cls) -> HindsightMemoryConfig:
        """Load configuration from environment variables (.env)."""
        load_dotenv()
        return cls(
            base_url=os.getenv(
                "HINDSIGHT_BASE_URL", "https://api.hindsight.vectorize.io"
            ),
            bank_id=os.getenv("HINDSIGHT_BANK_ID", "opsoria-incidents"),
            api_key=os.getenv("HINDSIGHT_API_KEY"),
            timeout=float(os.getenv("HINDSIGHT_TIMEOUT", "90.0")),
            cache_file=os.getenv("HINDSIGHT_CACHE_FILE", ".retained_cache.json"),
        )


class HindsightMemoryManager:
    """Manages Hindsight Cloud memory operations for Opsoria.

    Features:
    - Safe client lifecycle management that guarantees close() cannot hang.
    - Zero credential or raw sensitive content exposure in logs or exceptions.
    - Graceful non-blocking degradation if Hindsight is unreachable.
    - Persistent duplicate prevention across process restarts via checksum caching.
    - Uses Hindsight document_id and update_mode='replace' for document-level updates.
    """

    def __init__(self, config: HindsightMemoryConfig | None = None):
        self.config = config or HindsightMemoryConfig.from_env()
        self._client: Any = None
        self._retained_hashes: dict[str, str] = self._load_cache()
        self._initialize_client()

    def _sanitize(self, message: str) -> str:
        """Strip sensitive credentials from error messages or logs."""
        if self.config.api_key and self.config.api_key in message:
            return message.replace(self.config.api_key, "[REDACTED_API_KEY]")
        return message

    def _load_cache(self) -> dict[str, str]:
        """Load retained incident checksums from disk to persist across restarts."""
        cache_path = self.config.cache_file
        if cache_path and os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
            except Exception as exc:
                logger.debug("Could not load retained cache: %s", self._sanitize(str(exc)))
        return {}

    def _save_cache(self) -> None:
        """Persist retained incident checksums to disk atomically."""
        cache_path = self.config.cache_file
        if not cache_path:
            return

        cache_dir = os.path.dirname(cache_path) or "."
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile("w", dir=cache_dir, delete=False, encoding="utf-8") as tf:
                temp_name = tf.name
                json.dump(self._retained_hashes, tf, indent=2)

            os.replace(temp_name, cache_path)
        except Exception as exc:
            if temp_name and os.path.exists(temp_name):
                try:
                    os.remove(temp_name)
                except OSError:
                    pass
            logger.warning(
                "Failed to persist retained incident cache to '%s': %s. In-memory deduplication remains active.",
                cache_path,
                self._sanitize(str(exc)),
            )

    def _initialize_client(self) -> None:
        """Initialize the official Hindsight SDK client."""
        if not Hindsight:
            logger.warning("hindsight-client SDK is not installed. Memory operations disabled.")
            self._client = None
            return

        if not self.config.api_key:
            logger.warning(
                "HINDSIGHT_API_KEY is not set. Hindsight memory operations will be bypassed."
            )
            self._client = None
            return

        try:
            self._client = Hindsight(
                base_url=self.config.base_url,
                api_key=self.config.api_key,
                timeout=self.config.timeout,
            )
            logger.info(
                "Hindsight client initialized. Base URL: %s, Bank ID: %s, Timeout: %ss",
                self.config.base_url,
                self.config.bank_id,
                self.config.timeout,
            )
        except Exception as exc:
            logger.error(
                "Failed to initialize Hindsight client: %s",
                self._sanitize(str(exc)),
            )
            self._client = None

    @property
    def is_available(self) -> bool:
        """Check if Hindsight client is ready for operations."""
        return self._client is not None

    def retain_incident(self, incident: Incident, force: bool = False) -> bool:
        """Retain an incident in the Hindsight memory bank.

        Args:
            incident: The Incident instance to retain.
            force: Retain even if payload hash matches prior retain.

        Returns:
            bool: True if successfully retained or skipped as duplicate,
                  False if an error occurred.
        """
        if not self.is_available:
            logger.debug(
                "Hindsight client unavailable. Skipping retain for incident %s.",
                incident.incident_id,
            )
            return False

        content = incident.to_memory_content()
        payload_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        # Prevent duplicate API calls for identical incident payloads across restarts
        if not force and self._retained_hashes.get(incident.incident_id) == payload_hash:
            logger.info(
                "Incident %s payload unchanged; skipping redundant Retain call.",
                incident.incident_id,
            )
            return True

        tags = [incident.service, incident.environment, incident.status]
        metadata = {
            "incident_id": incident.incident_id,
            "service": incident.service,
            "environment": incident.environment,
            "status": incident.status,
            "has_confirmed_resolution": str(incident.confirmed_resolution is not None),
        }

        try:
            # Avoid logging sensitive content or full incident text
            logger.info(
                "Retaining incident %s (service: %s, status: %s) to bank %s...",
                incident.incident_id,
                incident.service,
                incident.status,
                self.config.bank_id,
            )

            # Pass document_id and update_mode='replace' for clean document grouping
            response = self._client.retain(
                bank_id=self.config.bank_id,
                content=content,
                document_id=incident.incident_id,
                update_mode="replace",
                metadata=metadata,
                tags=tags,
            )

            is_success = getattr(response, "success", None) is True
            bank_id_received = getattr(response, "bank_id", None)
            bank_matches = bank_id_received == self.config.bank_id

            if is_success and bank_matches:
                self._retained_hashes[incident.incident_id] = payload_hash
                self._save_cache()
                logger.info(
                    "Successfully retained incident %s in bank %s.",
                    incident.incident_id,
                    self.config.bank_id,
                )
                return True

            if not is_success:
                logger.warning(
                    "Hindsight retain returned unsuccessful response for %s.",
                    incident.incident_id,
                )
            elif not bank_matches:
                logger.warning(
                    "Hindsight retain returned unexpected bank_id '%s' (expected '%s') for %s.",
                    bank_id_received,
                    self.config.bank_id,
                    incident.incident_id,
                )
            return False

        except Exception as exc:
            # Failure must not crash the Opsoria application
            logger.error(
                "Hindsight Retain failed for incident %s: %s",
                incident.incident_id,
                self._sanitize(str(exc)),
            )
            return False

    def recall_incidents(
        self,
        query: str,
        tags: list[str] | None = None,
        max_tokens: int = 4096,
    ) -> list[HistoricalIncidentContext]:
        """Recall relevant historical incidents from Hindsight memory bank.

        Args:
            query: Natural language query to search for relevant incidents.
            tags: Optional tags (e.g., service name) to narrow search.
            max_tokens: Token budget for recalled results.

        Returns:
            list[HistoricalIncidentContext]: Retrieved contexts, or [] if empty/failed.
        """
        if not self.is_available:
            logger.debug("Hindsight client unavailable. Returning empty recall results.")
            return []

        try:
            # Avoid logging full raw query to protect potentially sensitive diagnostic tokens
            logger.info(
                "Recalling historical incidents for bank '%s' with tags %s (query length: %d chars)",
                self.config.bank_id,
                tags or [],
                len(query),
            )
            kwargs: dict[str, Any] = {
                "bank_id": self.config.bank_id,
                "query": query,
                "max_tokens": max_tokens,
            }
            if tags:
                kwargs["tags"] = tags

            response = self._client.recall(**kwargs)
            raw_results = getattr(response, "results", None) or []

            contexts: list[HistoricalIncidentContext] = []
            for item in raw_results:
                try:
                    # 1. Document ID: fallback to id or empty string
                    raw_doc_id = getattr(item, "document_id", None) or getattr(item, "id", None) or ""
                    document_id = str(raw_doc_id).strip()

                    # 2. Text: ensure string
                    raw_text = getattr(item, "text", None)
                    text = str(raw_text) if raw_text is not None else ""

                    # Require at least text or document_id
                    if not text and not document_id:
                        logger.warning("Skipping malformed recalled memory item lacking both document_id and text.")
                        continue

                    # 3. Memory type: handle enums, None, and strings
                    raw_type = getattr(item, "type", None)
                    if raw_type is None:
                        memory_type = "observation"
                    elif hasattr(raw_type, "value"):
                        memory_type = str(raw_type.value)
                    else:
                        memory_type = str(raw_type)

                    # 4. Scores: normalize RecallScores model or dict, filter None values and non-floats
                    raw_scores = getattr(item, "scores", None)
                    scores: dict[str, float] | None = None
                    if raw_scores is not None:
                        if hasattr(raw_scores, "to_dict") and callable(raw_scores.to_dict):
                            raw_dict = raw_scores.to_dict()
                        elif hasattr(raw_scores, "model_dump") and callable(raw_scores.model_dump):
                            raw_dict = raw_scores.model_dump()
                        elif isinstance(raw_scores, dict):
                            raw_dict = raw_scores
                        elif hasattr(raw_scores, "__dict__"):
                            raw_dict = raw_scores.__dict__
                        else:
                            raw_dict = None

                        if isinstance(raw_dict, dict):
                            scores_dict: dict[str, float] = {}
                            for k, v in raw_dict.items():
                                if v is not None:
                                    try:
                                        scores_dict[str(k)] = float(v)
                                    except (ValueError, TypeError):
                                        pass
                            scores = scores_dict

                    # 5. Tags: ensure list of strings
                    raw_tags = getattr(item, "tags", None)
                    if isinstance(raw_tags, (list, tuple, set)):
                        tags_list = [str(t) for t in raw_tags if t is not None]
                    elif isinstance(raw_tags, str) and raw_tags.strip():
                        tags_list = [raw_tags.strip()]
                    else:
                        tags_list = []

                    # 6. Metadata: ensure dict
                    raw_meta = getattr(item, "metadata", None)
                    if isinstance(raw_meta, dict):
                        meta_dict = dict(raw_meta)
                    elif hasattr(raw_meta, "to_dict") and callable(raw_meta.to_dict):
                        meta_dict = raw_meta.to_dict()
                    elif hasattr(raw_meta, "model_dump") and callable(raw_meta.model_dump):
                        meta_dict = raw_meta.model_dump()
                    else:
                        meta_dict = {}

                    is_synthetic = (
                        str(meta_dict.get("type", "")).strip().lower() == "synthetic_test"
                        or any("synthetic" in t.lower() for t in tags_list)
                        or "synthetic" in str(meta_dict.get("service", "")).lower()
                        or "synthetic" in str(meta_dict.get("environment", "")).lower()
                    )

                    contexts.append(
                        HistoricalIncidentContext(
                            document_id=document_id,
                            text=text,
                            memory_type=memory_type,
                            scores=scores,
                            tags=tags_list,
                            metadata=meta_dict,
                            is_synthetic=is_synthetic,
                        )
                    )
                except Exception as item_exc:
                    logger.warning(
                        "Skipping malformed recalled memory item: %s",
                        self._sanitize(str(item_exc)),
                    )
                    continue

            logger.info(
                "Hindsight recall returned %d relevant historical contexts.",
                len(contexts),
            )
            return contexts

        except Exception as exc:
            # Failure must not crash the Opsoria application
            logger.error(
                "Hindsight Recall failed for query length %d: %s",
                len(query),
                self._sanitize(str(exc)),
            )
            return []

    def close(self, timeout: float = 2.0) -> None:
        """Close client connections safely without hanging the process."""
        if not self._client:
            return

        client_to_close = self._client
        self._client = None

        if hasattr(client_to_close, "close"):
            def _shutdown():
                try:
                    client_to_close.close()
                except Exception as exc:
                    logger.debug("Error during client close: %s", self._sanitize(str(exc)))

            # Run SDK close in a daemon thread with timeout to protect against event loop deadlocks
            t = threading.Thread(target=_shutdown, daemon=True)
            t.start()
            t.join(timeout=timeout)
            if t.is_alive():
                logger.warning(
                    "Hindsight client close timed out after %s seconds; released reference.",
                    timeout,
                )
            else:
                logger.debug("Hindsight client closed cleanly.")

    def __enter__(self) -> HindsightMemoryManager:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
