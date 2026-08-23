import logging

logger = logging.getLogger("pipeline")


def log_step_pass(step: str, message: str) -> None:
    logger.info("【%s】审核通过：%s", step, message)


def log_step_fail(step: str, message: str) -> None:
    logger.error("【%s】审核失败：%s", step, message)


def log_step_start(step: str, message: str) -> None:
    logger.info("【%s】开始：%s", step, message)
