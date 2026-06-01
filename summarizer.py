"""
summarizer.py
Gemini API를 이용한 요약 모듈
"""

import logging
import time
from datetime import datetime

from google import genai

logger = logging.getLogger(__name__)


RETRYABLE_MARKERS = ("429", "500", "502", "503", "504", "UNAVAILABLE", "RESOURCE_EXHAUSTED")


def is_retryable_error(error: Exception) -> bool:
    message = str(error).upper()
    return any(marker in message for marker in RETRYABLE_MARKERS)


def summarize(
    api_key: str,
    model_name: str,
    prompt_template: str,
    messages_text: str,
    date_from: datetime,
    date_to: datetime,
    max_retries: int = 5,
    retry_initial_seconds: float = 60,
    retry_max_seconds: float = 900,
) -> str:
    """
    메시지 텍스트를 Gemini에 보내 요약된 마크다운 문서를 반환합니다.
    """
    client = genai.Client(api_key=api_key)

    prompt = prompt_template.format(
        days=str((date_to - date_from).days),
        date_from=date_from.strftime("%Y-%m-%d"),
        date_to=date_to.strftime("%Y-%m-%d"),
        messages=messages_text,
    )

    logger.info(f"Gemini 요약 요청 (모델: {model_name}, 입력 길이: {len(prompt)}자)")

    wait_seconds = retry_initial_seconds

    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            result = (response.text or "").strip()
            if not result:
                raise RuntimeError("Gemini 응답이 비어 있습니다.")
            logger.info(f"요약 완료 (출력 길이: {len(result)}자)")
            return result

        except Exception as e:
            if is_retryable_error(e) and attempt < max_retries:
                logger.warning(
                    "Gemini 일시 오류 - "
                    f"{wait_seconds:g}초 후 재시도 ({attempt}/{max_retries}): {e}"
                )
                time.sleep(wait_seconds)
                wait_seconds = min(wait_seconds * 2, retry_max_seconds)
            else:
                raise

    raise RuntimeError("Gemini 요약 재시도 횟수를 모두 소진했습니다.")


def build_md_document(
    summary: str,
    date_from: datetime,
    date_to: datetime,
    channels: list[str],
) -> str:
    """
    Gemini 요약 결과에 frontmatter를 붙여 최종 MD 문서를 생성합니다.
    Obsidian에서 바로 열 수 있는 형태입니다.
    """
    now = datetime.now()
    channels_yaml = "\n".join(f'  - "{c}"' for c in channels)

    frontmatter = f"""---
created: {now.strftime("%Y-%m-%d %H:%M")}
period: "{date_from.strftime("%Y-%m-%d")} ~ {date_to.strftime("%Y-%m-%d")}"
sources:
{channels_yaml}
tags:
  - briefings
---

"""
    return frontmatter + summary
