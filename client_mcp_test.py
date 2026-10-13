import asyncio

from mcp import ClientSession
from mcp.client.stdio import (
    stdio_client,
    StdioServerParameters
)


async def main():

    server_params = StdioServerParameters(
        command="python",
        args=["server.py"]
    )

    async with stdio_client(server_params) as (read, write):

        async with ClientSession(read, write) as session:

            await session.initialize()

            result = await session.call_tool(
                "get_cat_sticker",
                {
                    "context": "今天实验终于成功了，我好开心"
                }
            )

            print("猫猫返回：")
            print(result)


asyncio.run(main())