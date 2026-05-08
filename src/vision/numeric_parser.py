from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional, Sequence

from src.vision.ocr import PokerOCR


@dataclass(frozen=True)
class NumericParseResult:
    value: Optional[float]
    sanitized_text: str
    valid: bool
    reject_reason: str = ""


class NumericParser:
    def __init__(
        self,
        *,
        allow_decimal_amounts: bool = True,
        thousands_separators: Sequence[str] = (" ",),
        decimal_separators: Sequence[str] = (",", "."),
    ) -> None:
        self.allow_decimal_amounts = bool(allow_decimal_amounts)
        self.thousands_separators = tuple(thousands_separators)
        self.decimal_separators = tuple(decimal_separators)

    def _fallback_parse_amount(self, text: str) -> Optional[float]:
        normalized = str(text or "").replace("\u00A0", " ")
        candidates = re.findall(r"[\d][\d\s,\.]*", normalized)
        if not candidates:
            return None

        token = max(candidates, key=len).strip()
        if not token:
            return None

        compact = token.replace(" ", "")
        if not compact:
            return None

        decimal_separator = ""
        for separator in self.decimal_separators:
            if separator and compact.count(separator) == 1:
                suffix = compact.rsplit(separator, 1)[1]
                if self.allow_decimal_amounts and 1 <= len(suffix) <= 2 and suffix.isdigit():
                    decimal_separator = separator
                    break

        sanitized = compact
        for separator in self.thousands_separators:
            if separator:
                sanitized = sanitized.replace(separator, "")

        if decimal_separator:
            for separator in self.decimal_separators:
                if separator and separator != decimal_separator:
                    sanitized = sanitized.replace(separator, "")
            sanitized = sanitized.replace(decimal_separator, ".")
        else:
            for separator in self.decimal_separators:
                if separator:
                    sanitized = sanitized.replace(separator, "")

        if not re.fullmatch(r"\d+(\.\d+)?", sanitized):
            return None
        try:
            return float(sanitized)
        except ValueError:
            return None

    def parse(self, raw_text: str) -> NumericParseResult:
        text = str(raw_text or "").strip()
        if not text:
            return NumericParseResult(value=None, sanitized_text="", valid=False, reject_reason="empty_text")

        parse_amount = getattr(PokerOCR, "parse_amount", None)
        if callable(parse_amount):
            value = parse_amount(
                text,
                allow_decimal_amounts=self.allow_decimal_amounts,
                thousands_separators=self.thousands_separators,
                decimal_separators=self.decimal_separators,
            )
        else:
            value = self._fallback_parse_amount(text)
        if value is None:
            return NumericParseResult(value=None, sanitized_text=text, valid=False, reject_reason="parse_rejected")
        return NumericParseResult(value=float(value), sanitized_text=text, valid=True)
