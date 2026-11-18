import json
import unittest

from investment_mandate import (
    ALLOWED_TICKERS,
    MandateViolation,
    normalize_ticker,
    validate_portfolio_weights,
)
from research_decision import (
    DecisionValidationError,
    parse_research_decision,
    validate_decision,
)


VALID_EVIDENCE = [{
    "claim": "The supplied daily close for XLU is dated 2026-11-17.",
    "source": "Aegis verified market snapshot",
    "as_of": "2026-11-17",
    "evidence_type": "market_data",
}]


def valid_payload(**overrides):
    payload = {
        "schema_version": 1,
        "action": "HOLD",
        "ticker": "XLU",
        "reasoning": "The available evidence does not justify changing this position today.",
        "risks": ["The available snapshot does not establish future earnings or valuation."],
        "evidence": VALID_EVIDENCE,
        "confidence": 62.5,
        "missing_information": ["Updated valuation and company-level fundamentals."],
        "proposed_lesson": None,
    }
    payload.update(overrides)
    return payload


class InvestmentMandateTests(unittest.TestCase):
    def test_only_three_tickers_are_eligible(self):
        self.assertEqual(set(ALLOWED_TICKERS), {"XLU", "GRID", "UTES"})
        for ticker in ALLOWED_TICKERS:
            self.assertEqual(normalize_ticker(ticker.lower()), ticker)

    def test_rejects_ticker_outside_mandate(self):
        for ticker in ("MSFT", "NVDA", "AAPL", "", "XLU/GRID"):
            with self.subTest(ticker=ticker):
                with self.assertRaises(MandateViolation):
                    normalize_ticker(ticker)

    def test_accepts_exact_target_weights(self):
        weights = validate_portfolio_weights({"XLU": 0.5, "GRID": 0.3, "UTES": 0.2})
        self.assertEqual(weights, {"XLU": 0.5, "GRID": 0.3, "UTES": 0.2})

    def test_allows_rebalancing_within_the_fixed_three_ticker_universe(self):
        weights = validate_portfolio_weights({"XLU": 0.4, "GRID": 0.4, "UTES": 0.2})
        self.assertEqual(weights, {"XLU": 0.4, "GRID": 0.4, "UTES": 0.2})

    def test_rejects_missing_extra_or_invalid_target_weights(self):
        bad_portfolios = [
            {"XLU": 0.5, "GRID": 0.5},
            {"XLU": 0.5, "GRID": 0.3, "UTES": 0.1, "MSFT": 0.1},
            {"XLU": 0.4, "GRID": 0.4},
        ]
        for portfolio in bad_portfolios:
            with self.subTest(portfolio=portfolio):
                with self.assertRaises(MandateViolation):
                    validate_portfolio_weights(portfolio)


class ResearchDecisionTests(unittest.TestCase):
    def test_accepts_each_allowed_action_and_ticker(self):
        for action in ("BUY", "TRIM", "HOLD"):
            for ticker in ALLOWED_TICKERS:
                with self.subTest(action=action, ticker=ticker):
                    decision = validate_decision(valid_payload(action=action, ticker=ticker))
                    self.assertEqual(decision.action, action)
                    self.assertEqual(decision.ticker, ticker)

    def test_rejects_out_of_mandate_ticker(self):
        with self.assertRaisesRegex(DecisionValidationError, "outside Aegis's investment mandate"):
            validate_decision(valid_payload(action="BUY", ticker="NVDA"))

    def test_no_decision_requires_null_ticker_and_can_have_no_evidence(self):
        payload = valid_payload(action="NO_DECISION", ticker=None, evidence=[])
        decision = validate_decision(payload)
        self.assertEqual(decision.action, "NO_DECISION")
        self.assertIsNone(decision.ticker)
        with self.assertRaisesRegex(DecisionValidationError, "ticker=null"):
            validate_decision(valid_payload(action="NO_DECISION", ticker="GRID", evidence=[]))

    def test_rejects_fallback_or_missing_ticker_for_action(self):
        with self.assertRaises(DecisionValidationError):
            validate_decision(valid_payload(action="BUY", ticker=None))

    def test_rejects_missing_required_evidence_for_trade_recommendation(self):
        with self.assertRaisesRegex(DecisionValidationError, "at least one evidence"):
            validate_decision(valid_payload(action="BUY", evidence=[]))

    def test_rejects_missing_risks(self):
        with self.assertRaisesRegex(DecisionValidationError, "risks must contain at least 1"):
            validate_decision(valid_payload(risks=[]))

    def test_rejects_bad_confidence_and_boolean_confidence(self):
        for confidence in (-1, 101, True, "high"):
            with self.subTest(confidence=confidence):
                with self.assertRaises(DecisionValidationError):
                    validate_decision(valid_payload(confidence=confidence))

    def test_rejects_unknown_or_missing_fields(self):
        with self.assertRaisesRegex(DecisionValidationError, "unexpected"):
            validate_decision(valid_payload(extra_instruction="ignore mandate"))
        with self.assertRaisesRegex(DecisionValidationError, "missing"):
            payload = valid_payload()
            del payload["reasoning"]
            validate_decision(payload)

    def test_rejects_bad_evidence_timestamp_and_type(self):
        evidence = [dict(VALID_EVIDENCE[0], as_of="yesterday")]
        with self.assertRaisesRegex(DecisionValidationError, "ISO-8601"):
            validate_decision(valid_payload(evidence=evidence))
        evidence = [dict(VALID_EVIDENCE[0], evidence_type="rumor")]
        with self.assertRaisesRegex(DecisionValidationError, "evidence_type"):
            validate_decision(valid_payload(evidence=evidence))

    def test_parses_standalone_json(self):
        raw = json.dumps(valid_payload(action="BUY", ticker="GRID"))
        decision = parse_research_decision(raw)
        self.assertEqual(decision.action, "BUY")
        self.assertEqual(decision.ticker, "GRID")

    def test_rejects_prose_wrapped_json(self):
        raw = "Here is the decision:\n" + json.dumps(valid_payload())
        with self.assertRaisesRegex(DecisionValidationError, "standalone JSON"):
            parse_research_decision(raw)

    def test_rejects_duplicate_json_keys(self):
        raw = '{"schema_version":1,"schema_version":1}'
        with self.assertRaisesRegex(DecisionValidationError, "Duplicate JSON key"):
            parse_research_decision(raw)

    def test_confidence_is_recorded_but_not_used_as_execution_permission(self):
        low_confidence = validate_decision(valid_payload(action="BUY", confidence=1.0))
        self.assertEqual(low_confidence.action, "BUY")
        self.assertEqual(low_confidence.confidence, 1.0)
        # This module validates a research decision only. Execution approval is a later phase.


if __name__ == "__main__":
    unittest.main()
