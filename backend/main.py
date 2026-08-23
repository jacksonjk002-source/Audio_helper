from datetime import datetime
from pathlib import Path

import aiofiles
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware

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
)


@app.get("/")
def root() -> str:
    return "语音约碰面后端已启动"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/upload")
async def upload_audio(file: UploadFile = File(...)) -> dict[str, str | bool]:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "").suffix or ".webm"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"recording_{timestamp}{suffix}"
    save_path = STORAGE_DIR / filename

    content = await file.read()
    async with aiofiles.open(save_path, "wb") as out_file:
        await out_file.write(content)

    return {"success": True, "filename": filename}
