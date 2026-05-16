"""
main.py
텔레그램 AI 요약 봇 진입점
launchd 또는 터미널에서 직접 실행합니다.

사용법:
  python main.py              # config.yaml 기본 경로
  python main.py --config /path/to/config.yaml
  python main.py --dry-run    # API 호출 없이 메시지 수집만 테스트
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml


# err 에 시간 찍히게
class TimestampedStderr:
    def __init__(self, stream):
        self._stream = stream

    def write(self, msg):
        if msg.strip():  # 빈 줄은 스킵
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._stream.write(f"{ts} [STDERR] {msg}")
        else:
            self._stream.write(msg)

    def flush(self):
        self._stream.flush()


sys.stderr = TimestampedStderr(sys.stderr)


# ── 의존성 체크를 여기서 해서 에러 메시지를 친절하게 ──────────────────────
def _check_dependencies():
    missing = []
    try:
        import telethon  # noqa: F401
    except ImportError:
        missing.append("telethon")
    try:
        import google.genai  # noqa: F401
    except ImportError:
        missing.append("google-genai")
    if missing:
        print(f"[오류] 패키지 설치 필요: pip install {' '.join(missing)}")
        sys.exit(1)


_check_dependencies()

from telegram_fetcher import fetch_messages, format_messages_for_prompt
from summarizer import summarize, build_md_document
from file_writer import write_to_obsidian


# ── 로깅 설정 ──────────────────────────────────────────────────────────────
def setup_logging(level: str, log_file: str | None = None):
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if log_file:
        expanded = os.path.expanduser(log_file)
        Path(expanded).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(expanded, encoding="utf-8"))

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


# ── 설정 로드 ──────────────────────────────────────────────────────────────
def load_config(config_path: str) -> dict:
    path = Path(os.path.expanduser(config_path))
    if not path.exists():
        print(f"[오류] config 파일을 찾을 수 없습니다: {path}")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── 메인 로직 ──────────────────────────────────────────────────────────────
async def run(config: dict, dry_run: bool = False):
    logger = logging.getLogger("main")

    try:
        tg_cfg = config["telegram"]
        gem_cfg = config["gemini"]
        out_cfg = config["output"]

        # 기간 계산
        now = datetime.now(tz=timezone.utc)
        fetch_days = int(tg_cfg.get("fetch_days", 3))
        date_from = now - timedelta(days=fetch_days)

        logger.info(f"수집 기간: {date_from.strftime('%Y-%m-%d %H:%M')} UTC ~ 현재")

        # 1. 텔레그램 메시지 수집
        messages = await fetch_messages(
            api_id=int(tg_cfg["api_id"]),
            api_secret=tg_cfg["api_secret"],
            session_name=tg_cfg.get("session_name", "tg_summary_session"),
            channels=tg_cfg["channels"],
            since=date_from,
        )

        if not messages:
            logger.warning("수집된 메시지가 없습니다. 종료합니다.")
            return

        messages_text = format_messages_for_prompt(messages)

        if dry_run:
            logger.info("[dry-run] 수집된 메시지 미리보기:")
            print(messages_text[:2000])
            print("... (dry-run 모드: 요약 및 파일 저장 생략)")
            return
        # if dry_run:
        #     for m in messages[:7]:
        #         print(f"reactions raw: {m.reactions}")
        #     print(messages_text[:6000])
        #     print("... (dry-run 모드: 요약 및 파일 저장 생략)")
        #     return

        # 2. Gemini 요약
        summary_raw = summarize(
            api_key=gem_cfg["api_key"],
            model_name=gem_cfg.get("model", "gemini-2.0-flash"),
            prompt_template=gem_cfg["prompt_template"],
            messages_text=messages_text,
            date_from=date_from,
            date_to=now,
        )

        # 3. 최종 MD 문서 구성
        channel_names = tg_cfg["channels"]
        md_content = build_md_document(
            summary=summary_raw,
            date_from=date_from,
            date_to=now,
            channels=channel_names,
        )

        # 4. Obsidian vault에 저장
        saved_path = write_to_obsidian(
            content=md_content,
            vault_path=out_cfg["obsidian_vault_path"],
            target_folder=out_cfg.get("target_folder", "Briefings"),
            filename_format=out_cfg.get("filename_format", "digest_%Y-%m-%d.md"),
            reference_date=datetime.now(),
        )

        logger.info(f"완료! 저장 위치: {saved_path}")
    except Exception as e:
        logger.error(f"메인 오류: {e}", exc_info=True)
        sys.exit(1)


# ── CLI ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="텔레그램 채널 AI 요약 봇")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).parent / "config.yaml"),
        help="config 파일 경로 (기본값: ./config.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="메시지 수집만 하고 API 호출/파일 저장 생략",
    )
    args = parser.parse_args()

    config = load_config(args.config)

    log_cfg = config.get("logging", {})
    setup_logging(
        level=log_cfg.get("level", "INFO"),
        log_file=log_cfg.get("file"),
    )

    asyncio.run(run(config, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
