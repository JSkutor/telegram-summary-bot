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
from contextlib import contextmanager
import fcntl
import json
import logging
import os
import re
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
ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def load_env_file(env_file: str | None) -> None:
    if not env_file:
        return

    path = Path(os.path.expanduser(env_file))
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_env_placeholders(value):
    if isinstance(value, dict):
        return {k: resolve_env_placeholders(v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_env_placeholders(v) for v in value]
    if not isinstance(value, str):
        return value

    missing = []

    def replace(match: re.Match) -> str:
        name = match.group(1)
        env_value = os.environ.get(name)
        if env_value is None:
            missing.append(name)
            return match.group(0)
        return env_value

    resolved = ENV_PATTERN.sub(replace, value)
    if missing:
        names = ", ".join(sorted(set(missing)))
        raise ValueError(f"환경변수가 설정되어 있지 않습니다: {names}")
    return os.path.expanduser(resolved)


def load_config(config_path: str, env_file: str | None = None) -> dict:
    path = Path(os.path.expanduser(config_path))
    if not path.exists():
        print(f"[오류] config 파일을 찾을 수 없습니다: {path}")
        sys.exit(1)

    load_env_file(env_file or str(path.parent / ".env"))

    with open(path, encoding="utf-8") as f:
        try:
            return resolve_env_placeholders(yaml.safe_load(f) or {})
        except ValueError as e:
            print(f"[오류] {e}")
            sys.exit(1)


def parse_utc_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def read_state(state_file: str | None) -> dict:
    if not state_file:
        return {}

    path = Path(os.path.expanduser(state_file))
    if not path.exists():
        return {}

    logger = logging.getLogger("main")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"상태 파일을 읽지 못했습니다. 기본 기간으로 수집합니다: {e}")
        return {}


def write_state(
    state_file: str | None,
    *,
    date_from: datetime,
    date_to: datetime,
    message_count: int,
    output_path: Path | None,
) -> None:
    if not state_file:
        return

    path = Path(os.path.expanduser(state_file))
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "last_success_utc": date_to.astimezone(timezone.utc).isoformat(),
        "last_fetch_from_utc": date_from.astimezone(timezone.utc).isoformat(),
        "last_attempt_utc": date_to.astimezone(timezone.utc).isoformat(),
        "last_message_count": message_count,
        "last_output_path": str(output_path) if output_path else None,
        "last_error": None,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def write_failure_state(
    state_file: str | None,
    *,
    error: Exception,
    now: datetime,
) -> None:
    if not state_file:
        return

    state = read_state(state_file)
    state["last_attempt_utc"] = now.astimezone(timezone.utc).isoformat()
    state["last_failure_utc"] = now.astimezone(timezone.utc).isoformat()
    state["last_error"] = str(error)
    state["updated_at_utc"] = datetime.now(timezone.utc).isoformat()

    path = Path(os.path.expanduser(state_file))
    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def should_run_digest(
    config: dict,
    now: datetime,
    state_file: str | None,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> bool:
    if force or dry_run:
        return True

    logger = logging.getLogger("main")
    runtime_cfg = config.get("runtime", {})
    digest_interval_hours = float(runtime_cfg.get("digest_interval_hours", 72))
    if digest_interval_hours <= 0:
        return True

    state = read_state(state_file)
    last_success = parse_utc_datetime(state.get("last_success_utc"))
    if not last_success:
        return True

    next_run = last_success + timedelta(hours=digest_interval_hours)
    if now >= next_run:
        return True

    logger.info(
        "아직 실행 주기가 되지 않아 종료합니다. "
        f"다음 실행 가능 시각: {next_run.strftime('%Y-%m-%d %H:%M')} UTC"
    )
    return False


def calculate_date_from(config: dict, now: datetime, state_file: str | None) -> datetime:
    logger = logging.getLogger("main")
    tg_cfg = config["telegram"]
    runtime_cfg = config.get("runtime", {})

    fetch_days = int(tg_cfg.get("fetch_days", 3))
    fallback_date_from = now - timedelta(days=fetch_days)

    state = read_state(state_file)
    last_success = parse_utc_datetime(state.get("last_success_utc"))
    if not last_success:
        return fallback_date_from

    if last_success > now:
        logger.warning("상태 파일의 마지막 성공 시각이 미래입니다. 기본 기간으로 수집합니다.")
        return fallback_date_from

    overlap_minutes = int(runtime_cfg.get("state_overlap_minutes", 360))
    date_from = last_success - timedelta(minutes=overlap_minutes)
    logger.info(
        "마지막 성공 시각 기준으로 수집합니다: "
        f"{date_from.strftime('%Y-%m-%d %H:%M')} UTC부터 "
        f"(중복 방지용 여유 {overlap_minutes}분 포함)"
    )
    return date_from


@contextmanager
def single_instance_lock(lock_file: str | None):
    if not lock_file:
        yield True
        return

    path = Path(os.path.expanduser(lock_file))
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return

        f.write(str(os.getpid()))
        f.flush()
        try:
            yield True
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


# ── 메인 로직 ──────────────────────────────────────────────────────────────
async def run(
    config: dict,
    dry_run: bool = False,
    state_file: str | None = None,
    force: bool = False,
):
    logger = logging.getLogger("main")
    now = datetime.now(tz=timezone.utc)

    try:
        tg_cfg = config["telegram"]
        gem_cfg = config["gemini"]
        out_cfg = config["output"]

        if not should_run_digest(
            config,
            now,
            state_file,
            force=force,
            dry_run=dry_run,
        ):
            return

        date_from = calculate_date_from(config, now, state_file)

        logger.info(f"수집 기간: {date_from.strftime('%Y-%m-%d %H:%M')} UTC ~ 현재")

        # 1. 텔레그램 메시지 수집
        messages = await fetch_messages(
            api_id=int(tg_cfg["api_id"]),
            api_secret=tg_cfg["api_secret"],
            session_name=tg_cfg.get("session_name", "tg_summary_session"),
            channels=tg_cfg["channels"],
            since=date_from,
            allow_partial_failures=bool(
                config.get("runtime", {}).get("allow_partial_channel_failures", False)
            ),
        )

        if not messages:
            logger.warning("수집된 메시지가 없습니다. 종료합니다.")
            if not dry_run:
                write_state(
                    state_file,
                    date_from=date_from,
                    date_to=now,
                    message_count=0,
                    output_path=None,
                )
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
            max_retries=int(gem_cfg.get("max_retries", 5)),
            retry_initial_seconds=float(gem_cfg.get("retry_initial_seconds", 60)),
            retry_max_seconds=float(gem_cfg.get("retry_max_seconds", 900)),
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

        write_state(
            state_file,
            date_from=date_from,
            date_to=now,
            message_count=len(messages),
            output_path=saved_path,
        )
        logger.info(f"완료! 저장 위치: {saved_path}")
    except Exception as e:
        write_failure_state(state_file, error=e, now=now)
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
    parser.add_argument(
        "--force",
        action="store_true",
        help="실행 주기와 관계없이 바로 수집/요약",
    )
    parser.add_argument(
        "--env-file",
        help="환경변수를 읽을 .env 파일 경로 (기본값: config 파일 옆 .env)",
    )
    parser.add_argument(
        "--state-file",
        help="마지막 성공 시각을 저장할 JSON 파일 경로 (기본값: config 파일 옆 .state.json)",
    )
    parser.add_argument(
        "--lock-file",
        help="중복 실행 방지용 lock 파일 경로 (기본값: config 파일 옆 .lock)",
    )
    args = parser.parse_args()

    config_path = Path(os.path.expanduser(args.config)).resolve()
    config = load_config(str(config_path), env_file=args.env_file)

    log_cfg = config.get("logging", {})
    setup_logging(
        level=log_cfg.get("level", "INFO"),
        log_file=log_cfg.get("file"),
    )

    runtime_cfg = config.get("runtime", {})
    state_file = (
        args.state_file
        or runtime_cfg.get("state_file")
        or str(config_path.with_suffix(".state.json"))
    )
    lock_file = (
        args.lock_file
        or runtime_cfg.get("lock_file")
        or str(config_path.with_suffix(".lock"))
    )

    logger = logging.getLogger("main")
    with single_instance_lock(lock_file) as locked:
        if not locked:
            logger.warning(f"이미 실행 중입니다. 이번 실행은 건너뜁니다: {lock_file}")
            return
        asyncio.run(
            run(
                config,
                dry_run=args.dry_run,
                state_file=state_file,
                force=args.force,
            )
        )


if __name__ == "__main__":
    main()
