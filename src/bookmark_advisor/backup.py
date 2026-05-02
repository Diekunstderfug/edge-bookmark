from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


def create_backup(source_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = backup_dir / f"{source_path.name}_{timestamp}.bak"
    shutil.copy2(source_path, backup_path)
    return backup_path
