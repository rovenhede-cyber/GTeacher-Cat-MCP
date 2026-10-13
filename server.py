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
         f"猫猫名称：{result['name']}\n"
         f"描述：{result['description']}\n\n"
         f"![cat]({url})"
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


        return TextContent(
             type="text",
             text=description
        )


    except Exception as e:

        return {
            "message": "图片读取失败",
            "name": result["name"],
            "url": url,
            "error": str(e)
        }



import uvicorn
from mcp.server.transport_security import TransportSecuritySettings


security = TransportSecuritySettings(
    allowed_hosts=[
        "seas-telescope-vaccine-affecting.trycloudflare.com",
        "localhost",
        "127.0.0.1"
    ],
    allowed_origins=[
        "https://seas-telescope-vaccine-affecting.trycloudflare.com"
    ]
)


app = mcp.streamable_http_app(
    transport_security=security,
    host="0.0.0.0"
)


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000
    )

