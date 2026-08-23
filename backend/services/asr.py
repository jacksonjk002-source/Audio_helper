import base64
import logging
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

BAILIAN_ASR_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
)
ASR_MODEL = "qwen3-asr-flash"
ASR_TIMEOUT_SECONDS = 60.0

MIME_BY_SUFFIX = {
    ".webm": "audio/webm",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".m4a": "audio/mp4",
}


class AsrError(Exception):
    """语音识别失败，携带可展示给用户的中文提示。"""

    def __init__(self, user_message: str, log_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.log_message = log_message


def _get_api_key() -> str:
    api_key = (settings.get("BAILIAN_API_KEY") or "").strip()
    if not api_key:
        raise AsrError(
            "语音识别服务未配置，请联系管理员",
            "未在 backend/.env 中配置 BAILIAN_API_KEY",
        )
    return api_key


def _guess_mime_type(filename: str | None, content_type: str | None) -> str:
    if content_type and content_type.startswith("audio/"):
        return content_type.split(";")[0]

    suffix = ""
    if filename:
        suffix = filename.lower()[filename.rfind(".") :] if "." in filename else ""
    return MIME_BY_SUFFIX.get(suffix, "audio/webm")


def _build_audio_data_uri(audio_bytes: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(audio_bytes).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _extract_text(payload: dict[str, Any]) -> str:
    output = payload.get("output")
    if not isinstance(output, dict):
        return ""

    choices = output.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""

    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""

    content = message.get("content")
    if not isinstance(content, list):
        return ""

    texts: list[str] = []
    for item in content:
        if isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())

    return "".join(texts).strip()


async def transcribe_audio(
    audio_bytes: bytes,
    *,
    filename: str | None = None,
    content_type: str | None = None,
) -> str:
    if not audio_bytes:
        raise AsrError(
            "未收到有效音频，请重新录音后再试",
            "ASR 收到空音频内容",
        )

    api_key = _get_api_key()
    mime_type = _guess_mime_type(filename, content_type)
    audio_data_uri = _build_audio_data_uri(audio_bytes, mime_type)

    request_body = {
        "model": ASR_MODEL,
        "input": {
            "messages": [
                {
                    "role": "system",
                    "content": [{"text": ""}],
                },
                {
                    "role": "user",
                    "content": [{"audio": audio_data_uri}],
                },
            ]
        },
        "parameters": {
            "asr_options": {
                "enable_itn": False,
            }
        },
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(trust_env=False, timeout=ASR_TIMEOUT_SECONDS) as client:
            response = await client.post(
                BAILIAN_ASR_URL,
                headers=headers,
                json=request_body,
            )
    except httpx.TimeoutException as exc:
        raise AsrError(
            "语音识别超时，请稍后重试",
            f"调用百炼 ASR 超时: {exc}",
        ) from exc
    except httpx.HTTPError as exc:
        raise AsrError(
            "语音识别服务暂时不可用，请稍后重试",
            f"调用百炼 ASR 网络异常: {exc}",
        ) from exc

    if response.status_code != 200:
        raise AsrError(
            "语音识别失败，请重新录音后再试",
            f"百炼 ASR HTTP 状态异常: {response.status_code}, body={response.text[:500]}",
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise AsrError(
            "语音识别失败，请重新录音后再试",
            f"百炼 ASR 返回非 JSON 响应: {response.text[:500]}",
        ) from exc

    if payload.get("code"):
        raise AsrError(
            "语音识别失败，请重新录音后再试",
            f"百炼 ASR 业务错误: code={payload.get('code')}, message={payload.get('message')}",
        )

    text = _extract_text(payload)
    if not text:
        raise AsrError(
            "未能识别出有效文字，请说清楚一些后再试",
            f"百炼 ASR 返回空文本: {payload}",
        )

    logger.info("语音识别成功，文本长度: %s", len(text))
    return text
