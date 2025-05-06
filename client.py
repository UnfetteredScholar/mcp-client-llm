import json
import os
from contextlib import AsyncExitStack
from typing import Optional

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.types import Tool
from openai import OpenAI

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
load_dotenv()


class MCPClient:
    def __init__(self):
        # self.session: Optional[ClientSession] = None
        self.sessions: dict[str, ClientSession] = {}
        self._tool_url: dict[str, str] = {}
        self.exit_stack = AsyncExitStack()
        self.model_client = OpenAI(
            api_key=OPENAI_API_KEY,
        )
        # self.model_client = Anthropic(
        #     base_url="http://localhost:8001", api_key="ollama"
        # )

    # async def connect_to_server(self, server_path: str):
    #     """
    #     Connect to an MCP server

    #     Args:
    #         server_script_path: Path to the server script
    #     """

    #     if ".py" in server_path:
    #         server_params = StdioServerParameters(
    #             command="python",
    #             args=[server_path],
    #             env=None,
    #         )

    #         stdio_transport = await self.exit_stack.enter_async_context(
    #             stdio_client(server_params)
    #         )
    #         self.stdio, self.write = stdio_transport
    #         self.session = await self.exit_stack.enter_async_context(
    #             ClientSession(self.stdio, self.write)
    #         )

    #     else:
    # self._streams_context = sse_client(url=server_path)
    # streams = await self._streams_context.__aenter__()

    # self._session_context = ClientSession(*streams)
    # self.session: ClientSession = (
    #     await self._session_context.__aenter__()
    # )

    # self._streams_context = sse_client(url=server_path)
    #     streams = await self.exit_stack.enter_async_context(
    #         sse_client(url=server_path)
    #     )
    #     self._session_context = ClientSession(*streams)
    #     self.session: ClientSession = (
    #         await self.exit_stack.enter_async_context(
    #             self._session_context
    #         )
    #     )

    # await self.session.initialize()

    # response = await self.session.list_tools()
    # tools = response.tools
    # print(
    #     "\nConnected to server with tools: ", [tool.name for tool in tools]
    # )

    async def connect_to_servers(self, urls: list[str]):
        """
        Connect to multiple MCP servers

        Args:
            urls: list of server urls
        """
        tools = []

        for url in urls:
            # self._streams_context = sse_client(url=server_path)
            streams = await self.exit_stack.enter_async_context(
                sse_client(url=url)
            )
            session_context = ClientSession(*streams)
            session = await self.exit_stack.enter_async_context(
                session_context
            )
            self.sessions[url] = session

            await self.sessions[url].initialize()

            response = await self.sessions[url].list_tools()
            tools.extend(response.tools)

            for tool in response.tools:
                self._tool_url[tool.name] = url
        print(
            f"\nConnected to {len(urls)} server(s) with tools: ",
            [tool.name for tool in tools],
        )

    async def get_tools(self) -> list[Tool]:
        """Gets all tools from the current sessions"""
        tools = []
        for _, session in self.sessions.items():
            response = await session.list_tools()
            tools.extend(response.tools)

        return tools

    def get_session(self, tool_name: str) -> ClientSession:
        url = self._tool_url.get(tool_name)
        if not url:
            raise ValueError("Tool client not found")

        session = self.sessions.get(url)
        if not session:
            raise ValueError("Session not found")

        return session

    async def process_query(self, query: str) -> str:
        """
        Process a query using the LLM and available tools
        """

        messages = [{"role": "user", "content": query}]

        response = await self.get_tools()
        available_tools = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema,
                },
            }
            for tool in response
        ]

        response = self.model_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=available_tools,
            extra_headers={"X-API-KEY": "username"},
        )

        final_text = []

        assistant_message_content = []

        assistant_message = response.choices[0].message
        messages.append(assistant_message)

        if not assistant_message.tool_calls:
            final_text.append(assistant_message.content)
        else:
            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)
                print(tool_name)
                session = self.get_session(tool_name=tool_name)
                result = await session.call_tool(tool_name, tool_args)

                final_text.append(
                    f"\n[Calling tool {tool_name} with args {tool_args}]"
                )

                assistant_message_content.append(assistant_message)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result.content,
                    }
                )

                response = self.model_client.chat.completions.create(
                    model="gpt-4o",
                    messages=messages,
                    tools=available_tools,
                )

                final_text.append(response.choices[0].message.content)

        return "\n".join(final_text)

    async def chat_loop(self):
        """
        Run an interactive chat loop
        """

        print("\nMCP Client Started")
        print("Type your queries or 'quit' to exit.")

        while True:
            try:
                query = input("\nQuery: ").strip()

                if query.lower() == "quit":
                    break

                response = await self.process_query(query)
                print("\n" + response)

            except Exception as e:
                print(f"\nError: {str(e)}")

    async def cleanup(self):
        """
        Clean up resources
        """
        print("Cleanup")
        await self.exit_stack.aclose()
