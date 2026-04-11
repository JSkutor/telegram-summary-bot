"""
telegram_fetcher.py
채널 메시지 수집 모듈 (Telethon 기반)
"""

import logging
from datetime import datetime, timezone
from dataclasses import dataclass

from telethon import TelegramClient
from telethon.tl.types import Message

logger = logging.getLogger(__name__)


@dataclass
class ChannelMessage:
    channel: str
    date: datetime
    text: str
    url: str | None = None


async def fetch_messages(
    api_id: int,
    api_secret: str,
    session_name: str,
    channels: list[str],
    since: datetime,
) -> list[ChannelMessage]:
    """
    지정한 채널들에서 since 이후의 메시지를 수집해 반환합니다.
    최초 실행 시 터미널에서 전화번호 인증이 필요합니다.
    """
    messages: list[ChannelMessage] = []

    async with TelegramClient(session_name, api_id, api_secret) as client:
        for channel in channels:
            logger.info(f"채널 수집 중: {channel}")
            try:
                channel_messages = await _fetch_channel(client, channel, since)
                messages.extend(channel_messages)
                logger.info(f"  → {len(channel_messages)}개 메시지 수집")
            except Exception as e:
                # 채널 하나 실패해도 전체를 멈추지 않음
                logger.warning(f"  → 실패 ({channel}): {e}")

    # 날짜 오름차순 정렬
    messages.sort(key=lambda m: m.date)
    logger.info(f"총 {len(messages)}개 메시지 수집 완료")
    return messages


async def _fetch_channel(
    client: TelegramClient,
    channel: str,
    since: datetime,
) -> list[ChannelMessage]:
    """단일 채널에서 메시지 수집"""
    results = []
    entity = await client.get_entity(channel)

    async for msg in client.iter_messages(entity, offset_date=None, reverse=False):
        if not isinstance(msg, Message):
            continue

        # timezone-aware로 통일
        msg_date = msg.date
        if msg_date.tzinfo is None:
            msg_date = msg_date.replace(tzinfo=timezone.utc)
        since_aware = since if since.tzinfo else since.replace(tzinfo=timezone.utc)

        if msg_date < since_aware:
            break  # iter_messages는 최신순 → 이 시점부터 범위 이전

        text = msg.text or msg.message or ""
        text = text.strip()
        if not text:
            continue

        # 가능하면 메시지 링크 구성
        try:
            username = getattr(entity, "username", None)
            url = f"https://t.me/{username}/{msg.id}" if username else None
        except Exception:
            url = None

        results.append(
            ChannelMessage(
                channel=getattr(entity, "title", channel),
                date=msg_date,
                text=text,
                url=url,
            )
        )

    return results


def format_messages_for_prompt(messages: list[ChannelMessage]) -> str:
    """메시지 리스트를 프롬프트용 텍스트로 변환"""
    if not messages:
        return "(수집된 메시지가 없습니다)"

    lines = []
    current_channel = None

    for msg in messages:
        if msg.channel != current_channel:
            current_channel = msg.channel
            lines.append(f"\n### {current_channel}\n")

        date_str = msg.date.strftime("%Y-%m-%d %H:%M")
        link_str = f" [{msg.url}]" if msg.url else ""
        lines.append(f"[{date_str}]{link_str}\n{msg.text}\n")

    return "\n".join(lines)
