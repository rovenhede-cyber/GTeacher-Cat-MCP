import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():

    async with streamable_http_client(
        "http://127.0.0.1:8000/mcp"
    ) as (read, write):

        async with ClientSession(read, write) as session:

            await session.initialize()

            print("可用工具：")

            tools = await session.list_tools()

            for tool in tools.tools:
                print("-", tool.name)


            print("\n调用猫猫工具中...")

            result = await session.call_tool(
                "get_cat_sticker",
                {
                    "context": "开心"
                }
            )

            print("\n猫猫返回：")
            print(result)


if __name__ == "__main__":

    asyncio.run(main())