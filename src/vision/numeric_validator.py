from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class NumericValidationResult:
    accepted_value: Optional[float]
    valid: bool
    reject_reason: str = ""


class NumericValidator:
    def validate(self, field_name: str, previous_value: float, candidate_value: Optional[float]) -> NumericValidationResult:
        normalized_field = str(field_name or "").lower()
        if "pot" in normalized_field:
            return self.validate_pot(previous_value, candidate_value)
        if "stack" in normalized_field:
            return self.validate_stack(previous_value, candidate_value)
        if "bet" in normalized_field or "mise" in normalized_field:
            return self.validate_bet(previous_value, candidate_value)
        return self.validate_amount(previous_value, candidate_value)

    def _coerce_values(self, previous_value: float, candidate_value: Optional[float]) -> tuple[float, float] | None:
        if candidate_value is None:
            return None
        try:
            previous = max(0.0, float(previous_value or 0.0))
            candidate = float(candidate_value)
        except (TypeError, ValueError):
            return None
        return previous, candidate

    def validate_pot(self, previous_value: float, candidate_value: Optional[float]) -> NumericValidationResult:
        coerced = self._coerce_values(previous_value, candidate_value)
        if candidate_value is None:
            return NumericValidationResult(accepted_value=None, valid=False, reject_reason="missing_candidate")
        if coerced is None:
            return NumericValidationResult(accepted_value=None, valid=False, reject_reason="invalid_numeric_value")
        previous, raw_candidate = coerced
        if raw_candidate < 0.0:
            return NumericValidationResult(accepted_value=None, valid=False, reject_reason="invalid_numeric_value")
        candidate = max(0.0, raw_candidate)

        if candidate == 0.0 and previous > 0.0:
            return NumericValidationResult(accepted_value=previous, valid=False, reject_reason="suspicious_zero_regression")

        if previous > 0.0 and candidate < previous and (candidate / previous) < 0.5:
            return NumericValidationResult(accepted_value=previous, valid=False, reject_reason="implausible_pot_drop")

        if candidate > 200000.0:
            return NumericValidationResult(accepted_value=previous if previous > 0.0 else None, valid=False, reject_reason="pot_too_large")

        return NumericValidationResult(accepted_value=candidate, valid=True)

    def validate_stack(self, previous_value: float, candidate_value: Optional[float]) -> NumericValidationResult:
        del previous_value
        if candidate_value is None:
            return NumericValidationResult(accepted_value=None, valid=False, reject_reason="missing_candidate")
        try:
            candidate = float(candidate_value)
        except (TypeError, ValueError):
            return NumericValidationResult(accepted_value=None, valid=False, reject_reason="invalid_numeric_value")
        if candidate < 0.0:
            return NumericValidationResult(accepted_value=None, valid=False, reject_reason="invalid_numeric_value")
        if candidate > 200000.0:
            return NumericValidationResult(accepted_value=None, valid=False, reject_reason="stack_too_large")
        return NumericValidationResult(accepted_value=candidate, valid=True)

    def validate_bet(self, previous_value: float, candidate_value: Optional[float]) -> NumericValidationResult:
        del previous_value
        if candidate_value is None:
            return NumericValidationResult(accepted_value=None, valid=False, reject_reason="missing_candidate")
        try:
            candidate = float(candidate_value)
        except (TypeError, ValueError):
            return NumericValidationResult(accepted_value=None, valid=False, reject_reason="invalid_numeric_value")
        if candidate < 0.0:
            return NumericValidationResult(accepted_value=None, valid=False, reject_reason="invalid_numeric_value")
        if candidate > 200000.0:
            return NumericValidationResult(accepted_value=None, valid=False, reject_reason="bet_too_large")
        return NumericValidationResult(accepted_value=candidate, valid=True)

    def validate_amount(self, previous_value: float, candidate_value: Optional[float]) -> NumericValidationResult:
        del previous_value
        if candidate_value is None:
            return NumericValidationResult(accepted_value=None, valid=False, reject_reason="missing_candidate")
        try:
            candidate = float(candidate_value)
        except (TypeError, ValueError):
            return NumericValidationResult(accepted_value=None, valid=False, reject_reason="invalid_numeric_value")
        if candidate < 0.0:
            return NumericValidationResult(accepted_value=None, valid=False, reject_reason="invalid_numeric_value")
        if candidate > 200000.0:
            return NumericValidationResult(accepted_value=None, valid=False, reject_reason="amount_too_large")
        return NumericValidationResult(accepted_value=candidate, valid=True)
