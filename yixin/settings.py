from __future__ import annotations

from pathlib import Path

from .database import Database


LOCAL_SAVE_ASK = "ask"
LOCAL_SAVE_FIXED = "fixed"
LOCAL_SAVE_REFERENCE = "reference"
LOCAL_SAVE_MODES = (LOCAL_SAVE_ASK, LOCAL_SAVE_FIXED, LOCAL_SAVE_REFERENCE)
LOCAL_SAVE_LABELS = {
    LOCAL_SAVE_ASK: "每次询问",
    LOCAL_SAVE_FIXED: "固定文件夹",
    LOCAL_SAVE_REFERENCE: "AI图文件夹",
}
INPUT_CREATE_REFERENCE = "create_reference"
INPUT_BATCH_GARMENT = "batch_garment"
INPUT_BATCH_PERSON = "batch_person"
INPUT_FOLDER_KEYS = {
    INPUT_CREATE_REFERENCE: "input_last_folder_create_reference",
    INPUT_BATCH_GARMENT: "input_last_folder_batch_garment",
    INPUT_BATCH_PERSON: "input_last_folder_batch_person",
}


class AppSettings:
    MODE_KEY = "local_save_mode"
    FIXED_FOLDER_KEY = "local_save_fixed_folder"
    LAST_FOLDER_KEY = "local_save_last_folder"

    def __init__(self, database: Database) -> None:
        self.database = database

    def local_save_mode(self) -> str:
        mode = self.database.get_setting(self.MODE_KEY, LOCAL_SAVE_ASK)
        return mode if mode in LOCAL_SAVE_MODES else LOCAL_SAVE_ASK

    def set_local_save_mode(self, mode: str) -> None:
        if mode not in LOCAL_SAVE_MODES:
            raise ValueError("不支持的本地保存模式")
        self.database.set_setting(self.MODE_KEY, mode)

    def fixed_folder(self) -> Path | None:
        value = self.database.get_setting(self.FIXED_FOLDER_KEY, "")
        return Path(value) if value else None

    def set_fixed_folder(self, folder: Path | None) -> None:
        self.database.set_setting(
            self.FIXED_FOLDER_KEY, str(folder) if folder is not None else ""
        )

    def last_folder(self) -> Path | None:
        value = self.database.get_setting(self.LAST_FOLDER_KEY, "")
        return Path(value) if value else None

    def set_last_folder(self, folder: Path | None) -> None:
        self.database.set_setting(
            self.LAST_FOLDER_KEY, str(folder) if folder is not None else ""
        )

    def input_folder(self, scope: str) -> Path | None:
        key = INPUT_FOLDER_KEYS.get(scope)
        if key is None:
            raise ValueError("不支持的素材导入位置")
        value = self.database.get_setting(key, "")
        if not value:
            return None
        folder = Path(value)
        if folder.is_dir():
            return folder
        self.database.set_setting(key, "")
        return None

    def set_input_folder(self, scope: str, folder: Path | None) -> None:
        key = INPUT_FOLDER_KEYS.get(scope)
        if key is None:
            raise ValueError("不支持的素材导入位置")
        self.database.set_setting(
            key,
            str(Path(folder).resolve()) if folder is not None else "",
        )
