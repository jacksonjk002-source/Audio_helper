from fastapi import FastAPI

app = FastAPI(title="语音约碰面后端")


@app.get("/")
def root() -> str:
    return "语音约碰面后端已启动"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
