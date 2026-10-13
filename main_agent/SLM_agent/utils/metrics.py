#!/usr/bin/env python3
"""Per-run metrics recorder (LLM usage, latency and iteration outcomes)"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class MetricsRecorder:
    """
    Collect metrics for one agent run and persist them as JSON.

    The file is rewritten after every event, so a run that is killed or times
    out still leaves the metrics gathered up to that point.
    """

    def __init__(self, path: str, **run_info: Any):
        """
        Initialize recorder

        Args:
            path: Output JSON path (inside the mounted rundir)
            run_info: Static run settings to store (api_type, model, ...)
        """
        self.path = path
        self._start = time.time()
        self._iteration: Optional[Dict[str, Any]] = None
        self.data: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            **run_info,
            "started_at": self._now(),
            "finished_at": None,
            "wall_time_ms": None,
            "agent_success": None,
            "calls": [],
            "iterations": [],
            "totals": {},
        }
        self._flush()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def start_iteration(self, iteration: int, prompt_type: str) -> None:
        """Open a new refinement iteration; later events are attached to it"""
        self._iteration = {
            "iteration": iteration,
            "prompt_type": prompt_type,
            "llm_success": None,
            "structure_valid": None,
            "compilation_success": None,
            "test_success": None,
            "test_time_ms": None,
        }
        self.data["iterations"].append(self._iteration)
        self._flush()

    def update_iteration(self, **fields: Any) -> None:
        """Record outcome fields on the current iteration"""
        if self._iteration is None:
            return
        self._iteration.update(fields)
        self._flush()

    def record_call(self, **fields: Any) -> None:
        """Record one LLM API call"""
        call = {
            "iteration": self._iteration["iteration"] if self._iteration else None,
            **fields,
        }
        self.data["calls"].append(call)
        self._flush()

    def finish(self, success: bool) -> None:
        """Mark the run as finished"""
        self.data["finished_at"] = self._now()
        self.data["wall_time_ms"] = round((time.time() - self._start) * 1000, 1)
        self.data["agent_success"] = success
        self._flush()

    def _totals(self) -> Dict[str, Any]:
        calls = self.data["calls"]
        iterations = self.data["iterations"]

        def total(items, key):
            values = [item.get(key) for item in items if item.get(key) is not None]
            return sum(values) if values else None

        return {
            "iterations": len(iterations),
            "llm_calls": len(calls),
            "failed_llm_calls": sum(1 for call in calls if not call.get("success")),
            "input_tokens": total(calls, "input_tokens"),
            "output_tokens": total(calls, "output_tokens"),
            "total_tokens": total(calls, "total_tokens"),
            "cached_input_tokens": total(calls, "cached_input_tokens"),
            "llm_latency_ms": total(calls, "latency_ms"),
            "test_time_ms": total(iterations, "test_time_ms"),
            "gpu_energy_j": total(calls, "gpu_energy_j"),
            "gpu_peak_memory_mb": max(
                (call["gpu_peak_memory_mb"] for call in calls if call.get("gpu_peak_memory_mb") is not None),
                default=None),
        }

    def _flush(self) -> None:
        self.data["totals"] = self._totals()
        try:
            tmp_path = f"{self.path}.tmp"
            with open(tmp_path, "w") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp_path, self.path)
        except Exception as e:
            # Metrics must never break the agent run
            logger.warning(f"Could not write metrics file {self.path}: {e}")
