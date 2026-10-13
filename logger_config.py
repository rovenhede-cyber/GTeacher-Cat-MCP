import logging
import os


os.makedirs(
    "logs",
    exist_ok=True
)


logging.basicConfig(
    filename="logs/gteacher_cat.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8"
)


logger = logging.getLogger(
    "GTeacherCat"
)