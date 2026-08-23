import logging
from datetime import datetime
from pathlib import Path

import aiofiles
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from schemas import ExtractRequest, ExtractResponse, FinalizeRequest, SearchRequest, SearchResponse
from services.asr import AsrError, transcribe_audio
from services.extract import ExtractError, extract_meeting_info
from services.finalize import FinalizeError, encode_reply_text_header, finalize_meeting
from services.geo import GeoError, search_meeting_places
from services.pipeline_log import log_step_fail, log_step_pass, log_step_start

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

STORAGE_DIR = Path(__file__).resolve().parent / "storage"

app = FastAPI(title="语音约碰面后端")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5175",
        "http://127.0.0.1:5175",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Reply-Text"],
)


@app.get("/")
def root() -> str:
    return "语音约碰面后端已启动"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/upload")
async def upload_audio(file: UploadFile = File(...)) -> dict[str, str | bool]:
    log_step_start("上传", "接收前端音频文件")
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "").suffix or ".webm"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"recording_{timestamp}{suffix}"
    save_path = STORAGE_DIR / filename

    content = await file.read()
    if not content:
        log_step_fail("上传", "收到空音频文件")
        raise HTTPException(status_code=400, detail="未收到有效音频，请重新录音")

    async with aiofiles.open(save_path, "wb") as out_file:
        await out_file.write(content)

    log_step_pass("上传", f"文件已保存 {filename}，大小 {len(content)} bytes")
    return {"success": True, "filename": filename}


@app.post("/asr")
async def asr_audio(file: UploadFile = File(...)) -> dict[str, str]:
    log_step_start("语音识别", "调用百炼 ASR 转写音频")
    audio_bytes = await file.read()

    try:
        text = await transcribe_audio(
            audio_bytes,
            filename=file.filename,
            content_type=file.content_type,
        )
    except AsrError as exc:
        log_step_fail("语音识别", exc.log_message)
        raise HTTPException(status_code=502, detail=exc.user_message) from exc

    log_step_pass("语音识别", f"识别文字长度 {len(text)}")
    return {"text": text}


@app.post("/extract", response_model=ExtractResponse)
async def extract_info(body: ExtractRequest) -> ExtractResponse:
    log_step_start("信息提取", "调用 DeepSeek 提取地址与碰面类型")
    try:
        result = await extract_meeting_info(body.text)
    except ExtractError as exc:
        log_step_fail("信息提取", exc.log_message)
        raise HTTPException(status_code=502, detail=exc.user_message) from exc

    log_step_pass(
        "信息提取",
        f"address_a={result['address_a']}，address_b={result['address_b']}，category={result['category']}",
    )
    return ExtractResponse(**result)


@app.post("/search", response_model=SearchResponse)
async def search_places(body: SearchRequest) -> SearchResponse:
    log_step_start(
        "地图搜索",
        f"address_a={body.address_a}，address_b={body.address_b}，category={body.category}",
    )
    try:
        result = await search_meeting_places(
            body.address_a,
            body.address_b,
            body.category,
        )
    except GeoError as exc:
        log_step_fail("地图搜索", exc.log_message)
        raise HTTPException(status_code=502, detail=exc.user_message) from exc

    midpoint = result["midpoint"]
    pois = result["pois"]
    log_step_pass(
        "地图搜索",
        f"中点({midpoint['lng']:.6f}, {midpoint['lat']:.6f})，返回 {len(pois)} 个 POI",
    )
    return SearchResponse(**result)


@app.post("/finalize")
async def finalize_reply(body: FinalizeRequest) -> Response:
    log_step_start("播报生成", f"收到 {len(body.pois)} 个推荐地点，准备生成话术与语音")
    pois = [poi.model_dump() for poi in body.pois]
    midpoint = body.midpoint.model_dump()

    try:
        reply_text, audio_bytes = await finalize_meeting(
            midpoint,
            pois,
            address_a=body.address_a,
            address_b=body.address_b,
            category=body.category,
        )
    except FinalizeError as exc:
        log_step_fail("播报生成", exc.log_message)
        raise HTTPException(status_code=502, detail=exc.user_message) from exc

    log_step_pass("播报生成", f"话术长度 {len(reply_text)}，音频大小 {len(audio_bytes)} bytes")
    return Response(
        content=audio_bytes,
        media_type="audio/wav",
        headers={"X-Reply-Text": encode_reply_text_header(reply_text)},
    )
