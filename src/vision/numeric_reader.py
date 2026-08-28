from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from src.runtime.evidence_models import (
    FieldCandidate,
    FieldCriticality,
    FieldEvidence,
)
from src.vision.crop_quality import analyze_crop_quality
from src.vision.numeric_consensus import NumericConsensus
from src.vision.numeric_parser import NumericParser
from src.vision.numeric_preprocessing import preprocess_numeric_variants
from src.vision.numeric_validator import NumericValidator


@dataclass(frozen=True)
class NumericReadResult:
    selected_value: float | None
    evidence: FieldEvidence
    metadata: dict[str, Any]


class NumericReader:
    def __init__(
        self,
        ocr_engine,
        *,
        parser: NumericParser | None = None,
        validator: NumericValidator | None = None,
        consensus: NumericConsensus | None = None,
    ) -> None:
        self.ocr_engine = ocr_engine
        self.parser = parser or NumericParser()
        self.validator = validator or NumericValidator()
        self.consensus = consensus or NumericConsensus()

    @staticmethod
    def _iter_live_variants(field_name: str, image_crop: np.ndarray):
        variants = preprocess_numeric_variants(image_crop)
        if field_name == "pot":
            preferred = {"original", "upscaled_x2"}
            filtered = [(name, crop) for name, crop in variants if name in preferred]
            return filtered or variants[:2]
        return variants

    def read_amount(
        self, field_name: str, image_crop: np.ndarray, *, previous_value: float = 0.0
    ) -> NumericReadResult:
        crop_quality = analyze_crop_quality(field_name, image_crop)
        if image_crop is None or not isinstance(image_crop, np.ndarray) or image_crop.size == 0:
            evidence = FieldEvidence(
                field_name=field_name,
                criticality=FieldCriticality.IMPORTANT,
                crop_quality=crop_quality,
                state="empty",
                rejection_reason="empty_crop",
            )
            return NumericReadResult(
                selected_value=None, evidence=evidence, metadata={"variants": []}
            )

        candidates = []
        best_value: float | None = None
        best_confidence = -1.0
        best_candidate = None
        variant_rows = []
        for variant_name, variant_crop in self._iter_live_variants(field_name, image_crop):
            value = self.ocr_engine.read_and_parse_amount(variant_crop)
            ocr_metadata = (
                dict(self.ocr_engine.get_metadata() or {})
                if hasattr(self.ocr_engine, "get_metadata")
                else {}
            )
            parse_result = self.parser.parse(str(ocr_metadata.get("selected_text", "") or ""))
            parsed_value = parse_result.value if parse_result.valid else value
            confidence = float(ocr_metadata.get("selected_confidence", 0.0) or 0.0)
            candidate = FieldCandidate(
                field_name=field_name,
                value=parsed_value,
                raw_text=str(ocr_metadata.get("selected_text", "") or ""),
                confidence=confidence,
                source="numeric_reader",
                engine=str(ocr_metadata.get("selected_engine", "") or ""),
                variant=variant_name,
                metadata={"ocr": ocr_metadata, "parse_result": parse_result.__dict__},
            )
            candidates.append(candidate)
            variant_rows.append(
                {
                    "variant": variant_name,
                    "value": parsed_value,
                    "selected_engine": ocr_metadata.get("selected_engine", ""),
                    "selected_confidence": confidence,
                    "parse_valid": parse_result.valid,
                }
            )
            if parsed_value is not None and confidence >= best_confidence:
                best_confidence = confidence
                best_value = parsed_value
                best_candidate = candidate

            if (
                field_name == "pot"
                and parsed_value is not None
                and confidence >= 0.88
                and variant_name in {"original", "upscaled_x2"}
            ):
                break

        validation_result = self.validator.validate(field_name, previous_value, best_value)
        # Tentative pot jumps require stronger confirmation.
        if (
            field_name == "pot"
            and validation_result.valid
            and best_value is not None
            and previous_value > 5.0
            and best_value > previous_value * 2.5
            and best_confidence < 0.94
        ):
            validation_result = __import__(
                "src.vision.numeric_validator", fromlist=["NumericValidationResult"]
            ).NumericValidationResult(
                accepted_value=previous_value,
                valid=False,
                reject_reason="implausible_pot_jump_needs_confirmation",
            )
        consensus_result = self.consensus.update(validation_result.accepted_value)
        final_value = consensus_result.value
        final_candidate = best_candidate if validation_result.valid else None
        final_state = consensus_result.state if validation_result.valid else "quarantined"
        rejection_reason = (
            ""
            if validation_result.valid
            else validation_result.reject_reason or "no_valid_numeric_candidate"
        )
        # Quarantine policy for pot.
        # - When the validator rejected the new OCR value (e.g. implausible drop,
        #   implausible jump, zero regression, etc.) and the consensus has not yet
        #   confirmed a stable value, hold the previous value if already grounded
        #   (previous_value>0) otherwise surface None but keep state quarantined.
        # - When the OCR value is valid but large (>2x) and consensus is still
        #   tentative, delay promoting it to selected_value (wait for a 2nd frame).
        # - Cold-start (previous_value==0, first ever frame) must not be stuck in
        #   quarantine because downstream consumers await a first non-None value.
        should_quarantine = False
        if field_name == "pot" and consensus_result.state == "tentative":
            if not validation_result.valid:
                # rejected by validator — quarantine if we already have a grounded baseline
                should_quarantine = previous_value > 0.0
            else:
                should_quarantine = (
                    best_value is not None
                    and previous_value > 0.0
                    and best_value > previous_value * 2.0
                )
        if should_quarantine:
            final_value = (
                validation_result.accepted_value
                if not validation_result.valid and previous_value > 0.0
                else (consensus_result.history[-2] if len(consensus_result.history) >= 2 else None)
            )
            # When validator rejected, previous_value is the ground truth to keep.
            if not validation_result.valid and previous_value > 0.0:
                final_value = float(validation_result.accepted_value)
            final_state = "quarantined"
            if validation_result.valid:
                rejection_reason = "pot_consensus_tentative"
            final_candidate = None

        evidence = FieldEvidence(
            field_name=field_name,
            criticality=FieldCriticality.IMPORTANT,
            selected_value=final_value,
            selected_candidate=final_candidate,
            candidates=tuple(candidates),
            confidence=max(0.0, best_confidence),
            crop_quality=crop_quality,
            state=final_state,
            rejection_reason=rejection_reason,
            metadata={
                "variants": variant_rows,
                "validation": validation_result.__dict__,
                "consensus": consensus_result.__dict__,
                "previous_value": previous_value,
            },
        )
        return NumericReadResult(
            selected_value=final_value,
            evidence=evidence,
            metadata={
                "variants": variant_rows,
                "validation": validation_result.__dict__,
                "consensus": consensus_result.__dict__,
            },
        )
