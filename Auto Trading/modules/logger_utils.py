import csv
import os
from datetime import datetime

class CsvLogger:
    def __init__(self, filepath, headers):
        self.filepath = filepath
        self.headers = headers
        self._ensure_file()

    def _ensure_file(self):
        if not os.path.exists(self.filepath):
            # Create dir if needed
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            with open(self.filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=self.headers)
                writer.writeheader()

    def log(self, data_dict):
        """
        Append a row to CSV. Dictionary keys must match headers.
        """
        # Add timestamp if missing and in headers
        if 'timestamp' in self.headers and 'timestamp' not in data_dict:
             data_dict['timestamp'] = datetime.now().isoformat()

        try:
            with open(self.filepath, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=self.headers)
                writer.writerow(data_dict)
        except Exception as e:
            print(f"[LoggerError] Failed to write to {self.filepath}: {e}")

def get_run_id():
    # Simple YYYYMMDD_HHMM run ID
    return datetime.now().strftime("%Y%m%d_%H%M")
