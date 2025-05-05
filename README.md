# Trading212 MCP Server

<div style="color: #856404; background-color: #fff3cd; border-left: 4px solid #ffeeba; padding: 10px;">
⚠️ **Warning**: Putting an AI in charge of your stock broker is inherently risky. Do not use this connector unless you have considered the risks and put appropriate controls in place to manage those risks.

By using this connector you agree to the terms of the MIT license, which includes indemnity from any financial losses resulting from it's use.

You should test the connector using "demo" mode before deploying to your live account.

**Use at your own risk**
</div>

## Overview
The purpose of this MCP tool is to allow you to connect agentic AI to your Trading212 brokerage account. This will allow you to perform actions such as the following:

- Allow an AI to analyse and critique your portfolio
- Get the AI to suggest some stocks and order them on your behalf (due to a restriction in the Trading212 API, orders can only be created in practice mode currently)
- Allow the AI to manage/update a Trading212 investment pie on your behalf
- Allow the AI to create a Trading212 investment pie on your behalf (coming soon)

Due to aggressive API rate limits imposed by the Trading212 API, this tool will attempt to cache API results in-memory (the default TTL is 5 minutes).

If you deploy a local Redis server on port 6379 the tool will use it instead of the in-memory cache.

## Security tips

- If you are hosting the tool server remotely and connecting over the internet, make sure you deploy a reverse proxy with HTTPS, and ideally with Mutual TLS verification.
- You should avoid saving your Trading212 API key in plaintext. Try using an automated secret manager like keyring or 1password
- Always test the connector on the demo account before connecting to your real account

## Components

### Resources
The server exposes some dynamic resources:
- `trading212://equity/portfolio`: My Portfolio - All assets within your trading portfolio
- `trading212://equity/account/info` - My Account Info - Information about your trading account
- `trading212://equity/account/cash` - My Cash - Information about cash available in my trading account
- `trading212://equity/metadata/instruments/all` - Traded instrument information - Information about all instruments (warning: returns a lot of data and will probably overflow the context window)
- `trading212://equity/metadata/instruments/list` - Returns the list of traded instrument tickers
- `trading212://equity/metadata/instruments/{ticker}` - Returns detailed information about a specific ticker


### Prompts
There are currently no prompts

### Tools
The server offers these tools:

#### Order management

- `place_market_order`
   - Place a market order via Trading212
   - Input:
     - `ticker` (string): The ticker of the stock to order
     - `quantity` (float): The amount to buy or sell
   - Returns: Data object from the Trading212 API

- `place_limit_order` (coming soon)
   - Place a limit order via Trading212
   - Input:
     - `ticker` (string): The ticker of the stock to order
     - `quantity` (float): The amount to buy or sell
     - `limit` (float): The price limit
   - Returns: Data object from the Trading212 API

- `place_stop_order` (coming soon)
   - Place a stop order via Trading212
   - Input:
     - `ticker` (string): The ticker of the stock to order
     - `quantity` (float): The amount to buy or sell
     - `stop` (float): The price stop
   - Returns: Data object from the Trading212 API

- `place_stop_limit_order` (coming soon)
   - Place a stop/limit order via Trading212
   - Input:
     - `ticker` (string): The ticker of the stock to order
     - `quantity` (float): The amount to buy or sell
     - `stop` (float): The price stop
     - `limit` (float): The price limit
   - Returns: Data object from the Trading212 API

- `cancel_order` (coming soon)
   - Cancel an order via Trading212
   - Input:
     - `ticker` (string): The ticker of the order
   - Returns: Data object from the Trading212 API

- `update_pie` (coming soon)
   - Create/update a "pie" in Trading212
   - Input: (TBC)
   - Returns: Data object from the Trading212 API

#### Account data

- `get_account_info`
   - Get the account ID and currency
   - Returns: Data about the account

- `get_portfolio`
   - Get the list of equities currently held in the account
   - Returns: Portfolio data

- `get_account_cash`
   - Get the currently available cash in the account
   - Returns: Data about balance

#### Market data

- `get_all_instruments`
   - Get the list of all instruments in the account (warning: returns a lot of data)
   - Returns: Full data about all equities

- `get_instrument_list`
   - Get the list of tickers available in the account
   - Returns: Full list of stock tickers available in this account

- `get_instrument`
   - Get full information about a single traded instrument, by ticker
   - Input:
     - `ticker` (string): The ticker of interest
   - Returns: Full information about the traded instrument

- `search_instruments`
   - Search all instruments by name, using a partial fuzzy search term
   - Input:
     - `search_term` (string): The term to search by (usually a company name)
     - `threshold` (int): Minimum fuzzy search score to appear in results 0-100, default: 70
     - `limit` (int): Maximum number of results to return, default: 15
   - Returns: Full information about matching instruments

## Usage with Claude Desktop

### uv

```bash
# Add the server to your claude_desktop_config.json.
# NOTE: To trade in your real account you will need to change --environment to "live"
"mcpServers": {
  "trading212": {
    "command": "uv",
    "args": [
      "--directory",
      "parent_of_servers_repo/servers/src/mcp_server_trading212",
      "run",
      "--api-key",
      "<KEEP_THIS_A_SECRET>",
      "--environment",
      "demo",
      "mcp-server-trading212"
    ]
  }
}
```

### Docker

```json
# Add the server to your claude_desktop_config.json
"mcpServers": {
  "trading212": {
    "command": "docker",
    "args": [
      "run",
      "todo"
    ]
  }
}
```

## SSE Mode

This tool has SSE (server side events) mode built in to it. This allows you to run the tool as an HTTP service, which can optionally be located on a different server to the AI client. This is useful for debugging and might be helpful if you want to keep your API key away from your AI environment.

### Use with Claude desktop in SSE mode

```bash
# On Tool server:
uv --directory path/to/project run --api-key '<KEEP_THIS_SECRET>' --environment "demo" mcp-server-trading212 --host 127.0.0.1 --port 6677 --sse
```

```json
// Claude Desktop file
"mcpServers": {
  "trading212": {
    "command": "uvx",
    "args": [
      "mcp-proxy",
      "http://127.0.0.1:6677/sse",
    ],
    "env": {
        "API_ACCESS_TOKEN": "my-token"
    }
  }
}
```

If you are connecting to your tool server over an untrusted network (e.g. the internet) then you should host the tool server behind a reverse proxy that implements HTTPS encryption. Mutual TLS would be a good idea as well. Caddy can do all that for you.

## Building

Docker:

```bash
docker build -t mcp/trading212 .
```

## Test with MCP inspector

```bash
uv add "mcp[cli]"
mcp dev src/mcp_server_sqlite/server.py:wrapper  
```

## License

This MCP server is licensed under the MIT License. This means you are free to use, modify, and distribute the software, subject to the terms and conditions of the MIT License. For more details, please see the LICENSE file in the project repository.

By using this connector you agree to the terms of the MIT license, which includes indemnity from any financial losses resulting from it's use.
