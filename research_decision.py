"""Strict, side-effect-free validation for Aegis research decisions.

This module validates the shape and mandate eligibility of Gemini's proposed
research decision. It does not verify whether evidence claims are true, fetch
prices, calculate order sizes, change memory, or execute simulated trades.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

from investment_mandate import normalize_ticker

SCHEMA_VERSION = 1
VALID_ACTIONS = {"BUY", "TRIM", "HOLD", "NO_DECISION"}
VALID_EVIDENCE_TYPES = {
    "market_data",
    "headline_metadata",
    "fundamental_data",
    "regulatory",
    "macro",
    "portfolio_record",
    "industry_research",
    "company_research",
    "other",
}
MAX_TEXT_LENGTH = 4000
MAX_LIST_ITEMS = 20

# JSON Schema-compatible description for constrained model output. The Python
# validator below remains authoritative even if the model provider enforces it.
RESEARCH_DECISION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "schema_version": {"type": "INTEGER", "enum": [SCHEMA_VERSION]},
        "action": {"type": "STRING", "enum": ["BUY", "TRIM", "HOLD", "NO_DECISION"]},
        "ticker": {"type": "STRING", "enum": ["XLU", "GRID", "UTES"], "nullable": True},
        "reasoning": {"type": "STRING"},
        "risks": {"type": "ARRAY", "items": {"type": "STRING"}},
        "evidence": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "claim": {"type": "STRING"},
                    "source": {"type": "STRING"},
                    "as_of": {"type": "STRING"},
                    "evidence_type": {"type": "STRING", "enum": sorted(VALID_EVIDENCE_TYPES)},
                },
                "additionalProperties": False,
                "required": ["claim", "source", "as_of", "evidence_type"],
            },
        },
        "confidence": {"type": "NUMBER", "minimum": 0, "maximum": 100},
        "missing_information": {"type": "ARRAY", "items": {"type": "STRING"}},
        "proposed_lesson": {"type": "STRING", "nullable": True},
    },
    "additionalProperties": False,
    "required": [
        "schema_version", "action", "ticker", "reasoning", "risks",
        "evidence", "confidence", "missing_information", "proposed_lesson",
    ],
}


class DecisionValidationError(ValueError):
    """Raised when a model response is malformed or violates the mandate."""


@dataclass(frozen=True)
class ResearchDecision:
    schema_version: int
    action: str
    ticker: str | None
    reasoning: str
    risks: tuple[str, ...]
    evidence: tuple[dict[str, str], ...]
    confidence: float
    missing_information: tuple[str, ...]
    proposed_lesson: str | None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["risks"] = list(self.risks)
        result["evidence"] = [dict(item) for item in self.evidence]
        result["missing_information"] = list(self.missing_information)
        return result


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DecisionValidationError(f"Duplicate JSON key is not allowed: {key}")
        result[key] = value
    return result


def _required_text(value: Any, field: str, *, minimum: int = 1) -> str:
    if not isinstance(value, str):
        raise DecisionValidationError(f"{field} must be a string.")
    cleaned = value.strip()
    if len(cleaned) < minimum:
        raise DecisionValidationError(f"{field} must contain at least {minimum} characters.")
    if len(cleaned) > MAX_TEXT_LENGTH:
        raise DecisionValidationError(f"{field} exceeds {MAX_TEXT_LENGTH} characters.")
    return cleaned


def _text_list(value: Any, field: str, *, minimum_items: int = 0) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise DecisionValidationError(f"{field} must be a JSON array.")
    if len(value) < minimum_items:
        raise DecisionValidationError(f"{field} must contain at least {minimum_items} item(s).")
    if len(value) > MAX_LIST_ITEMS:
        raise DecisionValidationError(f"{field} cannot contain more than {MAX_LIST_ITEMS} items.")
    return tuple(_required_text(item, f"{field}[{index}]") for index, item in enumerate(value))


def _validate_as_of(value: Any, field: str) -> str:
    text = _required_text(value, field)
    try:
        if "T" in text or " " in text:
            datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            date.fromisoformat(text)
    except ValueError:
        raise DecisionValidationError(f"{field} must be an ISO-8601 date or timestamp.") from None
    return text


def _validate_evidence(value: Any, *, required: bool) -> tuple[dict[str, str], ...]:
    if not isinstance(value, list):
        raise DecisionValidationError("evidence must be a JSON array.")
    if required and not value:
        raise DecisionValidationError("BUY, TRIM, and HOLD decisions require at least one evidence item.")
    if len(value) > MAX_LIST_ITEMS:
        raise DecisionValidationError(f"evidence cannot contain more than {MAX_LIST_ITEMS} items.")

    normalized: list[dict[str, str]] = []
    expected_keys = {"claim", "source", "as_of", "evidence_type"}
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise DecisionValidationError(f"evidence[{index}] must be a JSON object.")
        if set(item) != expected_keys:
            missing = sorted(expected_keys - set(item))
            extra = sorted(set(item) - expected_keys)
            raise DecisionValidationError(
                f"evidence[{index}] fields mismatch; missing={missing}, unexpected={extra}."
            )
        evidence_type = _required_text(item["evidence_type"], f"evidence[{index}].evidence_type").lower()
        if evidence_type not in VALID_EVIDENCE_TYPES:
            raise DecisionValidationError(
                f"evidence[{index}].evidence_type must be one of {sorted(VALID_EVIDENCE_TYPES)}."
            )
        normalized.append({
            "claim": _required_text(item["claim"], f"evidence[{index}].claim", minimum=10),
            "source": _required_text(item["source"], f"evidence[{index}].source"),
            "as_of": _validate_as_of(item["as_of"], f"evidence[{index}].as_of"),
            "evidence_type": evidence_type,
        })
    return tuple(normalized)


def validate_decision(payload: Any) -> ResearchDecision:
    """Validate a decoded JSON object and return an immutable decision.

    BUY/TRIM/HOLD require one of the three mandate tickers and sourced evidence.
    NO_DECISION must have ticker=null; it cannot be converted into HOLD or a
    fallback ticker. Confidence is informational and never authorizes a trade.
    """
    if not isinstance(payload, dict):
        raise DecisionValidationError("Research decision must be a JSON object.")

    required_keys = {
        "schema_version", "action", "ticker", "reasoning", "risks",
        "evidence", "confidence", "missing_information", "proposed_lesson",
    }
    missing = sorted(required_keys - set(payload))
    unexpected = sorted(set(payload) - required_keys)
    if missing or unexpected:
        raise DecisionValidationError(
            f"Decision fields mismatch; missing={missing}, unexpected={unexpected}."
        )

    version = payload["schema_version"]
    if isinstance(version, bool) or version != SCHEMA_VERSION:
        raise DecisionValidationError(f"schema_version must be {SCHEMA_VERSION}.")

    action = _required_text(payload["action"], "action").upper()
    if action not in VALID_ACTIONS:
        raise DecisionValidationError(f"action must be one of {sorted(VALID_ACTIONS)}.")

    raw_ticker = payload["ticker"]
    if action == "NO_DECISION":
        if raw_ticker is not None:
            raise DecisionValidationError("NO_DECISION requires ticker=null; no fallback ticker is permitted.")
        ticker = None
    else:
        if raw_ticker is None:
            raise DecisionValidationError(f"{action} requires a mandate ticker.")
        try:
            ticker = normalize_ticker(raw_ticker)
        except ValueError as exc:
            raise DecisionValidationError(str(exc)) from exc

    reasoning = _required_text(payload["reasoning"], "reasoning", minimum=20)
    risks = _text_list(payload["risks"], "risks", minimum_items=1)
    missing_information = _text_list(payload["missing_information"], "missing_information")
    evidence = _validate_evidence(payload["evidence"], required=(action != "NO_DECISION"))

    confidence = payload["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise DecisionValidationError("confidence must be a number between 0 and 100.")
    if not 0 <= float(confidence) <= 100:
        raise DecisionValidationError("confidence must be between 0 and 100.")

    lesson_value = payload["proposed_lesson"]
    if lesson_value is None or (isinstance(lesson_value, str) and not lesson_value.strip()):
        proposed_lesson = None
    else:
        proposed_lesson = _required_text(lesson_value, "proposed_lesson")
        if len(proposed_lesson) > 300:
            raise DecisionValidationError("proposed_lesson cannot exceed 300 characters.")

    return ResearchDecision(
        schema_version=SCHEMA_VERSION,
        action=action,
        ticker=ticker,
        reasoning=reasoning,
        risks=risks,
        evidence=evidence,
        confidence=float(confidence),
        missing_information=missing_information,
        proposed_lesson=proposed_lesson,
    )


def parse_research_decision(raw_json: str) -> ResearchDecision:
    """Parse strict JSON; reject duplicate keys, prose wrappers, and bad schema."""
    if not isinstance(raw_json, str) or not raw_json.strip():
        raise DecisionValidationError("Model response is empty; NO DECISION.")
    try:
        payload = json.loads(raw_json, object_pairs_hook=_reject_duplicate_keys)
    except DecisionValidationError:
        raise
    except (json.JSONDecodeError, TypeError) as exc:
        raise DecisionValidationError(f"Model response is not valid standalone JSON: {exc}") from exc
    return validate_decision(payload)
