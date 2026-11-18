AEGIS RESEARCH — FIRST DAILY AGENT PATCH

Files:
  daily_agent.py                 Complete replacement daily research agent
  tests/test_daily_agent.py      11 focused unit tests

Verified in this build:
  - Python compilation passes.
  - 11/11 unit tests pass.
  - Stale or missing portfolio price data stops the AI call.
  - A data failure writes a DATA FAILURE briefing and leaves memory.json unchanged.
  - News retrieval failure does not invalidate an otherwise valid price snapshot.
  - AI output must contain valid action/ticker fields; proposed tickers need a validated price quote.
  - Research calls are explicitly marked research_call_not_execution.
  - Existing memory.json keys and legacy entry_price field are retained for compatibility.

Important limitations not yet solved:
  - yfinance data is a third-party feed, not an exchange-grade feed.
  - Headlines are metadata only; full article text and independent source verification are not implemented.
  - The existing dashboard still needs updating so it does not present research-call price movement as executed portfolio P&L.
  - This is not yet the $10,000 simulation ledger or the full portfolio accounting engine.

Run tests in GitHub Actions or a local environment with Python:
  python -m unittest discover -s tests -v

The runtime workflow still needs google-genai and yfinance installed, as before.
Do not merge this patch into main until it is tested on aegis-simulation-rebuild.
