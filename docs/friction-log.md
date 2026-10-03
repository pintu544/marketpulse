# Friction log — MarketPulse build

Honest notes on what slowed us down, for the judges and for future builders.

1. **Bedrock "account being verified" wall.** First `converse` calls returned
   `AccessDeniedException: Your account is currently being verified` for ~2h
   on a long-standing AWS account. No console banner explained it; we only
   learned the state from the API error string. Self-resolved.
2. **Anthropic models need a use-case form.** After verification cleared,
   Claude models returned `ResourceNotFoundException: Model use case details
   have not been submitted for this account`. The fix is a form in the Bedrock
   console, but nothing links you to it from the error. We shipped on Nova
   Micro instead — fine, but the error could deep-link the form.
3. **MCP Python SDK v2 rename.** `FastMCP` → `MCPServer`; old import path is
   gone, not deprecated. Every tutorial from the v1 era crashes on import.
   The "What's new" page documents it, but search results still surface v1 code.
4. **Corporate egress proxies vs. boto3.** Our VM's proxy password contains
   URL-breaking characters; botocore's proxy handling choked while curl
   worked. We built a tiny local CONNECT forwarder that injects
   `Proxy-Authorization`. Worth documenting for enterprise users.
5. **`mcp` client's httpx fork vs. `no_proxy`.** Bracketed IPv6 entries in
   `NO_PROXY` (`[::1]`) crashed URL parsing. Overriding
   `NO_PROXY=localhost,127.0.0.1` fixed it. Minor, but cost 20 minutes.
6. **Dict tool returns → no output schema.** Returning a bare `dict` from an
   `@mcp.tool()` publishes no `outputSchema`. Pydantic models do. The docs
   mention it, but it's easy to miss when scaffolding fast.

What went smoothly: the Streamable HTTP server itself (`stateless_http=True`,
`json_response=True`) worked first try; the ETL from 121MB of CSVs to a
0.1MB SQLite DB took minutes; Bedrock's Converse API is pleasant once
credentials and model access cooperate.
