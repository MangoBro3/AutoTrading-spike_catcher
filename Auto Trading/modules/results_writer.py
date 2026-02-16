import os
import csv
from datetime import datetime
from pathlib import Path
from .utils_json import safe_json_dump

class ResultsWriter:
    def __init__(self, base_dir="results"):
        self.base_dir = Path(base_dir)
        self.runs_dir = self.base_dir / "runs"
        self.index_dir = self.base_dir / "index"
        self.index_file = self.index_dir / "runs_index.csv"
        
        # Ensure base structure
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)

    def create_run_dir(self, run_type, exchange, tag):
        """
        Creates a strict run directory.
        Format: YYYYMMDD_HHMMSS_{run_type}_{exchange}_{tag}
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_tag = "".join(c if c.isalnum() else "_" for c in tag)
        run_id = f"{ts}_{run_type}_{exchange}_{safe_tag}"
        
        run_path = self.runs_dir / run_id
        run_path.mkdir(parents=True, exist_ok=True)
        
        return run_id, run_path

    def write_summary(self, run_id, summary_data):
        """
        Writes run_summary.json using atomic save.
        Validates minimial schema.
        """
        # Schema Enforcement / Injection
        summary_data['_schema_ver'] = "1.0"
        summary_data['run_id'] = run_id
        if 'created_at' not in summary_data:
            summary_data['created_at'] = datetime.now().isoformat()
            
        if 'files' not in summary_data:
            summary_data['files'] = {}

        run_path = self.runs_dir / run_id
        # Safety: ensure dir exists (create_run_dir usually called before, but safe check)
        run_path.mkdir(parents=True, exist_ok=True)
        
        file_path = run_path / "run_summary.json"
        safe_json_dump(summary_data, file_path)
        
        return file_path

    def update_index(self, summary_data):
        """
        Appends a row to results/index/runs_index.csv
        """
        # Flatten basic metrics for CSV
        metrics = summary_data.get('metrics', {})
        
        row = {
            'run_id': summary_data.get('run_id'),
            'created_at': summary_data.get('created_at'),
            'run_type': summary_data.get('run_type'),
            'exchange': summary_data.get('exchange'),
            'market': summary_data.get('market', "KRW"),
            'timeframe': summary_data.get('timeframe', "1d"), # Default if missing
            'tag': summary_data.get('tag', ""),
            'roi_pct': metrics.get('total_return', 0),
            'max_drawdown_pct': metrics.get('max_dd', 0),
            'win_rate_pct': metrics.get('win_rate', 0),
            'trades': metrics.get('trades', 0),
            'summary_path': str(self.runs_dir / summary_data.get('run_id', "") / "run_summary.json"),
            'params_path': str(summary_data.get('files', {}).get('params_json', ""))
        }
        
        fieldnames = [
            'run_id', 'created_at', 'run_type', 'exchange', 'market', 
            'timeframe', 'tag', 'roi_pct', 'max_drawdown_pct', 
            'win_rate_pct', 'trades', 'summary_path', 'params_path'
        ]
        
        file_exists = self.index_file.exists()
        
        try:
            with open(self.index_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row)
        except Exception as e:
            print(f"[ResultsWriter] Failed to update index: {e}")
