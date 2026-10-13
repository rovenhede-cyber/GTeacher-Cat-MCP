import requests
import os

from dotenv import load_dotenv

from logger_config import logger


load_dotenv()


_library_cache = None


REPO_RAW = os.getenv(
    "STICKER_REPO_URL"
)


JSON_URL = REPO_RAW + "instructions.json"


def load_library():

    global _library_cache


    if _library_cache is not None:

        logger.info(
            "Using cached sticker library"
        )

        return _library_cache


    response = requests.get(
        JSON_URL
    )

    response.raise_for_status()


    _library_cache = response.json()


    logger.info(
        "Sticker library loaded from GitHub"
    )


    return _library_cache



def search_sticker(keyword):

    data = load_library()

    stickers = data["stickers"]

    result = []


    for item in stickers:

        text = " ".join([
            item.get("name", ""),
            item.get("description", ""),
            " ".join(item.get("tags", [])),
            " ".join(item.get("use_when", []))
        ])


        if keyword in text:

            result.append(item)



    if result:

        result.sort(
            key=lambda x: x.get(
                "priority",
                0
            ),
            reverse=True
        )


        selected = result[0]


        logger.info(
            f"Matched sticker: {selected['name']}"
        )


        return selected



    logger.warning(
        f"No sticker found for keyword: {keyword}"
    )


    return None