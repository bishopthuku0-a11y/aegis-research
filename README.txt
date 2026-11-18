AEGIS MARKET DATA PATCH

Files:
- market_data.py (repository root)
- tests/test_market_data.py (inside existing tests/ directory)

Purpose:
- Fetch the exact requested daily closing bar using yfinance.
- Preserve the exchange timezone timestamp attached to the daily bar.
- Record the retrieval time separately.
- Reject missing dates, timezone-naive bars, invalid prices, and provider errors.
- Fetch a symbol batch atomically: if any requested ticker fails, no partial
  quote dictionary is returned.

This patch does not initialize the $10,000 portfolio or change the daily agent.
It only supplies a date-specific quote adapter. Yahoo Finance data availability
and accuracy are not guaranteed; Aegis must still treat provider failures as
DATA FAILURE and must not substitute a different date.

The tests use synthetic local fixtures only. They do not contact Yahoo Finance.

Run:
  python -m unittest discover -s tests -v

Required runtime dependency: yfinance (already installed by the current
Aegis Daily Run workflow). pandas is installed as a yfinance dependency.
