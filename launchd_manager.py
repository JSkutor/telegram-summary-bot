"""
launchd_manager.py
macOS LaunchAgent 등록/해제 도우미.

사용 예:
  python launchd_manager.py install
  python launchd_manager.py install --run-now
  python launchd_manager.py status
  python launchd_manager.py uninstall
"""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_LABEL = "com.tgbot.summary"
DEFAULT_CHECK_INTERVAL_HOURS = 6


def default_python() -> Path:
    venv_python = PROJECT_DIR / "venv" / "bin" / "python3"
    if venv_python.exists():
        return venv_python
    return Path(sys.executable)


def expand_path(path: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def plist_path(label: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def launchd_domain() -> str:
    return f"gui/{os.getuid()}"


def build_plist(args: argparse.Namespace) -> dict:
    config_path = expand_path(args.config)
    python_path = expand_path(args.python)
    log_dir = expand_path(args.log_dir)

    check_interval_hours = getattr(args, "check_interval_hours", None)
    if check_interval_hours is None:
        interval_days = getattr(args, "interval_days", None)
        check_interval_hours = (
            interval_days * 24 if interval_days is not None else DEFAULT_CHECK_INTERVAL_HOURS
        )
    args.check_interval_hours = check_interval_hours
    interval_seconds = int(check_interval_hours * 60 * 60)

    return {
        "Label": args.label,
        "ProgramArguments": [
            str(python_path),
            str(PROJECT_DIR / "main.py"),
            "--config",
            str(config_path),
        ],
        "WorkingDirectory": str(PROJECT_DIR),
        "StartInterval": interval_seconds,
        "RunAtLoad": bool(args.run_at_load),
        "StandardOutPath": str(log_dir / "tgbot_stdout.log"),
        "StandardErrorPath": str(log_dir / "tgbot_stderr.log"),
    }


def run_launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["launchctl", *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        command = " ".join(["launchctl", *args])
        detail = result.stderr.strip() or result.stdout.strip()
        raise SystemExit(f"[오류] {command}\n{detail}")
    return result


def ensure_install_inputs(args: argparse.Namespace) -> None:
    config_path = expand_path(args.config)
    python_path = expand_path(args.python)
    main_path = PROJECT_DIR / "main.py"

    missing = [
        str(path)
        for path in (config_path, python_path, main_path)
        if not path.exists()
    ]
    if missing:
        raise SystemExit("[오류] 필요한 파일을 찾을 수 없습니다:\n" + "\n".join(missing))


def command_install(args: argparse.Namespace) -> None:
    ensure_install_inputs(args)

    destination = plist_path(args.label)
    destination.parent.mkdir(parents=True, exist_ok=True)
    expand_path(args.log_dir).mkdir(parents=True, exist_ok=True)

    plist_data = build_plist(args)
    with open(destination, "wb") as f:
        plistlib.dump(plist_data, f, sort_keys=False)

    domain = launchd_domain()
    run_launchctl("bootout", domain, str(destination), check=False)
    run_launchctl("bootstrap", domain, str(destination))

    print(f"등록 완료: {args.label}")
    print(f"plist: {destination}")
    print(f"체크 주기: {args.check_interval_hours:g}시간마다")

    if args.run_now:
        run_launchctl("kickstart", "-k", f"{domain}/{args.label}")
        print("즉시 실행 요청 완료")


def command_uninstall(args: argparse.Namespace) -> None:
    destination = plist_path(args.label)
    domain = launchd_domain()

    run_launchctl("bootout", domain, str(destination), check=False)
    if destination.exists() and not args.keep_plist:
        destination.unlink()
        print(f"plist 삭제: {destination}")
    print(f"등록 해제 완료: {args.label}")


def command_status(args: argparse.Namespace) -> None:
    result = run_launchctl(
        "print",
        f"{launchd_domain()}/{args.label}",
        check=False,
    )
    if result.returncode != 0:
        print(f"등록되어 있지 않습니다: {args.label}")
        return
    print(result.stdout.rstrip())


def command_run(args: argparse.Namespace) -> None:
    if args.force:
        config_path = expand_path(args.config)
        python_path = expand_path(args.python)
        subprocess.run(
            [
                str(python_path),
                str(PROJECT_DIR / "main.py"),
                "--config",
                str(config_path),
                "--force",
            ],
            check=False,
            cwd=PROJECT_DIR,
        )
        return

    run_launchctl("kickstart", "-k", f"{launchd_domain()}/{args.label}")
    print(f"즉시 실행 요청 완료: {args.label}")


def command_logs(args: argparse.Namespace) -> None:
    log_dir = expand_path(args.log_dir)
    subprocess.run(
        [
            "tail",
            "-f",
            str(log_dir / "tgbot_stdout.log"),
            str(log_dir / "tgbot_stderr.log"),
        ],
        check=False,
    )


def command_plist(args: argparse.Namespace) -> None:
    plist_data = build_plist(args)
    print(plistlib.dumps(plist_data, sort_keys=False).decode("utf-8"), end="")


def add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--label", default=DEFAULT_LABEL, help="LaunchAgent label")
    parser.add_argument(
        "--log-dir",
        default="~/Library/Logs",
        help="stdout/stderr 로그 디렉터리",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="tg_summary_bot launchd 관리")
    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser("install", help="plist 생성 후 launchd 등록")
    add_common_options(install)
    install.add_argument(
        "--config",
        default=str(PROJECT_DIR / "config.yaml"),
        help="config.yaml 경로",
    )
    install.add_argument(
        "--python",
        default=str(default_python()),
        help="실행할 python3 경로",
    )
    install.add_argument(
        "--check-interval-hours",
        type=float,
        default=None,
        help="launchd가 앱을 깨우는 간격(시간)",
    )
    install.add_argument(
        "--interval-days",
        type=float,
        help="이전 버전 호환 옵션: launchd 체크 간격(일)",
    )
    install.add_argument(
        "--run-at-load",
        action="store_true",
        help="로그인/등록 시 바로 실행",
    )
    install.add_argument(
        "--run-now",
        action="store_true",
        help="등록 직후 한 번 즉시 실행",
    )
    install.set_defaults(func=command_install)

    uninstall = subparsers.add_parser("uninstall", help="launchd 등록 해제")
    add_common_options(uninstall)
    uninstall.add_argument(
        "--keep-plist",
        action="store_true",
        help="등록만 해제하고 plist 파일은 남김",
    )
    uninstall.set_defaults(func=command_uninstall)

    status = subparsers.add_parser("status", help="launchd 상태 출력")
    add_common_options(status)
    status.set_defaults(func=command_status)

    run = subparsers.add_parser("run", help="등록된 작업 즉시 실행")
    add_common_options(run)
    run.add_argument(
        "--force",
        action="store_true",
        help="launchd를 거치지 않고 실행 주기와 관계없이 바로 실행",
    )
    run.add_argument(
        "--config",
        default=str(PROJECT_DIR / "config.yaml"),
        help="config.yaml 경로 (--force에서 사용)",
    )
    run.add_argument(
        "--python",
        default=str(default_python()),
        help="실행할 python3 경로 (--force에서 사용)",
    )
    run.set_defaults(func=command_run)

    logs = subparsers.add_parser("logs", help="stdout/stderr 로그 tail")
    add_common_options(logs)
    logs.set_defaults(func=command_logs)

    plist = subparsers.add_parser("plist", help="생성될 plist를 stdout으로 출력")
    add_common_options(plist)
    plist.add_argument(
        "--config",
        default=str(PROJECT_DIR / "config.yaml"),
        help="config.yaml 경로",
    )
    plist.add_argument(
        "--python",
        default=str(default_python()),
        help="실행할 python3 경로",
    )
    plist.add_argument(
        "--check-interval-hours",
        type=float,
        default=None,
        help="launchd가 앱을 깨우는 간격(시간)",
    )
    plist.add_argument(
        "--interval-days",
        type=float,
        help="이전 버전 호환 옵션: launchd 체크 간격(일)",
    )
    plist.add_argument(
        "--run-at-load",
        action="store_true",
        help="로그인/등록 시 바로 실행",
    )
    plist.set_defaults(func=command_plist)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
