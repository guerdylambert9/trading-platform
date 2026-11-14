# Alpaca in Claude Desktop

These configs connect Claude Desktop to your Alpaca account through the official [Alpaca MCP server](https://github.com/alpacahq/alpaca-mcp-server), so you can ask about positions, orders and market data in a chat. They need [uv](https://docs.astral.sh/uv/) installed, because `uvx` starts the server.

| File | Keys | What Claude can do |
|---|---|---|
| `claude_desktop_config.paper.json` | Paper | Everything, including placing paper orders |
| `claude_desktop_config.live-readonly.json` | Live | Read the account, assets, prices and news. The `trading` toolset is left out, so it can't place or cancel orders. |

To use one, copy its `mcpServers` entry into your own `claude_desktop_config.json`, put in your keys, and restart Claude Desktop. The file is in `~/Library/Application Support/Claude/` on a Mac and `%APPDATA%\Claude\` on Windows.

Keep two things in mind:

- The chat is a window, not the trading engine. Orders this app places go through its planner, risk checks and your approval; an order placed from a chat skips all of that. The app treats any position in its universe as its own and may sell it when the signal says so, and the broker check flags positions without a protective stop or outside the universe. Trade from the paper chat freely, but keep the live one read-only.
- Run the MCP server only on your own computer, and never expose it to the internet. Anyone who can reach it can act with your keys.
