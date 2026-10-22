from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .database import Database
from .settings import (
    LOCAL_SAVE_FIXED,
    LOCAL_SAVE_REFERENCE,
    AppSettings,
)
from .storage import atomic_copy_file


INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_prompt_summary(prompt: str, limit: int = 24) -> str:
    summary = INVALID_FILENAME_CHARACTERS.sub("_", prompt.strip())
    summary = re.sub(r"\s+", "_", summary).strip(" ._")
    return (summary[:limit] or "作品").rstrip(" ._")


class LocalImageExporter:
    def __init__(self, database: Database, settings: AppSettings) -> None:
        self.database = database
        self.settings = settings

    def preferred_directory(self, task_id: int) -> Path | None:
        mode = self.settings.local_save_mode()
        if mode == LOCAL_SAVE_FIXED:
            folder = self.settings.fixed_folder()
            return folder if folder and folder.is_dir() else None
        if mode == LOCAL_SAVE_REFERENCE:
            references = self.database.get_task_references(task_id)
            if references:
                source = references[-1].source_path
                if source and source.parent.is_dir():
                    return source.parent
        last_folder = self.settings.last_folder()
        return last_folder if last_folder and last_folder.is_dir() else None

    def save_result(self, task_id: int, result_id: int, directory: Path) -> Path:
        task = self.database.get_task(task_id)
        if task is None:
            raise ValueError("任务不存在")
        results = self.database.get_task_results(task_id)
        result = next((item for item in results if int(item["id"]) == result_id), None)
        if result is None:
            raise ValueError("生成结果不存在")
        source = Path(result["path"])
        if not source.is_file():
            raise ValueError("生成结果文件已不存在")
        directory = directory.expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        if not directory.is_dir():
            raise ValueError("本地保存位置不是有效文件夹")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        summary = safe_prompt_summary(task["prompt"])
        stem = (
            f"{summary}_{timestamp}_任务{task_id}_结果{int(result['position']) + 1}"
        )
        suffix = source.suffix or ".png"
        destination = directory / f"{stem}{suffix}"
        sequence = 2
        while destination.exists():
            destination = directory / f"{stem}_{sequence}{suffix}"
            sequence += 1
        atomic_copy_file(source, destination)
        self.settings.set_last_folder(directory)
        return destination
