# 텔레그램 AI 요약 봇

텔레그램 채널 메시지를 주기적으로 수집해 Gemini로 요약하고, Obsidian vault에 마크다운 파일로 저장하는 macOS용 봇입니다.

## 특징

- Telethon으로 텔레그램 채널 메시지 수집
- Gemini API로 브리핑 마크다운 생성
- Obsidian vault에 파일 저장
- macOS `launchd` 자동 실행 지원
- API 실패 대비 재시도와 상태 파일 기반 누락 방지

## 설치

```bash
git clone https://github.com/JSkutor/telegram-summary-bot.git
cd telegram-summary-bot

python3 -m venv venv
./venv/bin/pip install -r requirements.txt

cp config.yaml.template config.yaml
cp .env.example .env
```

## 설정

민감한 API 키는 `config.yaml`에 직접 쓰지 않고 `.env`에 넣습니다.

```dotenv
TELEGRAM_API_ID=123456
TELEGRAM_API_SECRET=your_telegram_api_hash
GEMINI_API_KEY=your_gemini_api_key
```

`config.yaml`에는 채널 목록과 Obsidian 경로를 설정합니다.

```yaml
telegram:
  channels:
    - "@channel_username"

output:
  obsidian_vault_path: "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/{vault_name}"
```

Telegram API 키는 https://my.telegram.org 의 `API development tools`에서 발급합니다. Gemini API 키는 https://aistudio.google.com 에서 발급합니다.

## 첫 실행

텔레그램은 처음 한 번 전화번호 인증이 필요합니다. 자동 실행 등록 전에 수동으로 인증하세요.

```bash
./venv/bin/python main.py --dry-run
```

인증이 끝나면 `tg_summary_session.session` 파일이 생성됩니다. 이 파일은 개인 세션이므로 GitHub에 올리면 안 됩니다.

## 자주 쓰는 실행 명령

```bash
# 메시지 수집만 테스트
./venv/bin/python main.py --dry-run

# 실행 주기가 되었을 때만 요약
./venv/bin/python main.py

# 실행 주기와 관계없이 바로 요약
./venv/bin/python main.py --force

# plist 생성 및 launchd 등록
./venv/bin/python launchd_manager.py install

# 등록 직후 바로 한 번 실행 요청
./venv/bin/python launchd_manager.py install --run-now

# launchd 상태 확인
./venv/bin/python launchd_manager.py status

# launchd 등록 해제
./venv/bin/python launchd_manager.py uninstall
```

## 자동 실행

`launchd_manager.py`가 현재 프로젝트 경로, venv 파이썬, 로그 경로를 반영한 plist를 생성하고 등록합니다.

```bash
./venv/bin/python launchd_manager.py install
```

기본값은 6시간마다 앱을 깨우는 것입니다. 앱은 내부 상태를 보고 실제 요약 주기인 72시간이 지나지 않았으면 바로 종료합니다. 즉, API 실패가 나도 다음 정규 3일을 기다리지 않고 6시간 뒤 다시 시도합니다.

```bash
# launchd 체크 주기를 3시간으로 변경
./venv/bin/python launchd_manager.py install --check-interval-hours 3

# 등록 직후 launchd job을 한 번 깨움
./venv/bin/python launchd_manager.py install --run-now
```

상태 확인과 관리는 아래 명령을 사용합니다.

```bash
./venv/bin/python launchd_manager.py status
./venv/bin/python launchd_manager.py run
./venv/bin/python launchd_manager.py run --force
./venv/bin/python launchd_manager.py logs
./venv/bin/python launchd_manager.py uninstall
```

## 누락 방지 방식

이 봇은 `config.state.json`에 마지막 성공 시각을 저장합니다. 다음 실행 때는 마지막 성공 시각보다 `runtime.state_overlap_minutes`만큼 앞에서 다시 수집합니다. 기본값은 360분입니다.

Gemini 호출은 기본 5회 재시도합니다. `429`, `500`, `502`, `503`, `504`, `UNAVAILABLE`, `RESOURCE_EXHAUSTED` 계열 오류는 지수 백오프로 다시 시도합니다. 그래도 실패하면 상태 파일의 `last_success_utc`는 갱신하지 않습니다. 그래서 다음 launchd 체크 때 다시 같은 기간을 수집하고 요약을 재시도합니다.

실제 요약 간격은 `config.yaml`의 아래 값으로 조정합니다.

```yaml
runtime:
  digest_interval_hours: 72
  state_overlap_minutes: 360
```

## macOS Sleep

Mac이 잠자기 상태이면 launchd job은 그 순간 실행되지 않습니다. `StartInterval`로 예약된 시간이 잠자는 동안 지나가면, 깨어난 뒤 실행 기회가 한 번 들어옵니다. 잠자는 동안 여러 번의 interval이 지나가도 밀린 횟수만큼 전부 실행되지는 않고 보통 한 번으로 합쳐집니다.

그래서 이 프로젝트는 launchd 체크 주기를 실제 요약 주기보다 짧게 둡니다. Mac이 며칠 동안 잠들어 있었거나 네트워크/API 문제로 실패해도, 깨어난 뒤 다음 체크에서 마지막 성공 시각 기준으로 다시 수집합니다.

## 수동 실행

```bash
# 실행 주기가 되었을 때만 요약
./venv/bin/python main.py

# 실행 주기와 관계없이 바로 요약
./venv/bin/python main.py --force

# 메시지 수집만 테스트
./venv/bin/python main.py --dry-run

# 다른 설정 파일 또는 env 파일 사용
./venv/bin/python main.py --config /path/to/config.yaml --env-file /path/to/.env
```

## GitHub에 올리지 않는 파일

아래 파일은 개인 환경 또는 실행 산출물이라 `.gitignore`에 포함되어 있습니다.

- `config.yaml`
- `.env`
- `*.session`, `*.session-journal`
- `*.state.json`, `*.lock`
- `venv/`
- `*.plist`
- `.DS_Store`

## 파일 구조

```text
tg_summary_bot/
├── main.py                          # 진입점
├── telegram_fetcher.py              # 메시지 수집
├── summarizer.py                    # Gemini 요약
├── file_writer.py                   # Obsidian 저장
├── launchd_manager.py               # launchd 등록/관리 명령
├── config.yaml.template             # 설정 템플릿
├── .env.example                     # 환경변수 템플릿
├── com.tgbot.summary.plist.template # plist 참고 템플릿
└── requirements.txt
```
