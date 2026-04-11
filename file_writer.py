"""
file_writer.py
Obsidian vault (iCloud 경로)에 MD 파일을 저장하는 모듈
"""

import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def write_to_obsidian(
    content: str,
    vault_path: str,
    target_folder: str,
    filename_format: str,
    reference_date: datetime | None = None,
) -> Path:
    """
    MD 파일을 Obsidian vault 폴더에 저장합니다.

    Args:
        content:         저장할 마크다운 텍스트
        vault_path:      Obsidian vault 루트 경로 (~/ 포함 가능)
        target_folder:   vault 내 저장 폴더명 (없으면 자동 생성)
        filename_format: strftime 형식 파일명 (예: "digest_%Y-%m-%d.md")
        reference_date:  파일명 기준 날짜 (기본값: 오늘)

    Returns:
        저장된 파일의 Path 객체
    """
    ref_date = reference_date or datetime.now()

    # ~ 경로 확장
    vault = Path(os.path.expanduser(vault_path))
    folder = vault / target_folder

    folder.mkdir(parents=True, exist_ok=True)

    filename = ref_date.strftime(filename_format)
    file_path = folder / filename

    # 같은 날짜 파일이 이미 있으면 덮어쓰지 않고 _2, _3 접미사
    if file_path.exists():
        stem = file_path.stem
        suffix = file_path.suffix
        counter = 2
        while file_path.exists():
            file_path = folder / f"{stem}_{counter}{suffix}"
            counter += 1

    file_path.write_text(content, encoding="utf-8")
    logger.info(f"파일 저장 완료: {file_path}")
    return file_path
