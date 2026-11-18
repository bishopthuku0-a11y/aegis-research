AEGIS DAILY VALUATION PATCH

Files:
- simulation_runner.py: repository root
- tests/test_simulation_runner.py: inside the existing tests folder

Purpose:
- Loads the existing paper-only ledger.
- Fetches exact-date daily closes for every current holding.
- Rejects partial or wrong-date data without changing the ledger.
- Updates the daily valuation snapshot atomically.
- Re-running the same date replaces that day's snapshot (idempotent).
- Rejects valuations before portfolio start or earlier than the latest saved snapshot.

This component does NOT place orders, call Gemini, or connect to a broker.

Run locally from the repository root:
  python -m unittest discover -s tests -v

Run manually after a ledger exists and after the selected market date has closed:
  python simulation_runner.py --date YYYY-MM-DD

Do not run this until the initial portfolio ledger has been created and the
selected market date is known to have completed for all held instruments.
