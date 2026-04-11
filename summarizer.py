"""
summarizer.py
Gemini API를 이용한 요약 모듈
"""

import logging
from datetime import datetime

import google.generativeai as genai

logger = logging.getLogger(__name__)


def summarize(
    api_key: str,
    model_name: str,
    prompt_template: str,
    messages_text: str,
    date_from: datetime,
    date_to: datetime,
) -> str:
    """
    메시지 텍스트를 Gemini에 보내 요약된 마크다운 문서를 반환합니다.
    """
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    prompt = prompt_template.format(
        days=str((date_to - date_from).days),
        date_from=date_from.strftime("%Y-%m-%d"),
        date_to=date_to.strftime("%Y-%m-%d"),
        messages=messages_text,
    )

    logger.info(f"Gemini 요약 요청 (모델: {model_name}, 입력 길이: {len(prompt)}자)")

    response = model.generate_content(prompt)
    result = response.text.strip()

    logger.info(f"요약 완료 (출력 길이: {len(result)}자)")
    return result


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
  - digest
  - auto-generated
---

"""
    return frontmatter + summary
