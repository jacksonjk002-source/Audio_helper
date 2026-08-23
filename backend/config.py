from pathlib import Path

from dotenv import dotenv_values

_ENV_PATH = Path(__file__).resolve().parent / ".env"

# 仅从 backend/.env 读取，不合并系统环境变量
settings: dict[str, str | None] = dotenv_values(_ENV_PATH)
