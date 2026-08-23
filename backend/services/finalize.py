import base64
import logging
from typing import Any
from urllib.parse import quote

import httpx

from config import settings

logger = logging.getLogger(__name__)

DEEPSEEK_CHAT_URL = "https://api.deepseek.com/chat/completions"
BAILIAN_TTS_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
)
REPLY_MODEL = "deepseek-v4-flash"
TTS_MODEL = "qwen3-tts-flash"
TTS_VOICE = "Cherry"
FINALIZE_TIMEOUT_SECONDS = 60.0

REPLY_SYSTEM_PROMPT = """你是「语音约碰面」助手的播报员。请根据用户提供的两人地址、中点坐标和推荐地点列表，生成一段适合语音朗读的中文播报。

要求：
1. 口语自然，像朋友在电话里给建议，长度控制在 40-120 字
2. 必须提到「中间位置附近」或类似表达
3. 优先推荐第 1 家地点，可简要提及另外 1-2 家备选
4. 包含推荐地点名称和地址
5. 只输出播报正文，不要标题、JSON、markdown 或额外解释"""


class FinalizeError(Exception):
    """播报生成失败，携带可展示给用户的中文提示。"""

    def __init__(self, user_message: str, log_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.log_message = log_message


def _get_deepseek_api_key() -> str:
    api_key = (settings.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        raise FinalizeError(
            "播报服务未配置，请联系管理员",
            "未在 backend/.env 中配置 DEEPSEEK_API_KEY",
        )
    return api_key


def _get_bailian_api_key() -> str:
    api_key = (settings.get("BAILIAN_API_KEY") or "").strip()
    if not api_key:
        raise FinalizeError(
            "语音合成服务未配置，请联系管理员",
            "未在 backend/.env 中配置 BAILIAN_API_KEY",
        )
    return api_key


def _build_reply_user_prompt(
    midpoint: dict[str, float],
    pois: list[dict[str, str]],
    *,
    address_a: str | None = None,
    address_b: str | None = None,
    category: str | None = None,
) -> str:
    poi_lines = []
    for index, poi in enumerate(pois, start=1):
        poi_lines.append(f"{index}. {poi['name']}，地址：{poi['address']}")

    parts = [
        f"我的地址：{address_a or '未知'}",
        f"朋友地址：{address_b or '未知'}",
        f"碰面类型：{category or '咖啡店'}",
        f"中点坐标：经度 {midpoint['lng']:.6f}，纬度 {midpoint['lat']:.6f}",
        "推荐地点：",
        *poi_lines,
    ]
    return "\n".join(parts)


def _extract_reply_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""

    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""

    content = message.get("content")
    return content.strip() if isinstance(content, str) else ""


async def _generate_reply_text(
    midpoint: dict[str, float],
    pois: list[dict[str, str]],
    *,
    address_a: str | None = None,
    address_b: str | None = None,
    category: str | None = None,
) -> str:
    if not pois:
        raise FinalizeError(
            "没有可播报的推荐地点，请先完成地点搜索",
            "播报生成收到空 POI 列表",
        )

    api_key = _get_deepseek_api_key()
    user_prompt = _build_reply_user_prompt(
        midpoint,
        pois,
        address_a=address_a,
        address_b=address_b,
        category=category,
    )

    request_body = {
        "model": REPLY_MODEL,
        "messages": [
            {"role": "system", "content": REPLY_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(trust_env=False, timeout=FINALIZE_TIMEOUT_SECONDS) as client:
            response = await client.post(
                DEEPSEEK_CHAT_URL,
                headers=headers,
                json=request_body,
            )
    except httpx.TimeoutException as exc:
        raise FinalizeError(
            "播报话术生成超时，请稍后重试",
            f"DeepSeek 播报话术超时: {exc}",
        ) from exc
    except httpx.HTTPError as exc:
        raise FinalizeError(
            "播报话术生成失败，请稍后重试",
            f"DeepSeek 播报话术网络异常: {exc}",
        ) from exc

    if response.status_code != 200:
        raise FinalizeError(
            "播报话术生成失败，请稍后重试",
            f"DeepSeek 播报 HTTP 异常: {response.status_code}, body={response.text[:500]}",
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise FinalizeError(
            "播报话术生成失败，请稍后重试",
            f"DeepSeek 播报返回非 JSON: {response.text[:500]}",
        ) from exc

    if payload.get("error"):
        raise FinalizeError(
            "播报话术生成失败，请稍后重试",
            f"DeepSeek 播报业务错误: {payload['error']}",
        )

    reply_text = _extract_reply_text(payload)
    if not reply_text:
        raise FinalizeError(
            "播报话术生成失败，请稍后重试",
            f"DeepSeek 播报返回空文本: {payload}",
        )

    logger.info("播报话术生成成功，长度: %s", len(reply_text))
    return reply_text


async def _download_audio_url(client: httpx.AsyncClient, url: str) -> bytes:
    try:
        response = await client.get(url)
    except httpx.HTTPError as exc:
        raise FinalizeError(
            "语音合成失败，请稍后重试",
            f"下载 TTS 音频失败: {exc}",
        ) from exc

    if response.status_code != 200 or not response.content:
        raise FinalizeError(
            "语音合成失败，请稍后重试",
            f"下载 TTS 音频 HTTP 异常: status={response.status_code}",
        )

    return response.content


async def _synthesize_speech(reply_text: str) -> bytes:
    api_key = _get_bailian_api_key()
    request_body = {
        "model": TTS_MODEL,
        "input": {
            "text": reply_text,
            "voice": TTS_VOICE,
            "language_type": "Chinese",
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(trust_env=False, timeout=FINALIZE_TIMEOUT_SECONDS) as client:
            response = await client.post(
                BAILIAN_TTS_URL,
                headers=headers,
                json=request_body,
            )
    except httpx.TimeoutException as exc:
        raise FinalizeError(
            "语音合成超时，请稍后重试",
            f"百炼 TTS 超时: {exc}",
        ) from exc
    except httpx.HTTPError as exc:
        raise FinalizeError(
            "语音合成失败，请稍后重试",
            f"百炼 TTS 网络异常: {exc}",
        ) from exc

    if response.status_code != 200:
        raise FinalizeError(
            "语音合成失败，请稍后重试",
            f"百炼 TTS HTTP 异常: {response.status_code}, body={response.text[:500]}",
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise FinalizeError(
            "语音合成失败，请稍后重试",
            f"百炼 TTS 返回非 JSON: {response.text[:500]}",
        ) from exc

    if payload.get("code"):
        raise FinalizeError(
            "语音合成失败，请稍后重试",
            f"百炼 TTS 业务错误: code={payload.get('code')}, message={payload.get('message')}",
        )

    output = payload.get("output")
    if not isinstance(output, dict):
        raise FinalizeError(
            "语音合成失败，请稍后重试",
            f"百炼 TTS 缺少 output: {payload}",
        )

    audio = output.get("audio")
    if not isinstance(audio, dict):
        raise FinalizeError(
            "语音合成失败，请稍后重试",
            f"百炼 TTS 缺少 audio: {output}",
        )

    audio_data = audio.get("data")
    if isinstance(audio_data, str) and audio_data.strip():
        try:
            audio_bytes = base64.b64decode(audio_data)
        except ValueError as exc:
            raise FinalizeError(
                "语音合成失败，请稍后重试",
                f"百炼 TTS Base64 解码失败: {exc}",
            ) from exc
        logger.info("语音合成成功，音频大小: %s bytes（Base64）", len(audio_bytes))
        return audio_bytes

    audio_url = audio.get("url")
    if isinstance(audio_url, str) and audio_url.strip():
        async with httpx.AsyncClient(trust_env=False, timeout=FINALIZE_TIMEOUT_SECONDS) as client:
            audio_bytes = await _download_audio_url(client, audio_url)
        logger.info("语音合成成功，音频大小: %s bytes（URL 下载）", len(audio_bytes))
        return audio_bytes

    raise FinalizeError(
        "语音合成失败，请稍后重试",
        f"百炼 TTS 未返回音频数据: {audio}",
    )


async def finalize_meeting(
    midpoint: dict[str, float],
    pois: list[dict[str, str]],
    *,
    address_a: str | None = None,
    address_b: str | None = None,
    category: str | None = None,
) -> tuple[str, bytes]:
    reply_text = await _generate_reply_text(
        midpoint,
        pois,
        address_a=address_a,
        address_b=address_b,
        category=category,
    )
    audio_bytes = await _synthesize_speech(reply_text)
    return reply_text, audio_bytes


def encode_reply_text_header(reply_text: str) -> str:
    return quote(reply_text, safe="")
