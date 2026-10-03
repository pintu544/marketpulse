# Product feedback — Amazon / AWS tools used in MarketPulse

## Amazon Bedrock (Converse API, Nova Micro, us-east-1)

**What we used it for:** every LLM call in MarketPulse — spoken insights on
all 8 MCP tools, free-form analyst answers, and brief generation — via the
Converse API with the `alexa-bedrock-agent` IAM user (least-privilege
`bedrock:InvokeModel` policy).

**What worked:** the Converse API's unified message format is genuinely
pleasant; inference-profile IDs (`us.amazon.nova-micro-v1:0`) just work;
Nova Micro is fast and cheap enough to narrate every tool call.

**What could be better:**
- The new-account verification blackout (~2h, API-error-only signal) and the
  Anthropic use-case-details form (no deep link from the error) both cost us
  real debugging time. A console banner + error deep-links would fix both.
- `bedrock:InvokeModel` covering Converse is correct but non-obvious; the
  docs bury it. A one-line note on the Converse page would help.

**Rating:** 4/5 — powerful and simple once past onboarding.

## Model Context Protocol (Python SDK v2, Streamable HTTP)

**What we used it for:** the entire Alexa+ integration surface — 8 tools over
Streamable HTTP per spec 2025-11-25, consumed by our simulated Alexa+ host.

**What worked:** `MCPServer` + `mcp.run(transport="streamable-http",
stateless_http=True, json_response=True)` was a 10-line compliant server;
stateless mode is ideal for hackathon judging (no session bookkeeping).

**What could be better:**
- The v1→v2 `FastMCP`→`MCPServer` rename breaks every older tutorial with an
  import error rather than a deprecation warning; search still surfaces v1.
- Bare-`dict` tool returns silently publish no `outputSchema` — a startup
  warning would save builders from shipping schema-less tools.

**Rating:** 4.5/5 — the happy path is excellent.

## Alexa+ (simulated experience path)

We used the explicitly allowed simulation path (the MCP Toolkit is
partner-gated). The `web/` host demonstrates the full voice-question →
MCP-tool → spoken-answer loop. For future hackathons, a public sandbox tier
of the toolkit would let builders demo on real Alexa+ hardware.
