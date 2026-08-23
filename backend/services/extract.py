import json
import logging
import re
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

DEEPSEEK_CHAT_URL = "https://api.deepseek.com/chat/completions"
EXTRACT_MODEL = "deepseek-v4-flash"
EXTRACT_TIMEOUT_SECONDS = 60.0
DEFAULT_CATEGORY = "咖啡店"

SYSTEM_PROMPT = """你是一个信息提取助手。用户会用自然语言描述两个人想在哪里碰面、各自的位置以及想做什么。

你的任务：从用户输入中提取三个字段，且只输出一个 JSON 对象，不要输出任何其他文字、解释或 markdown。

输出格式（键名必须完全一致）：
{
  "address_a": "说话者自己的位置/地址",
  "address_b": "朋友的位置/地址",
  "category": "碰面想做什么，如咖啡店、餐厅、商场等"
}

规则：
1. address_a 是「我」所在的位置，address_b 是「朋友」所在的位置
2. 地址尽量简洁准确，保留地标名、地铁站、商圈、城市等关键信息
3. 若用户未说明碰面想做什么，category 必须为「咖啡店」
4. 不要编造用户未提及的信息；无法确定的地址留空字符串
5. 只输出 JSON，不要使用 markdown 代码块"""


class ExtractError(Exception):
    """信息提取失败，携带可展示给用户的中文提示。"""

    def __init__(self, user_message: str, log_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.log_message = log_message


def _get_api_key() -> str:
    api_key = (settings.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        raise ExtractError(
            "信息提取服务未配置，请联系管理员",
            "未在 backend/.env 中配置 DEEPSEEK_API_KEY",
        )
    return api_key


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_extract_payload(raw_content: str) -> dict[str, str]:
    cleaned = _strip_json_fence(raw_content)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ExtractError(
            "未能理解您的描述，请说清楚两个地址后再试",
            f"DeepSeek 返回内容无法解析为 JSON: {raw_content[:500]}",
        ) from exc

    if not isinstance(payload, dict):
        raise ExtractError(
            "未能理解您的描述，请说清楚两个地址后再试",
            f"DeepSeek 返回 JSON 不是对象: {payload}",
        )

    address_a = str(payload.get("address_a", "")).strip()
    address_b = str(payload.get("address_b", "")).strip()
    category = str(payload.get("category", "")).strip() or DEFAULT_CATEGORY

    if not address_a or not address_b:
        raise ExtractError(
            "未能识别出两个地址，请分别说明您和朋友的位置",
            f"DeepSeek 提取结果字段缺失: address_a={address_a!r}, address_b={address_b!r}",
        )

    return {
        "address_a": address_a,
        "address_b": address_b,
        "category": category,
    }


def _extract_message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""

    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""

    content = message.get("content")
    return content.strip() if isinstance(content, str) else ""


async def extract_meeting_info(text: str) -> dict[str, str]:
    user_text = text.strip()
    if not user_text:
        raise ExtractError(
            "没有可提取的文字，请先录音识别后再试",
            "信息提取收到空文本",
        )

    api_key = _get_api_key()
    request_body = {
        "model": EXTRACT_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(trust_env=False, timeout=EXTRACT_TIMEOUT_SECONDS) as client:
            response = await client.post(
                DEEPSEEK_CHAT_URL,
                headers=headers,
                json=request_body,
            )
    except httpx.TimeoutException as exc:
        raise ExtractError(
            "信息提取超时，请稍后重试",
            f"调用 DeepSeek 超时: {exc}",
        ) from exc
    except httpx.HTTPError as exc:
        raise ExtractError(
            "信息提取服务暂时不可用，请稍后重试",
            f"调用 DeepSeek 网络异常: {exc}",
        ) from exc

    if response.status_code != 200:
        raise ExtractError(
            "信息提取失败，请重新描述后再试",
            f"DeepSeek HTTP 状态异常: {response.status_code}, body={response.text[:500]}",
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise ExtractError(
            "信息提取失败，请重新描述后再试",
            f"DeepSeek 返回非 JSON 响应: {response.text[:500]}",
        ) from exc

    if payload.get("error"):
        error_info = payload["error"]
        raise ExtractError(
            "信息提取失败，请重新描述后再试",
            f"DeepSeek 业务错误: {error_info}",
        )

    raw_content = _extract_message_content(payload)
    if not raw_content:
        raise ExtractError(
            "未能理解您的描述，请说清楚两个地址后再试",
            f"DeepSeek 返回空内容: {payload}",
        )

    result = _parse_extract_payload(raw_content)
    logger.info(
        "信息提取成功: address_a=%s, address_b=%s, category=%s",
        result["address_a"],
        result["address_b"],
        result["category"],
    )
    return result
