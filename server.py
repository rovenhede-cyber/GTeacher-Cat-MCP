import base64
import requests

from mcp.server import MCPServer
from mcp.types import ImageContent, TextContent

from sticker_engine import search_sticker


mcp = MCPServer(
    "GTeacher Cat"
)


@mcp.tool()
def get_cat_sticker(context: str):
    """
    根据关键词寻找最匹配猫猫表情，并返回原始图片
    """

    result = search_sticker(context)

    if result is None:
        return {
            "message": "没有找到合适猫猫"
        }


    url = (
        "https://raw.githubusercontent.com/"
        "rovenhede-cyber/stickersforGPT/main/"
        + result["file"]
    )


    description = (
        f"猫猫：{result['name']}\n"
        f"描述：{result['description']}\n"
        f"原图：{url}"
    )


    try:

        response = requests.get(
            url,
            timeout=15
        )

        response.raise_for_status()


        ext = result["file"].lower().split(".")[-1]


        mime_type = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "webp": "image/webp",
            "gif": "image/gif"
        }.get(
            ext,
            "image/jpeg"
        )


        image_data = base64.b64encode(
            response.content
        ).decode(
            "utf-8"
        )


        return [
            TextContent(
                type="text",
                text=description
            ),

            ImageContent(
                type="image",
                data=image_data,
                mimeType=mime_type
            )
        ]


    except Exception as e:

        return {
            "message": "图片读取失败",
            "name": result["name"],
            "url": url,
            "error": str(e)
        }



if __name__ == "__main__":

    mcp.run(
        transport="streamable-http"
    )