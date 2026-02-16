import os
import time
import requests
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List

# Reuse Stage 1 utilities for atomic storage
from .utils_json import safe_json_dump, CustomJSONEncoder

# Setup basic logging
logger = logging.getLogger("NotifierTelegram")

class TelegramNotifier:
    def __init__(self, 
                 bot_token: str = None, 
                 chat_id: str = None, 
                 storage_dir: str = "results/outbox",
                 file_name: str = "telegram_outbox.json"):
        
        # Auto-load from Env if not provided
        if not bot_token:
            bot_token = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
        if not chat_id:
            chat_id = os.getenv("TELEGRAM_CHAT_ID")

        self.bot_token = bot_token
        self.chat_id = chat_id
        self.storage_dir = Path(storage_dir)
        self.file_path = self.storage_dir / file_name
        
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory queue: List of event dicts
        self.outbox: List[Dict] = []
        
        # Dedupe cache: {dedupe_key: last_sent_ts (unix)}
        self.dedupe_cache: Dict[str, float] = {}
        
        # Load existing state
        self.load_outbox()

    def load_outbox(self):
        """Loads outbox from JSON file."""
        if self.file_path.exists():
            try:
                import json
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    self.outbox = json.load(f)
                
                # Rebuild dedupe cache from SENT items
                # (Assuming we trust the history for recent dedupe)
                now = time.time()
                for evt in self.outbox:
                    if evt.get('status') == 'SENT' and 'dedupe_key' in evt:
                        # Keep it if it's recent (e.g. within 24 hours) for safety?
                        # Or just rely on memory for runtime. 
                        # Let's populate it.
                        ts = datetime.fromisoformat(evt['ts']).timestamp()
                        self.dedupe_cache[evt['dedupe_key']] = ts
                        
                logger.info(f"Loaded {len(self.outbox)} events from outbox.")
            except Exception as e:
                logger.error(f"Failed to load outbox: {e}")
                self.outbox = []

    def save_outbox(self):
        """Atomically saves outbox to disk."""
        try:
            safe_json_dump(self.outbox, self.file_path)
        except Exception as e:
            logger.error(f"Failed to save outbox: {e}")

    def emit_event(self, 
                   event_type: str, 
                   exchange: str, 
                   title: str, 
                   message: str, 
                   severity: str = "INFO", 
                   dedupe_key: Optional[str] = None, 
                   cooldown_min: int = 0):
        """
        Standard API to enqueue an event.
        Types: SYSTEM, WATCH, TRADE, RISK, SUMMARY
        """
        # 0. Deduplication Check
        now_ts = time.time()
        if dedupe_key and cooldown_min > 0:
            last_ts = self.dedupe_cache.get(dedupe_key)
            if last_ts:
                elapsed_min = (now_ts - last_ts) / 60.0
                if elapsed_min < cooldown_min:
                    logger.info(f"Examples Dedupe Skip: {dedupe_key} (Elapsed: {elapsed_min:.1f}m < {cooldown_min}m)")
                    return # SKIP

        # 1. Build Event Record
        formatted_title = f"[{exchange}] [{event_type}] {title}"
        event = {
            "id": f"{int(now_ts*1000)}_{exchange}_{event_type}", # Simple ID
            "ts": datetime.now().isoformat(),
            "event_type": event_type,
            "exchange": exchange,
            "severity": severity,
            "title": formatted_title,
            "message": message,
            "dedupe_key": dedupe_key,
            "status": "PENDING", # PENDING, SENT, FAILED
            "retry_count": 0,
            "next_retry_ts": now_ts, # Ready immediately
            "last_error": None
        }
        
        # 2. Add to Outbox
        self.outbox.append(event)
        self.save_outbox()
        
        # 3. Optimistic Immediate Send (optional, but good for responsiveness)
        # We process the whole outbox to respect order/priority
        self.process_outbox()

    def check_health(self):
        """
        STAGE 10: Monitor Outbox Jam & Output Heartbeat logic
        Should be called periodically by Controller.
        """
        # 1. JAM Check
        pending = [m for m in self.outbox if m['status'] == 'PENDING']
        if len(pending) > 50:
            logger.warning(f"[Notifier] Outbox JAMMED! {len(pending)} pending messages.")
            # We don't use emit_event here to avoid recursive jamming, just log or print.

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
            dedupe_key=f"HB_{datetime.now().strftime('%Y%m%d%H')}", # Once per hour max if logic fails updates
            cooldown_min=55 
        )

    def process_outbox(self):
        """
        Worker method to process PENDING events.
        Should be called periodically or after emit.
        """
        now_ts = time.time()
        dirty = False
        
        for evt in self.outbox:
            if evt['status'] != 'PENDING':
                continue
                
            # Check Retry Timing
            if now_ts < evt['next_retry_ts']:
                continue
                
            # Try Send
            try:
                self._send_telegram(evt['title'], evt['message'])
                
                # Success
                evt['status'] = 'SENT'
                if evt.get('dedupe_key'):
                    self.dedupe_cache[evt['dedupe_key']] = now_ts
                dirty = True
                
            except Exception as e:
                # Failure -> Backoff
                evt['retry_count'] += 1
                evt['last_error'] = str(e)
                
                # Max Retries? Let's keep trying forever or cap it?
                # User said "일정 횟수 초과 시 FAILED"
                if evt['retry_count'] > 10:
                     evt['status'] = 'FAILED'
                else:
                    # Exponential Backoff: 10, 30, 60, 120...
                    # User: 10s/30s/60s/5m...
                    if evt['retry_count'] == 1: backoff = 10
                    elif evt['retry_count'] == 2: backoff = 30
                    elif evt['retry_count'] == 3: backoff = 60
                    else: backoff = 300 # Cap at 5m
                    
                    evt['next_retry_ts'] = now_ts + backoff
                
                dirty = True
                logger.warning(f"Failed to send {evt['id']}: {e}. Retry in {backoff if evt['status']=='PENDING' else 0}s")

        if dirty:
            self.save_outbox()

    def _send_telegram(self, title, msg):
        """Physical send via requests"""
        if not self.bot_token or not self.chat_id:
            # Mock mode or unconfigured
            logger.warning("Telegram token/chat_id not set. Mocking send.")
            return

        text = f"{title}\n\n{msg}"
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        data = {"chat_id": self.chat_id, "text": text}
        
        resp = requests.post(url, data=data, timeout=5) # 5s timeout
        resp.raise_for_status()

