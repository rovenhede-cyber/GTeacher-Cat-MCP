import requests
import os
import random

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
        JSON_URL,
        timeout=15
    )

    response.raise_for_status()


    _library_cache = response.json()


    logger.info(
        "Sticker library loaded from GitHub"
    )


    return _library_cache



def search_sticker(keyword):

    """
    根据关键词匹配猫猫。
    
    采用评分机制：
    名称匹配 > 标签匹配 > 使用场景 > 描述
    
    同分结果随机选择，避免固定返回同一张图。
    """


    data = load_library()

    stickers = data["stickers"]


    scored_results = []


    keyword = keyword.lower()


    for item in stickers:


        score = 0


        name = item.get(
            "name",
            ""
        ).lower()


        description = item.get(
            "description",
            ""
        ).lower()


        tags = [
            x.lower()
            for x in item.get(
                "tags",
                []
            )
        ]


        use_when = [
            x.lower()
            for x in item.get(
                "use_when",
                []
            )
        ]


        # 名称精准匹配
        if keyword in name:

            score += 5


        # 标签匹配
        if keyword in tags:

            score += 4


        # 使用场景匹配
        if keyword in use_when:

            score += 3


        # 描述匹配
        if keyword in description:

            score += 1



        if score > 0:

            scored_results.append(
                {
                    "item": item,
                    "score": score
                }
            )



    if not scored_results:

        logger.warning(
            f"No sticker found for keyword: {keyword}"
        )

        return None



    # 找最高分

    max_score = max(
        x["score"]
        for x in scored_results
    )


    best_candidates = [
        x["item"]
        for x in scored_results
        if x["score"] == max_score
    ]



    # 同等级随机选择

    selected = random.choice(
        best_candidates
    )


    logger.info(
        f"Matched sticker: {selected['name']} "
        f"(score={max_score})"
    )


    return selected