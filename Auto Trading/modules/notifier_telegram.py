import json
import logging
import os
import time
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .utils_json import SCHEMA_VERSION_FIELD, safe_json_dump, safe_json_load

logger = logging.getLogger("NotifierTelegram")


class TelegramNotifier:
    # Outbox state machine (v2)
    STATUS_REQUESTED = "requested"
    STATUS_ACCEPTED = "accepted"
    STATUS_FILLED = "filled"
    STATUS_CANCELED = "canceled"
    STATUS_SUCCESS = {"filled", "SENT"}
    CURRENT_SCHEMA_VERSION = 2

    def __init__(
        self,
        bot_token: str = None,
        chat_id: str = None,
        storage_dir: str = "results/outbox",
        file_name: str = "telegram_outbox.json",
    ):
        if not bot_token:
            bot_token = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
        if not chat_id:
            chat_id = os.getenv("TELEGRAM_CHAT_ID")

        self.bot_token = bot_token
        self.chat_id = chat_id
        self.storage_dir = Path(storage_dir)
        self.file_path = self.storage_dir / file_name

        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.outbox: List[Dict] = []
        self.dedupe_cache: Dict[str, float] = {}

        self.load_outbox()

    @classmethod
    def _normalize_status(cls, status: str) -> str:
        if status in {"SENT"}:  # legacy
            return cls.STATUS_FILLED
        if status in {"PENDING"}:  # legacy
            return cls.STATUS_REQUESTED
        if status in {"FAILED"}:  # legacy
            return cls.STATUS_CANCELED
        return str(status or cls.STATUS_REQUESTED).lower()

    @classmethod
    def _legacy_event_shape(cls, payload: object) -> List[Dict]:
        # Legacy file format is plain list[dict]
        if isinstance(payload, list):
            events = []
            for evt in payload:
                if not isinstance(evt, dict):
                    continue
                evt = dict(evt)
                evt["status"] = cls._normalize_status(evt.get("status"))
                events.append(evt)
            return events

        if not isinstance(payload, dict):
            return []

        events = payload.get("events") if isinstance(payload, dict) else None
        if isinstance(events, list):
            normalized = []
            for evt in events:
                if not isinstance(evt, dict):
                    continue
                evt = dict(evt)
                evt["status"] = cls._normalize_status(evt.get("status"))
                normalized.append(evt)
            return normalized

        return []

    def load_outbox(self):
        """Loads outbox from JSON file with schema repair fallback."""
        default = {
            SCHEMA_VERSION_FIELD: self.CURRENT_SCHEMA_VERSION,
            "events": [],
        }
        data = safe_json_load(
            self.file_path,
            default=default,
            schema_version=self.CURRENT_SCHEMA_VERSION,
            repair=True,
            schema_migrations=[self._legacy_event_shape],
        )

        # Support both legacy list format and current object wrapper.
        if isinstance(data, list):
            data = {
                SCHEMA_VERSION_FIELD: self.CURRENT_SCHEMA_VERSION,
                "events": self._legacy_event_shape(data),
            }
        elif not isinstance(data, dict):
            data = default

        if not isinstance(data.get("events"), list):
            data["events"] = self._legacy_event_shape(data)

        self.outbox = []
        self.dedupe_cache = {}

        now = time.time()
        for evt in data.get("events", []):
            if not isinstance(evt, dict):
                continue

            # Normalize status and fill missing defaults for repaired rows.
            evt = dict(evt)
            status = evt.get("status") or self.STATUS_REQUESTED
            evt["status"] = self._normalize_status(status)
            evt.setdefault("retry_count", 0)
            evt.setdefault("next_retry_ts", 0.0)
            evt.setdefault("last_error", None)

            self.outbox.append(evt)

            if evt.get("status") in self.STATUS_SUCCESS and evt.get("dedupe_key"):
                # Keep only latest sent timestamp by dedupe key
                try:
                    ts = datetime.fromisoformat(evt["ts"]).timestamp() if evt.get("ts") else now
                except Exception:
                    ts = now
                prev_ts = self.dedupe_cache.get(evt["dedupe_key"])
                self.dedupe_cache[evt["dedupe_key"]] = max(prev_ts or 0.0, ts)

        # Persist repaired/migrated structure only when legacy shape was detected.
        if data.get(SCHEMA_VERSION_FIELD, 1) != self.CURRENT_SCHEMA_VERSION:
            self.save_outbox()

        logger.info(f"Loaded {len(self.outbox)} events from outbox (schema={self.CURRENT_SCHEMA_VERSION}).")

    def _build_payload(self):
        return {
            SCHEMA_VERSION_FIELD: self.CURRENT_SCHEMA_VERSION,
            "events": self.outbox,
            "updated_at": time.time(),
        }

    def save_outbox(self):
        """Atomically saves outbox to disk."""
        try:
            safe_json_dump(self._build_payload(), self.file_path, schema_version=self.CURRENT_SCHEMA_VERSION)
        except Exception as e:
            logger.error(f"Failed to save outbox: {e}")

    def emit_event(
        self,
        event_type: str,
        exchange: str,
        title: str,
        message: str,
        severity: str = "INFO",
        dedupe_key: Optional[str] = None,
        cooldown_min: int = 0,
    ):
        """
        Standard API to enqueue an event.
        Types: SYSTEM, WATCH, TRADE, RISK, SUMMARY
        """
        now_ts = time.time()
        if dedupe_key and cooldown_min > 0:
            last_ts = self.dedupe_cache.get(dedupe_key)
            if last_ts:
                elapsed_min = (now_ts - last_ts) / 60.0
                if elapsed_min < cooldown_min:
                    logger.info(
                        f"Outbox dedupe skip: {dedupe_key} (Elapsed: {elapsed_min:.1f}m < {cooldown_min}m)"
                    )
                    return

        event = {
            "id": f"{int(now_ts * 1000)}_{exchange}_{event_type}",
            "ts": datetime.now().isoformat(),
            "event_type": event_type,
            "exchange": exchange,
            "severity": severity,
            "title": f"[{exchange}] [{event_type}] {title}",
            "message": message,
            "dedupe_key": dedupe_key,
            "status": self.STATUS_REQUESTED,
            "retry_count": 0,
            "next_retry_ts": now_ts,
            "last_error": None,
        }

        self.outbox.append(event)
        self.save_outbox()
        self.process_outbox()

    def check_health(self):
        """
        STAGE 10: Monitor Outbox Jam & Output Heartbeat logic
        Should be called periodically by Controller.
        """
        requested = [m for m in self.outbox if m.get("status") in {self.STATUS_REQUESTED, self.STATUS_ACCEPTED}]
        if len(requested) > 50:
            logger.warning(f"[Notifier] Outbox JAMMED! {len(requested)} pending messages.")

    def send_heartbeat(self, summary=""):
        """
        Periodic Heartbeat
        """
        self.emit_event(
            event_type="HEARTBEAT",
            exchange="SYSTEM",
            title="Alive",
            message=f"I am alive. {summary}",
            severity="INFO",
            dedupe_key=f"HB_{datetime.now().strftime('%Y%m%d%H')}",
            cooldown_min=55,
        )

    def process_outbox(self):
        """
        Worker method to process events using requested->accepted->filled/canceled.
        """
        now_ts = time.time()
        dirty = False

        for evt in self.outbox:
            status = evt.get("status")
            if status not in {self.STATUS_REQUESTED, self.STATUS_ACCEPTED}:
                continue

            # Retry wait check (requested/accepted can have backoff)
            if now_ts < evt.get("next_retry_ts", 0):
                continue

            evt["status"] = self.STATUS_ACCEPTED
            dirty = True

            try:
                self._send_telegram(evt["title"], evt["message"])
                evt["status"] = self.STATUS_FILLED
                if evt.get("dedupe_key"):
                    self.dedupe_cache[evt["dedupe_key"]] = now_ts

            except Exception as e:
                evt["retry_count"] = int(evt.get("retry_count", 0)) + 1
                evt["last_error"] = str(e)

                max_retry = 10
                if evt["retry_count"] > max_retry:
                    evt["status"] = self.STATUS_CANCELED
                    backoff = 0
                else:
                    # Exponential-ish backoff, capped at 5m.
                    if evt["retry_count"] == 1:
                        backoff = 10
                    elif evt["retry_count"] == 2:
                        backoff = 30
                    elif evt["retry_count"] == 3:
                        backoff = 60
                    else:
                        backoff = 300
                    evt["status"] = self.STATUS_REQUESTED
                    evt["next_retry_ts"] = now_ts + backoff

                logger.warning(
                    f"Failed to send {evt.get('id')}: {e}. "
                    f"Retry in {backoff if evt['status'] != self.STATUS_CANCELED else 0}s"
                )

        if dirty:
            self.save_outbox()

    def _send_telegram(self, title, msg):
        """Physical send via requests"""
        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram token/chat_id not set. Mocking send.")
            return

        text = f"{title}\n\n{msg}"
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        data = {"chat_id": self.chat_id, "text": text}

        resp = requests.post(url, data=data, timeout=5)
        resp.raise_for_status()
