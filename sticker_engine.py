import requests
import os

from dotenv import load_dotenv

load_dotenv()


_cache = None


REPO_RAW = os.getenv(
    "STICKER_REPO_URL"
)

JSON_URL = REPO_RAW + "instructions.json"


_library_cache = None


def load_library():

    global _library_cache

    if _library_cache is None:

        response = requests.get(JSON_URL)

        response.raise_for_status()

        _library_cache = response.json()

    return _library_cache



def calculate_score(context, item):

    score = 0

    context = context.lower()


    fields = {
        "name": 5,
        "tags": 4,
        "use_when": 3,
        "description": 1
    }


    for field, weight in fields.items():

        value = item.get(field, "")


        if isinstance(value, list):

            value = " ".join(value)


        if value.lower() in context:

            score += weight


        for word in value.split():

            if word and word.lower() in context:

                score += weight


    score += item.get(
        "priority",
        0
    ) * 0.2


    return score



def search_sticker(context):

    data = load_library()

    stickers = data["stickers"]


    results = []


    for item in stickers:

        score = calculate_score(
            context,
            item
        )

        if score > 0:

            results.append(
                (
                    score,
                    item
                )
            )


    if results:

        results.sort(
            key=lambda x:x[0],
            reverse=True
        )

        return results[0][1]


    return None