def should_send_sticker(context):

    intents = context.get(
        "intent",
        []
    )

    intensity = context.get(
        "intensity",
        0
    )


    if "comfort" in intents:
        return True


    if "celebrate" in intents:
        return True


    if "affection" in intents:
        return True


    if intensity >= 8:
        return True


    return False