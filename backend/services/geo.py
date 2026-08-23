import logging
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

AMAP_BASE_URL = "https://restapi.amap.com"
GEOCODE_PATH = "/v3/geocode/geo"
PLACE_AROUND_PATH = "/v3/place/around"
AMAP_SUCCESS_STATUS = "1"
GEO_TIMEOUT_SECONDS = 15.0
POI_RADIUS_METERS = 3000
POI_LIMIT = 3


class GeoError(Exception):
    """地图搜索失败，携带可展示给用户的中文提示。"""

    def __init__(self, user_message: str, log_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.log_message = log_message


def _get_api_key() -> str:
    api_key = (settings.get("AMAP_API_KEY") or "").strip()
    if not api_key:
        raise GeoError(
            "地图服务未配置，请联系管理员",
            "未在 backend/.env 中配置 AMAP_API_KEY",
        )
    return api_key


def _parse_location(location: str) -> tuple[float, float]:
    lng_str, lat_str = location.split(",", maxsplit=1)
    return float(lng_str), float(lat_str)


def _ensure_amap_success(
    payload: dict[str, Any],
    *,
    action: str,
    address: str | None = None,
) -> None:
    status = str(payload.get("status", ""))
    if status == AMAP_SUCCESS_STATUS:
        return

    info = payload.get("info", "未知错误")
    if address:
        log_message = f"高德 API 调用失败：{action}，地址「{address}」，status={status}，info={info}"
    else:
        log_message = f"高德 API 调用失败：{action}，status={status}，info={info}"

    raise GeoError("地图服务暂时不可用，请稍后重试", log_message)


async def _amap_get(path: str, params: dict[str, str | int]) -> dict[str, Any]:
    api_key = _get_api_key()
    query = {"key": api_key, **params}

    try:
        async with httpx.AsyncClient(trust_env=False, timeout=GEO_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{AMAP_BASE_URL}{path}", params=query)
    except httpx.TimeoutException as exc:
        raise GeoError(
            "地图服务请求超时，请稍后重试",
            f"高德 API 网络超时：{path}，params={params}",
        ) from exc
    except httpx.HTTPError as exc:
        raise GeoError(
            "地图服务请求失败，请检查网络后重试",
            f"高德 API 网络异常：{path}，error={exc}",
        ) from exc

    if response.status_code != 200:
        raise GeoError(
            "地图服务暂时不可用，请稍后重试",
            f"高德 API HTTP 状态异常：{path}，status_code={response.status_code}，body={response.text[:500]}",
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise GeoError(
            "地图服务暂时不可用，请稍后重试",
            f"高德 API 返回非 JSON：{path}，body={response.text[:500]}",
        ) from exc

    if not isinstance(payload, dict):
        raise GeoError(
            "地图服务暂时不可用，请稍后重试",
            f"高德 API 返回格式异常：{path}，payload={payload}",
        )

    return payload


async def _geocode_address(address: str, label: str) -> tuple[float, float]:
    trimmed = address.strip()
    if not trimmed:
        raise GeoError(
            f"{label}为空，请重新说明位置",
            f"地理编码收到空地址：{label}",
        )

    payload = await _amap_get(GEOCODE_PATH, {"address": trimmed})
    _ensure_amap_success(payload, action=f"地理编码 {label}", address=trimmed)

    count = int(str(payload.get("count", "0")))
    geocodes = payload.get("geocodes")
    if count == 0 or not isinstance(geocodes, list) or not geocodes:
        log_message = (
            f"地理编码未命中：{label}「{trimmed}」count=0，"
            f"info={payload.get('info', '')}"
        )
        if label == "address_a":
            user_message = f"您的地址「{trimmed}」没识别出来，换个说法再说说"
        else:
            user_message = f"朋友的地址「{trimmed}」没识别出来，换个说法再说说"
        raise GeoError(user_message, log_message)

    first = geocodes[0]
    if not isinstance(first, dict):
        raise GeoError(
            "有一个地址没识别出来，换个说法再说说",
            f"地理编码结果格式异常：{label}「{trimmed}」，geocodes={geocodes}",
        )

    location = first.get("location")
    if not isinstance(location, str) or "," not in location:
        raise GeoError(
            "有一个地址没识别出来，换个说法再说说",
            f"地理编码缺少坐标：{label}「{trimmed}」，geocode={first}",
        )

    lng, lat = _parse_location(location)
    logger.info("地理编码成功：%s「%s」-> (%s, %s)", label, trimmed, lng, lat)
    return lng, lat


def _calculate_midpoint(
    lng_a: float,
    lat_a: float,
    lng_b: float,
    lat_b: float,
) -> tuple[float, float]:
    return (lng_a + lng_b) / 2, (lat_a + lat_b) / 2


async def _search_nearby_pois(
    lng: float,
    lat: float,
    category: str,
) -> list[dict[str, str]]:
    keyword = category.strip() or "咖啡店"
    location = f"{lng},{lat}"

    payload = await _amap_get(
        PLACE_AROUND_PATH,
        {
            "location": location,
            "keywords": keyword,
            "radius": POI_RADIUS_METERS,
            "sortrule": "distance",
            "offset": POI_LIMIT,
            "page": 1,
        },
    )
    _ensure_amap_success(payload, action=f"周边搜索 category={keyword}", address=location)

    pois_raw = payload.get("pois")
    if not isinstance(pois_raw, list) or not pois_raw:
        raise GeoError(
            f"这附近找不到合适的{keyword}，请换个类型或地址试试",
            f"中点周边 POI 为空：category={keyword}，location={location}，count={payload.get('count', 0)}",
        )

    pois: list[dict[str, str]] = []
    for item in pois_raw[:POI_LIMIT]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        address = str(item.get("address", "")).strip()
        if name:
            pois.append({"name": name, "address": address or "地址暂无"})

    if not pois:
        raise GeoError(
            f"这附近找不到合适的{keyword}，请换个类型或地址试试",
            f"中点周边 POI 解析后为空：category={keyword}，location={location}，raw={pois_raw[:3]}",
        )

    logger.info("周边搜索成功：category=%s，返回 %s 条", keyword, len(pois))
    return pois


async def search_meeting_places(
    address_a: str,
    address_b: str,
    category: str,
) -> dict[str, Any]:
    lng_a, lat_a = await _geocode_address(address_a, "address_a")
    lng_b, lat_b = await _geocode_address(address_b, "address_b")

    mid_lng, mid_lat = _calculate_midpoint(lng_a, lat_a, lng_b, lat_b)
    logger.info("中点坐标：(%s, %s)", mid_lng, mid_lat)

    pois = await _search_nearby_pois(mid_lng, mid_lat, category)

    return {
        "midpoint": {"lng": mid_lng, "lat": mid_lat},
        "pois": pois,
    }
