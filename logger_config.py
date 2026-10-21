import logging
import os

# 日志路径可用环境变量覆盖；测试时指向临时文件，避免污染仓库里的 logs/gteacher_cat.log
LOG_PATH = os.getenv("GTEACHER_LOG", "logs/gteacher_cat.log")
LOG_DIR = os.path.dirname(LOG_PATH)

if LOG_DIR:
    os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    filename=LOG_PATH,
    level=os.getenv("GTEACHER_LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8",
)

logger = logging.getLogger("GTeacherCat")
