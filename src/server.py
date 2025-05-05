import asyncio
from pydantic import AnyUrl

import click
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.shared.exceptions import McpError
import mcp.server.stdio
import json
import httpx

from .t212 import Trading212API
from .sse_server import SseServerSettings, run_sse_server

MISSING_AUTH_TOKEN_MESSAGE = (
    """Trading212 API Key not found. Please provide an API key with the TRADING212_API_KEY variable."""
)
SERVER_NAME = "trading212"
SERVER_VERSION = "0.1.0"


async def serve(api_key: str, environment: str ="demo", cache_ttl: int = 300) -> Server:
    server = Server(SERVER_NAME)
    api = Trading212API(api_key=api_key, environment=environment, cache_ttl=cache_ttl)

    # I am not sure I understand what prompts are for yet...
    # @server.list_prompts()
    # async def handle_list_prompts() -> list[types.Prompt]:
    #     return [
    #         types.Prompt(
    #             name="sentry-issue",
    #             description="Retrieve a Sentry issue by ID or URL",
    #             arguments=[
    #                 types.PromptArgument(
    #                     name="issue_id_or_url",
    #                     description="Sentry issue ID or URL",
    #                     required=True,
    #                 )
    #             ],
    #         )
    #     ]

    # @server.get_prompt()
    # async def handle_get_prompt(
    #     name: str, arguments: dict[str, str] | None
    # ) -> types.GetPromptResult:
    #     if name != "sentry-issue":
    #         raise ValueError(f"Unknown prompt: {name}")

    #     issue_id_or_url = (arguments or {}).get("issue_id_or_url", "")
    #     issue_data = await handle_sentry_issue(http_client, auth_token, issue_id_or_url)
    #     return issue_data.to_prompt_result()

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return [
            # These are tools
            types.Tool(
                name="create_order",
                description="""Create a working order in the Trading212 brokerage account. Use this tool when you need to:
                - Buy or sell stocks, ETFs and other traded securities
                - Buy or sell at current market value (by providing ticker and quantity only)
                - Submit a stop order (by submitting a ticker, quantity and stopPrice)
                - Submit a limit order (by submitting a ticker, quantity and limitPrice)
                - Submit a stop/limit order (by submitting a ticker, quantity, stopPrice and limitPrice)
                - timeValidity can be specified for all orders, except a market value order.""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "ticker": {
                            "type": "string",
                            "description": "Ticker of security to be traded"
                        },
                        "quantity": {
                            "type": "float",
                            "description": "Quantity of security to be traded"
                        },
                        "stopPrice": {
                            "type": "float",
                            "description": "Lower price limit below which the order is activated. If a stop and limit price are provided, a stop/limit order is created."
                        },
                        "limitPrice": {
                            "type": "float",
                            "description": "Upper price limit above which the order is activated. If a stop and limit price are provided, a stop/limit order is created."
                        },
                        "timeValidity": {
                            "type": "string",
                            "enum": ["DAY", "GOOD_TIL_CANCEL"],
                            "description": "Specifies how long the order is valid for. Can be DAY or GOOD_TIL_CANCEL."
                        }
                    },
                    "required": ["ticker", "quantity"]
                }
            ),
            types.Tool(
                name="search_instruments",
                description="""Search all instruments in the brokerage account using partial matching and fuzzy search. Use this tool if you need to:
                - Locate the ticker of a stock, ETF or other traded security
                - Verify whether a named security is available to trade in this account""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "search_term": {
                            "type": "string",
                            "description": "The term to perform the search by (for example, human readable name)"
                        },
                        "threshold": {
                            "type": "int",
                            "description": "The minimum levenshtein score for a search result to be shown, between 0 (lowest) to 100 (highest). Default: 70.",
                            "default": 70
                        },
                        "limit": {
                            "type": "int",
                            "description": "The maximum number of results to include in the output. Default: 15.",
                            "default": 15
                        }
                    },
                    "required": ["search_term"]
                }
            ),
            types.Tool(
                name="update_pie",
                description="""Update the details of a single pie, including current stock allocations (a pie is simply a group of equities with fixed ratios which can be considered as a self-managed fund). Use this tool when you need to:
                - Update the current stock allocations in the pie
                - Verify whether dividends are reinvesting or extracted
                - Force the pie to rebalance holdings now
                - Update other information about the pie""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "integer",
                            "description": "ID of the pie"
                        },
                        "name": {
                            "type": "string",
                            "description": "Name of the pie"
                        },
                        "dividendCashAction": {
                            "type": "string",
                            "enum": ["REINVEST", "TO_ACCOUNT_CASH"],
                            "description": "Specifies what to do with dividend payments from pie constituents."
                        },
                        "instrumentShares": {
                            "type": "object",
                            "description": "A dictionary mapping stock tickers (keys) to percentage allocation (values). All values in the allocation must sum to 1.00 and have no more than 2 decimal places.",
                            "minProperties": 1,
                            "propertyNames": {
                                "type": "string",
                                "minLength": 1
                            },
                            "additionalProperties": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1
                            }
                        },
                    },
                    "required": ["id"]
                }
            ),


            # Strictly speaking, these ones should be resources, but resource support isn't great currently...
            types.Tool(
                name="get_portfolio",
                description="""Get current portfolio from the Trading212 brokerage account. Use this tool when you need to:
                - List currently owned stocks, ETFs and securities in the Trading212 brokerage account
                - Check current profit / loss on active positions
                - Check currently held position values
                - Re-examine current position""",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            ),
            types.Tool(
                name="get_account_info",
                description="""Get basic details of the brokerage account. Use this tool when you need to:
                - Check the account ID
                - Check the account currency""",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            ),
            types.Tool(
                name="get_account_cash",
                description="""Get the currently available cash balance of the account. Use this tool when you need to:
                - Check how much cash is available on the account balance for orders""",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            ),
            types.Tool(
                name="get_all_instruments",
                description="""Get the full details of all instruments which can be traded in the brokerage account. Use this tool when you want to:
                - Scan all available securities / tickers to cross-check a human readable name or some other detail.
                Warning: This tool will return a lot of data and can overflow the context window.
                You may get better results using the get_instrument_list and get_instrument tools together in place of this one.
                This endpoint will return these details for all tickers:
                - Equity type (usually stock, etf, or other) - field: "type"
                - Currency of security - field: "currencyCode"
                - Name of security - field: "name"
                - Short name of security - field "shortName"
                - Date added to exchange - field "addedOn"
                - Minimum trade quantity - field "minTradeQuantity"
                - Maximum open quantity - field "maxOpenQuantity"
                """,
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            ),
            types.Tool(
                name="get_instrument_list",
                description="""Get a list of tickers for all instruments which can be traded in the brokerage account. Use this tool when you want to:
                - Get a list of all tickers for securities which can be traded in this account.""",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            ),
            types.Tool(
                name="get_instrument",
                description="""Get the full details of a specific instrument which can be traded in the brokerage account, by the stock ticker.
                Use this tool when you want to look up details of a traded security, by ticker. The details available are:
                - Equity type (usually stock, etf, or other) - field: "type"
                - Currency of security - field: "currencyCode"
                - Name of security - field: "name"
                - Short name of security - field "shortName"
                - Date added to exchange - field "addedOn"
                - Minimum trade quantity - field "minTradeQuantity"
                - Maximum open quantity - field "maxOpenQuantity"
                """,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "ticker": {
                            "type": "string",
                            "description": "Ticker of security to be looked up"
                        },
                    },
                    "required": ["ticker"]
                }
            ),
            types.Tool(
                name="get_pies",
                description="""Get the list of all investment "pies" in this account (a pie is simply a group of equities with fixed ratios which can be considered as a self-managed fund). Use this tool when you need to:
                - List all pies in the account
                Use the "get_pie_details" tool to get detailed information about the pie, by ID.""",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            ),
            types.Tool(
                name="get_pie_details",
                description="""Gets detailed information about a single pie, including current stock allocations (a pie is simply a group of equities with fixed ratios which can be considered as a self-managed fund). Use this tool when you need to:
                - Check the current stock allocations in the pie
                - Verify whether dividends are reinvesting or extracted
                - Check the pie cash balance
                - See other information about the pie""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "integer",
                            "description": "ID of the pie"
                        },
                    },
                    "required": ["id"]
                }
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict | None
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        try:
            if name == "create_order":
                if not arguments or "ticker" not in arguments:
                    raise ValueError("Missing ticker argument")
                if "stopPrice" in arguments:
                    if "limitPrice" in arguments:
                        data = await api.create_stop_limit_order(**arguments)
                    else:
                        data = await api.create_stop_order(**arguments)
                elif "limitPrice" in arguments:
                    data = await api.create_limit_order(**arguments)
                else:
                    data = await api.create_market_order(**arguments)
            elif name == "update_pie":
                if not arguments or "id" not in arguments:
                    raise ValueError("Missing id")
                data = api.update_pie(**arguments)

            # These ones should be resources...
            elif name == "get_pies":
                data = api.get_pies()
            elif name == "get_pie_details":
                if not arguments or "id" not in arguments:
                    raise ValueError("Missing id")
                data = api.get_pie_details(**arguments)

            elif name == "get_portfolio":
                data = api.get_portfolio()
            elif name == "get_account_info":
                data = api.get_account_info()
            elif name == "get_account_cash":
                data = api.get_account_balance()
            elif name == "get_all_instruments":
                # This returns a lot of data...
                data = api.get_equity_info()
            elif name == "get_instrument_list":
                data = api.list_equities()
            elif name == "get_instrument":
                if not arguments or "ticker" not in arguments:
                    raise ValueError("Missing ticker argument")
                data = api.get_equity_info(**arguments)
            elif name == "search_instruments":
                if not arguments or "search_term" not in arguments:
                    raise ValueError("Missing search_term")
                data = api.search_instruments(**arguments)
                # This particular one will display better as a list
                data = list(data.values())
            else:
                raise ValueError(f"Unknown tool: {name}")

            if isinstance(data, list):
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(item, default=str),
                    ) for item in data
                ]
            else:
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(data, default=str),
                    )
                ]
        except httpx.HTTPError as e:
            # print(f"Could not fetch detailed information for {symbol}: {e}")
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({
                        "status_code": e.response.status_code,
                        "reason": str(e),
                        "body": e.response.text
                    }, default=str),
                )
            ]

    # return server
    @server.list_resources()
    async def list_resources() -> list[types.ResourceTemplate | types.Resource]:
        return [
            # These should all be done as tools as well, since resources don't have great support.
            types.Resource(
                uri=AnyUrl("trading212://equity/portfolio"),
                name="My Portfolio",
                description="All assets within my trading portfolio",
                mimeType="application/json"
            ),
            types.Resource(
                uri=AnyUrl("trading212://equity/account/info"),
                name="My Account Info",
                description="Information about my trading account",
                mimeType="application/json"
            ),
            types.Resource(
                uri=AnyUrl("trading212://equity/account/cash"),
                name="My Cash",
                description="Information about cash available in my trading account",
                mimeType="application/json"
            ),
            types.Resource(
                uri=AnyUrl("trading212://equity/metadata/instruments/all"),
                name="Traded instrument information",
                description="Information about all instruments (warning: returns a lot of data)",
                mimeType="application/json"
            ),
            types.Resource(
                uri=AnyUrl("trading212://equity/metadata/instruments/list"),
                name="Traded instrument information",
                description="Returns the list of traded instrument tickers",
                mimeType="application/json"
            ),
            types.ResourceTemplate(
                uriTemplate="trading212://equity/metadata/instruments/{ticker}",
                name="Traded instrument information",
                description="Information about a single traded instrument",
                mimeType="application/json"
            ),
        ]

    @server.read_resource()
    async def handle_read_resource(uri: AnyUrl = AnyUrl("trading212://equity/portfolio")) -> str:
        if uri.scheme != "trading212":
            # logger.error(f"Unsupported URI scheme: {uri.scheme}")
            raise ValueError(f"Unsupported URI scheme: {uri.scheme}")

        path = str(uri).replace("trading212://", "/")
        if path == "/equity/portfolio":
            data = api.get_portfolio()
        elif path == "/equity/account/info":
            data = api.get_account_info()
        elif path == "/equity/account/cash":
            data = api.get_account_balance()
        elif path == "/equity/metadata/instruments/all":
            # This returns a lot of data...
            data = api.get_equity_info()
        elif path == "/equity/metadata/instruments/list":
            data = api.list_equities()
        elif path.startswith("/equity/metadata/instruments/"):
            ticker = path.removeprefix("/equity/metadata/instruments/")
            data = api.get_equity_info(ticker)
        else:
            raise ValueError(f"Unsupported resource URI: {uri}")
        return json.dumps(data, indent=2, default=str)

    return server

@click.command()
@click.option(
    "--api-key",
    envvar="TRADING212_API_KEY",
    required=True,
    help="Trading212 API Key",
)
@click.option(
    "--environment",
    envvar="TRADING212_ENVIRONMENT",
    required=False,
    help="Trading212 Environment ('demo' or 'live')",
    default="demo",
)
@click.option(
    "--cache-ttl",
    envvar="TRADING212_CACHE_TTL",
    required=False,
    type=int,
    help="Internal cache TTL (seconds), default: 300",
    default=300,
)
@click.option(
    "--sse/--no-sse",
    envvar="TRADING212_SSE",
    required=False,
    type=bool,
    help="Server Side Events mode. If set, will run as a server on port / host ...",
    default=False,
)
@click.option(
    "--host",
    envvar="TRADING212_HOST",
    required=False,
    type=str,
    help="Hosts to open to. Hint: Use 0.0.0.0 to allow from everywhere. Default: 127.0.0.1",
    default="127.0.0.1",
)
@click.option(
    "--port",
    envvar="TRADING212_PORT",
    required=False,
    type=int,
    help="Port to open. Default: 6677",
    default=6677,
)
def main(api_key: str, environment: str = "demo", cache_ttl: int = 300, sse=False, host="127.0.0.1", port=6677):
    async def _run():
        # STDIN/STDOUT mode
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            server = await serve(api_key=api_key, environment=environment, cache_ttl=cache_ttl)
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name=SERVER_NAME,
                    server_version=SERVER_VERSION,
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )
    async def _run_sse():
        server = await serve(api_key=api_key, environment=environment, cache_ttl=cache_ttl)
        await run_sse_server(
            mcp_server=server,
            sse_settings=SseServerSettings(
                bind_host=host,
                port=port,
                log_level="DEBUG"
            )
        )

    if sse:
        asyncio.run(_run_sse())
    else:
        asyncio.run(_run())
