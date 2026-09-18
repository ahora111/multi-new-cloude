import logging
import os

def get_logger(name="app"):
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        ))
        logger.addHandler(handler)
        logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))
    return logger
