# 텔레그램 AI 요약 봇

텔레그램 채널을 3일마다 자동으로 긁어와 Gemini로 요약하고,
iCloud Obsidian vault에 MD 파일로 저장하는 봇입니다.

---

## 설치

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. config.yaml 수정
cp config.yaml config.yaml  # 이미 있음
# 아래 항목들을 채워넣으세요
```

---

## 설정 (config.yaml)

### Telegram API 키 발급

1. https://my.telegram.org 접속 → Log in
2. API development tools → 앱 생성
3. `api_id`, `api_hash` 복사 → config.yaml에 입력

### Gemini API 키 발급

1. https://aistudio.google.com 접속
2. "Get API key" → 키 생성
3. config.yaml `gemini.api_key`에 입력

### Obsidian vault 경로 확인

iCloud에 Obsidian vault가 있는 경우 기본 경로:

```
~/Library/Mobile Documents/iCloud~md~obsidian/Documents/{vault이름}
```

터미널에서 확인:

```bash
ls ~/Library/Mobile\ Documents/iCloud~md~obsidian/Documents/
```

---

## 첫 실행 (인증)

텔레그램은 처음 한 번 수동 실행으로 전화번호 인증이 필요합니다.

```bash
cd /path/to/tg_summary_bot
python main.py --dry-run
# 전화번호 입력 → SMS 코드 입력 → 인증 완료
# 세션 파일(tg_summary_session.session)이 생성되면 이후 자동 실행됨
```

---

## launchd 등록 (자동 실행)

```bash
# 1. plist 파일 안의 경로 수정 (YOUR_USERNAME → 실제 유저명)
# ProgramArguments의 python3 경로와 main.py 경로
# StandardOutPath, StandardErrorPath

# python3 경로 확인
which python3

# 2. LaunchAgents 폴더에 복사
cp com.tgbot.summary.plist ~/Library/LaunchAgents/

# 3. 등록
launchctl load ~/Library/LaunchAgents/com.tgbot.summary.plist

# 4. 상태 확인
launchctl list | grep tgbot
```

### 유용한 launchd 명령어

```bash
# 지금 당장 실행
launchctl start com.tgbot.summary

# 로그 확인
tail -f ~/Library/Logs/tgbot_stdout.log
tail -f ~/Library/Logs/tgbot_stderr.log

# 등록 해제 (자동 실행 중지)
launchctl unload ~/Library/LaunchAgents/com.tgbot.summary.plist
```

---

## 파일 구조

```
tg_summary_bot/
├── main.py              # 진입점
├── telegram_fetcher.py  # 메시지 수집
├── summarizer.py        # Gemini 요약
├── file_writer.py       # Obsidian 저장
├── config.yaml          # 설정 (API 키 등)
├── requirements.txt
└── com.tgbot.summary.plist  # launchd 설정
```
