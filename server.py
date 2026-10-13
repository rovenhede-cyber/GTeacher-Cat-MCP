from mcp.server import MCPServer

from sticker_engine import search_sticker


mcp = MCPServer(
    "GTeacher Cat"
)


@mcp.tool()
def get_cat_sticker(context: str):

    """
    根据关键词寻找最匹配猫猫表情
    """

    result = search_sticker(context)


    if result is None:

        return {
            "message": "没有找到合适猫猫"
        }


    return {

        "id": result["id"],

        "name": result["name"],

        "description":
        result["description"],

        "file":
        result["file"],

        "url":
        "https://raw.githubusercontent.com/"
        "rovenhede-cyber/stickersforGPT/main/"
        +
        result["file"]

    }


if __name__ == "__main__":

    mcp.run()