import base64
import requests

from mcp.server import MCPServer
from mcp.types import TextContent, ImageContent

from sticker_engine import search_sticker
from emotion_engine import analyze_context
from trigger_engine import should_send_sticker


mcp = MCPServer(
    "GTeacher Cat"
)



@mcp.tool()
def send_cat_companion(
       user_emotional_context: str
):

    """
    Use this tool to send a cat companion reaction when the user may benefit from emotional support or celebration.

    Use this tool when the user:
    - expresses sadness, frustration, disappointment, or needs comfort
    - celebrates achievements or shares exciting news
    - expresses gratitude, affection, or wants emotional companionship
    - uses cute or emotional language where a cat reaction improves the conversation

    The tool automatically analyzes the conversation context
    and selects an appropriate cat sticker.

    Do not use this tool for:
    - academic questions
    - technical explanations
    - coding problems
    - factual information requests

    The input should describe the user's recent emotional situation,
    not only a single keyword.
  
    """


    # 1. 情绪分析

    analysis = analyze_context(
        context
    )


    # 2. 判断是否需要猫猫

    if not should_send_sticker(
        analysis
    ):

        return TextContent(
            type="text",
            text="当前场景不需要发送猫猫"
        )


    # 3. 搜索猫猫

    result = search_sticker(
        analysis
    )


    if result is None:

        return TextContent(
            type="text",
            text="没有找到合适猫猫"
        )


    file_path = result.get(
        "file"
    )


    if not file_path:

        return TextContent(
            type="text",
            text="猫猫图片路径缺失"
        )


    # 4. 拼接GitHub图片地址

    url = (
        "https://raw.githubusercontent.com/"
        "rovenhede-cyber/stickersforGPT/main/"
        + file_path
    )


    description = (
        f"猫猫名称：{result['name']}\n"
        f"描述：{result['description']}\n"
        f"图片地址：{url}"
    )


    try:

        response = requests.get(
            url,
            timeout=15
        )

        response.raise_for_status()


        image_data = base64.b64encode(
            response.content
        ).decode(
            "utf-8"
        )


        ext = file_path.lower().split(".")[-1]


        mime_type = {
            "jpg":"image/jpeg",
            "jpeg":"image/jpeg",
            "png":"image/png",
            "webp":"image/webp",
            "gif":"image/gif"
        }.get(
            ext,
            "image/png"
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


        return TextContent(
            type="text",
            text=(
                "猫猫图片读取失败\n"
                f"{str(e)}"
            )
        )



import uvicorn

from mcp.server.transport_security import (
    TransportSecuritySettings
)


security = TransportSecuritySettings(

    allowed_hosts=[
        "cat.hedecat.cc",
        "localhost",
        "127.0.0.1"
    ],

    allowed_origins=[
        "http://cat.hedecat.cc",
        "https://cat.hedecat.cc"
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