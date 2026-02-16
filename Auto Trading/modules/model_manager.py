import os
import shutil
from datetime import datetime
from pathlib import Path

from .utils_json import safe_json_dump


class ModelManager:
    """
    Registry layout:
      models/_active/
      models/_staging/<run_id>/
      models/_archive/<run_id>/
    """

    ACTIVE_TMP_OLD = "_active_tmp_old"
    ACTIVE_TMP_NEW = "_active_tmp_new"

    def __init__(self, base_dir="models"):
        self.base_dir = Path(base_dir)
        self.active_dir = self.base_dir / "_active"
        self.staging_dir = self.base_dir / "_staging"
        self.archive_dir = self.base_dir / "_archive"
        self._ensure_dirs()
        self.recover_if_needed()

    def _ensure_dirs(self):
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def _tmp_old(self):
        return self.base_dir / self.ACTIVE_TMP_OLD

    def _tmp_new(self):
        return self.base_dir / self.ACTIVE_TMP_NEW

    def _read_model_id(self, model_dir: Path):
        meta_path = model_dir / "model_meta.json"
        if not meta_path.exists():
            return None
        try:
            import json
            return json.loads(meta_path.read_text(encoding="utf-8")).get("model_id")
        except Exception:
            return None

    def _archive_name(self, base_name: str):
        candidate = self.archive_dir / base_name
        if not candidate.exists():
            return candidate
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.archive_dir / f"{base_name}_{stamp}"

    def recover_if_needed(self):
        """
        Best-effort recovery if crash happened during promotion.
        """
        tmp_old = self._tmp_old()
        tmp_new = self._tmp_new()
        active_exists = self.active_dir.exists()

        if not active_exists and tmp_new.exists():
            os.replace(tmp_new, self.active_dir)
            active_exists = True

        if not active_exists and tmp_old.exists():
            os.replace(tmp_old, self.active_dir)
            active_exists = True

        if active_exists and tmp_old.exists():
            prev_id = self._read_model_id(tmp_old) or f"recovered_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            os.replace(tmp_old, self._archive_name(prev_id))

        if tmp_new.exists():
            abandoned_id = self._read_model_id(tmp_new) or f"abandoned_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            os.replace(tmp_new, self._archive_name(abandoned_id))

    def create_staging(self, run_id: str):
        run_dir = self.staging_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir

    def write_staging_artifacts(self, run_id: str, best_params: dict, run_summary: dict, model_meta: dict):
        run_dir = self.staging_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        safe_json_dump(best_params, run_dir / "best_params.json")
        safe_json_dump(run_summary, run_dir / "run_summary.json")
        safe_json_dump(model_meta, run_dir / "model_meta.json")
        return run_dir

    def archive_staging(self, run_id: str):
        src = self.staging_dir / run_id
        if not src.exists():
            return None
        dst = self._archive_name(run_id)
        os.replace(src, dst)
        return dst

    def promote(self, run_id: str, fail_step: str = None):
        """
        Atomic-ish promotion with crash recovery:
          1) staging/<run_id> -> _active_tmp_new
          2) _active -> _active_tmp_old (if exists)
          3) _active_tmp_new -> _active
          4) _active_tmp_old -> _archive/<prev_id>

        fail_step is test hook:
          - "after_new"
          - "after_old"
        """
        src = self.staging_dir / run_id
        if not src.exists():
            raise FileNotFoundError(f"staging run not found: {src}")

        tmp_new = self._tmp_new()
        tmp_old = self._tmp_old()

        if tmp_new.exists():
            shutil.rmtree(tmp_new, ignore_errors=True)
        if tmp_old.exists():
            shutil.rmtree(tmp_old, ignore_errors=True)

        os.replace(src, tmp_new)
        if fail_step == "after_new":
            raise RuntimeError("Injected failure after moving staging to tmp_new")

        if self.active_dir.exists():
            os.replace(self.active_dir, tmp_old)
        if fail_step == "after_old":
            raise RuntimeError("Injected failure after moving active to tmp_old")

        os.replace(tmp_new, self.active_dir)

        if tmp_old.exists():
            prev_id = self._read_model_id(tmp_old) or f"archived_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            os.replace(tmp_old, self._archive_name(prev_id))

    def load_active_params(self):
        path = self.active_dir / "best_params.json"
        if not path.exists():
            return None
        try:
            import json
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def active_model_id(self):
        if not self.active_dir.exists():
            return None
        return self._read_model_id(self.active_dir)
