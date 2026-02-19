import json
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class LockInfo:
    pid: int
    started_at: float
    mode: str
    exchange: str
    host: str


class SingleInstanceLock:
    """Atomic single-instance lock using O_EXCL lock-file creation."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._owned = False

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            if int(pid) <= 0:
                return False
            os.kill(int(pid), 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except Exception:
            return False

    def read(self) -> Optional[LockInfo]:
        if not self.path.exists():
            return None
        try:
            raw = self.path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            return LockInfo(
                pid=int(payload.get("pid", 0)),
                started_at=float(payload.get("started_at", 0.0)),
                mode=str(payload.get("mode", "")),
                exchange=str(payload.get("exchange", "")),
                host=str(payload.get("host", "")),
            )
        except Exception:
            return None

    def acquire(self, mode: str, exchange: str, force: bool = False):
        payload = {
            "pid": os.getpid(),
            "started_at": time.time(),
            "mode": str(mode or "").upper(),
            "exchange": str(exchange or "").upper(),
            "host": socket.gethostname(),
        }
        body = json.dumps(payload, ensure_ascii=False)

        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(str(self.path), flags)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(body)
            self._owned = True
            return True, "acquired"
        except FileExistsError:
            if not force:
                info = self.read()
                if info and self._pid_alive(info.pid):
                    return False, f"lock-held pid={info.pid} mode={info.mode} exchange={info.exchange}"
                return False, "lock-exists"

            # force path: remove stale or unreadable lock and retry once
            try:
                self.path.unlink(missing_ok=True)
            except Exception as e:
                return False, f"force-unlink-failed: {e}"
            try:
                fd = os.open(str(self.path), flags)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(body)
                self._owned = True
                return True, "acquired-force"
            except Exception as e:
                return False, f"acquire-failed-after-force: {e}"
        except Exception as e:
            return False, f"acquire-error: {e}"

    def release(self):
        if not self.path.exists():
            return True
        try:
            info = self.read()
            if info and int(info.pid) != os.getpid() and self._owned:
                return False
            if info and int(info.pid) != os.getpid() and not self._owned:
                return False
            self.path.unlink(missing_ok=True)
            self._owned = False
            return True
        except Exception:
            return False
