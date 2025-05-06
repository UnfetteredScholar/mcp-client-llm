import asyncio

from client import MCPClient


async def main():
    new_client = MCPClient()

    try:
        await new_client.connect_to_servers(
            ["http://localhost:8200/sse", "http://localhost:8300/sse"]
        )

        response = await new_client.process_query(
            "What is my current location?"
        )

        print(response)
    finally:
        await new_client.cleanup()


asyncio.run(main())
