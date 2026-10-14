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





def search_sticker(context):

    """
    根据情绪分析结果寻找猫猫。

    context 示例：

    {
        "emotion":[
            "sad"
        ],

        "intent":[
            "comfort"
        ],

        "keywords":[
            "抱抱",
            "安慰"
        ],

        "intensity":8
    }

    """


    data = load_library()


    stickers = data["stickers"]


    scored_results = []



    emotions = [
        x.lower()
        for x in context.get(
            "emotion",
            []
        )
    ]


    intents = [
        x.lower()
        for x in context.get(
            "intent",
            []
        )
    ]


    keywords = [
        x.lower()
        for x in context.get(
            "keywords",
            []
        )
    ]


    intensity = context.get(
        "intensity",
        0
    )



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


        # ===== 情绪匹配 =====

        item_emotions = [
            x.lower()
            for x in item.get(
                "emotion",
                []
            )
        ]


        for emotion in emotions:

            if emotion in item_emotions:

                score += 5



        # ===== 意图匹配 =====

        item_intents = [
            x.lower()
            for x in item.get(
                "intent",
                []
            )
        ]


        for intent in intents:

            if intent in item_intents:

                score += 5



        # ===== 标签匹配 =====

        for keyword in keywords:


            if keyword in tags:

                score += 3



            if keyword in name:

                score += 4



            if keyword in description:

                score += 1



            for scene in use_when:

                if keyword in scene:

                    score += 2



        # ===== 强度匹配 =====

        priority = item.get(
            "priority",
            5
        )


        if intensity >= 8:

            if priority >= 8:

                score += 2



        if score > 0:

            scored_results.append(
                {
                    "item": item,
                    "score": score
                }
            )



    if not scored_results:


        logger.warning(
            "No sticker found for context: "
            f"{context}"
        )


        return None



    max_score = max(
        x["score"]
        for x in scored_results
    )



    best_candidates = [

        x["item"]

        for x in scored_results

        if x["score"] >= max_score - 2

    ]



    logger.info(
        f"Candidates: "
        f"{[x['name'] for x in best_candidates]}"
    )



    selected = random.choice(
        best_candidates
    )



    logger.info(
        f"Matched sticker: "
        f"{selected['name']} "
        f"(score={max_score})"
    )



    return selected