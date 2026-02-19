import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any


PHASE_BOOTING_DEGRADED = "BOOTING_DEGRADED"
PHASE_WAITING_SYNC = "WAITING_SYNC"
PHASE_WAITING_OPERATOR = "WAITING_OPERATOR"
PHASE_RUNNING = "RUNNING"
PHASE_STOPPED = "STOPPED"


@dataclass
class SafeStartResult:
    ok: bool
    phase: str
    details: Dict[str, Any]


class SafeStartManager:
    def __init__(self, state_path: Path, runtime_state_path: Path, runtime_status_path: Path):
        self.state_path = Path(state_path)
        self.runtime_state_path = Path(runtime_state_path)
        self.runtime_status_path = Path(runtime_status_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def _write_state(self, phase: str, details: Dict[str, Any]):
        payload = {
            "ts": time.time(),
            "phase": phase,
            "details": details or {},
        }
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    def read_state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {"phase": PHASE_STOPPED, "details": {}, "ts": None}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {"phase": PHASE_STOPPED, "details": {"error": "state-corrupt"}, "ts": None}

    def begin_boot(self) -> SafeStartResult:
        details = {
            "message": "Start requested. Entering DEGRADED boot.",
            "running_blocked": True,
        }
        self._write_state(PHASE_BOOTING_DEGRADED, details)
        return SafeStartResult(ok=True, phase=PHASE_BOOTING_DEGRADED, details=details)

    def sync_check(self) -> SafeStartResult:
        errors = []

        # Check runtime_state json readability
        if self.runtime_state_path.exists():
            try:
                val = json.loads(self.runtime_state_path.read_text(encoding="utf-8"))
                if not isinstance(val, dict):
                    errors.append("runtime_state_not_object")
            except Exception as e:
                errors.append(f"runtime_state_invalid:{e}")

        # Check runtime_status json readability (best-effort)
        if self.runtime_status_path.exists():
            try:
                val = json.loads(self.runtime_status_path.read_text(encoding="utf-8"))
                if not isinstance(val, dict):
                    errors.append("runtime_status_not_object")
            except Exception as e:
                errors.append(f"runtime_status_invalid:{e}")

        if errors:
            details = {
                "message": "Sync check failed. RUNNING is blocked.",
                "errors": errors,
                "running_blocked": True,
            }
            self._write_state(PHASE_WAITING_SYNC, details)
            return SafeStartResult(ok=False, phase=PHASE_WAITING_SYNC, details=details)

        details = {
            "message": "Sync check passed. Waiting for operator confirmation.",
            "running_blocked": True,
        }
        self._write_state(PHASE_WAITING_OPERATOR, details)
        return SafeStartResult(ok=True, phase=PHASE_WAITING_OPERATOR, details=details)

    def mark_running(self) -> SafeStartResult:
        details = {
            "message": "Operator confirmed. RUNNING enabled.",
            "running_blocked": False,
        }
        self._write_state(PHASE_RUNNING, details)
        return SafeStartResult(ok=True, phase=PHASE_RUNNING, details=details)

    def mark_stopped(self, reason: str = "stopped") -> SafeStartResult:
        details = {
            "message": reason,
            "running_blocked": True,
        }
        self._write_state(PHASE_STOPPED, details)
        return SafeStartResult(ok=True, phase=PHASE_STOPPED, details=details)
