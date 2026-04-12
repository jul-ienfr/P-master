"""Local-first room preset management, validation and drift detection."""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from poker.tools.helper import COMPUTER_NAME, get_config, get_dir
from poker.tools.supported_sites import infer_supported_site

log = logging.getLogger(__name__)

try:  # pragma: no cover - depends on local runtime packages
    from poker.tools.screen_operations import (
        binary_pil_to_cv2 as _binary_pil_to_cv2,
        crop_screenshot_with_topleft_corner as _crop_screenshot_with_topleft_corner,
        find_template_on_screen as _find_template_on_screen,
        get_ocr_float as _get_ocr_float,
        is_template_in_search_area as _is_template_in_search_area,
    )
    _SCREEN_OPS_AVAILABLE = True
except Exception:  # pragma: no cover - fallback for lightweight test/runtime environments
    _binary_pil_to_cv2 = None
    _crop_screenshot_with_topleft_corner = None
    _find_template_on_screen = None
    _get_ocr_float = None
    _is_template_in_search_area = None
    _SCREEN_OPS_AVAILABLE = False

SCHEMA_VERSION = 1
ROOM_PRESET_DIRNAME = "local_presets"
FAMILY_FILENAME = "family.json"
MANIFEST_FILENAME = "manifest.json"
ASSET_DIRNAME = "assets"
MODEL_DIRNAME = "model"
SAMPLE_DIRNAME = "samples"
RUNTIME_CAPTURE_DIRNAME = "runtime_captures"
MAX_RUNTIME_CAPTURES = 12
DEFAULT_AI_TIMEOUT_SECONDS = 45
DEFAULT_AI_MAX_IMAGES = 3

MANDATORY_ASSET_LABELS = (
    "topleft_corner",
    "call_button",
    "fold_button",
    "dealer_button",
    "covered_card",
)
MANDATORY_COORDINATES = (
    "buttons_search_area",
    "my_turn_search_area",
    "table_cards_area",
    "my_cards_area",
    "total_pot_area",
)
CRITICAL_TEMPLATE_LABELS = (
    "call_button",
    "fold_button",
    "dealer_button",
    "covered_card",
)
OPTIONAL_TEMPLATE_LABELS = (
    "raise_button",
    "bet_button",
    "check_button",
    "all_in_call_button",
    "my_turn",
    "fast_fold_button",
    "lost_everything",
    "im_back",
    "resume_hand",
)
NUMERIC_AREAS = (
    "call_value",
    "raise_value",
    "all_in_call_value",
    "current_round_pot",
    "total_pot_area",
)
PLAYER_AREA_LABELS = (
    "covered_card_area",
    "player_name_area",
    "player_funds_area",
    "player_pot_area",
    "button_search_area",
)

_PRESET_REPOSITORY = None


def read_room_manager_settings() -> dict[str, Any]:
    config = get_config().config
    return {
        "enable_drift_watcher": config.getboolean("room_manager", "enable_drift_watcher", fallback=False),
        "drift_check_interval_seconds": config.getint("room_manager", "drift_check_interval_seconds", fallback=300),
        "ai_mode": config.get("room_manager", "ai_mode", fallback="local"),
        "ai_cloud_opt_in": config.getboolean("room_manager", "ai_cloud_opt_in", fallback=False),
        "ai_provider_type": config.get("room_manager", "ai_provider_type", fallback="openai_compatible"),
        "ai_endpoint": config.get("room_manager", "ai_endpoint", fallback="").strip(),
        "ai_model": config.get("room_manager", "ai_model", fallback="").strip(),
        "ai_api_key_env": config.get("room_manager", "ai_api_key_env", fallback="ROOM_MANAGER_AI_API_KEY").strip(),
        "ai_api_key": config.get("room_manager", "ai_api_key", fallback="").strip(),
        "ai_timeout_seconds": config.getint("room_manager", "ai_timeout_seconds", fallback=DEFAULT_AI_TIMEOUT_SECONDS),
        "ai_max_images": config.getint("room_manager", "ai_max_images", fallback=DEFAULT_AI_MAX_IMAGES),
        "ai_allow_full_screenshot": config.getboolean("room_manager", "ai_allow_full_screenshot", fallback=False),
        "ai_extra_headers_json": config.get("room_manager", "ai_extra_headers_json", fallback="").strip(),
    }


def update_room_manager_settings(updates: dict[str, Any]) -> dict[str, Any]:
    parser = get_config()
    config = parser.config
    if not config.has_section("room_manager"):
        config.add_section("room_manager")
    for key, value in updates.items():
        if isinstance(value, bool):
            serialized = "true" if value else "false"
        else:
            serialized = str(value)
        config.set("room_manager", key, serialized)
    parser.update_file()
    return read_room_manager_settings()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _slugify(value: str) -> str:
    cleaned = [
        ch.lower() if ch.isalnum() else "-"
        for ch in str(value).strip()
    ]
    slug = "".join(cleaned).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "preset"


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        if default is not None:
            return copy.deepcopy(default)
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _hash_image(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return _hash_bytes(buffer.getvalue())


def _load_image_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _save_image_bytes(path: Path, payload: bytes) -> None:
    _ensure_parent(path)
    path.write_bytes(payload)


def _image_to_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _template_to_internal(payload: bytes):
    if _SCREEN_OPS_AVAILABLE:
        return _binary_pil_to_cv2(payload)
    return Image.open(io.BytesIO(payload)).convert("RGB")


def _fallback_find_template(template: Image.Image, screenshot: Image.Image):
    template = template.convert("RGB")
    screenshot = screenshot.convert("RGB")
    width, height = template.size
    screenshot_width, screenshot_height = screenshot.size
    template_bytes = template.tobytes()
    screenshot_bytes = screenshot.tobytes()
    template_row_stride = width * 3
    screenshot_row_stride = screenshot_width * 3
    template_rows = [
        template_bytes[row * template_row_stride:(row + 1) * template_row_stride]
        for row in range(height)
    ]
    screenshot_rows = [
        screenshot_bytes[row * screenshot_row_stride:(row + 1) * screenshot_row_stride]
        for row in range(screenshot_height)
    ]
    points = []
    best_fit = None
    for y in range(screenshot_height - height + 1):
        current_row = screenshot_rows[y]
        start = 0
        while True:
            match_at = current_row.find(template_rows[0], start)
            if match_at < 0:
                break
            if match_at % 3 == 0:
                x = match_at // 3
                if x + width <= screenshot_width:
                    matched = True
                    for row_index in range(1, height):
                        segment = screenshot_rows[y + row_index][x * 3:(x + width) * 3]
                        if segment != template_rows[row_index]:
                            matched = False
                            break
                    if matched:
                        points.append((x, y))
                        if best_fit is None:
                            best_fit = (x, y)
            start = match_at + 3
    return len(points), points, best_fit, 0.0 if points else 1.0


def _find_template(template, screenshot, threshold=0.01):
    if _SCREEN_OPS_AVAILABLE:
        return _find_template_on_screen(template, screenshot, threshold)
    return _fallback_find_template(template, screenshot)


def _crop_with_topleft_corner(screenshot: Image.Image, topleft_payload: bytes):
    if _SCREEN_OPS_AVAILABLE:
        return _crop_screenshot_with_topleft_corner(
            screenshot,
            _binary_pil_to_cv2(topleft_payload),
            useSleep=False,
        )
    template = Image.open(io.BytesIO(topleft_payload)).convert("RGB")
    count, points, _, _ = _fallback_find_template(template, screenshot)
    if count != 1:
        return None, None
    point = points[0]
    return screenshot.crop((point[0], point[1], point[0] + 1500, point[1] + 1100)), point


def _resolve_search_area(table_dict: dict[str, Any], image_area: str, player: str | None):
    if player:
        return table_dict[image_area][player]
    return table_dict[image_area]


def _template_in_search_area(table_dict, screenshot, image_name, image_area, player=None, extended=False):
    _ = extended
    if _SCREEN_OPS_AVAILABLE:
        return _is_template_in_search_area(table_dict, screenshot, image_name, image_area, player=player)
    template = Image.open(io.BytesIO(table_dict[image_name])).convert("RGB")
    search_area = _resolve_search_area(table_dict, image_area, player)
    cropped = screenshot.crop((search_area["x1"], search_area["y1"], search_area["x2"], search_area["y2"]))
    count, _, _, _ = _fallback_find_template(template, cropped)
    return count >= 1


def _ocr_float(image: Image.Image) -> float:
    if _SCREEN_OPS_AVAILABLE:
        return _get_ocr_float(image)
    return -1.0


def _deepcopy_jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _set_nested_mapping(table_data: dict[str, Any], label: str, value: Any) -> None:
    if "." not in label:
        table_data[label] = value
        return

    root_key, nested_key = label.split(".", 1)
    nested = table_data.setdefault(root_key, {})
    nested[nested_key] = value


def _flatten_nested_keys(payload: dict[str, Any]) -> set[str]:
    flattened = set()
    for key, value in payload.items():
        flattened.add(key)
        if isinstance(value, dict):
            for nested_key in value:
                flattened.add(f"{key}.{nested_key}")
    return flattened


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


@dataclass
class ValidationResult:
    status: str
    golden_pass_rate: float
    live_pass_rate: float
    critical_anchor_score: float
    issues: list[str] = field(default_factory=list)
    evaluated_samples: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "golden_pass_rate": round(self.golden_pass_rate, 4),
            "live_pass_rate": round(self.live_pass_rate, 4),
            "critical_anchor_score": round(self.critical_anchor_score, 4),
            "issues": list(self.issues),
            "evaluated_samples": self.evaluated_samples,
        }


@dataclass
class RuntimeResolution:
    table_name: str
    resolved_table_name: str
    family_slug: str | None
    version_id: str | None
    score: float
    fingerprint_hash: str
    diagnostics: list[str] = field(default_factory=list)


@dataclass
class DriftResult:
    status: str
    table_name: str
    score: float
    version_id: str | None = None
    diagnostics: list[str] = field(default_factory=list)


class AiAssistProvider:
    """Base contract for optional preset assistance."""

    provider_name = "none"

    def suggest(self, table_name: str, screenshots: list[Image.Image], manifest: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "site_guess": None,
            "base_preset": None,
            "notes": [],
        }


class LocalAiAssistProvider(AiAssistProvider):
    provider_name = "local"

    def __init__(self, repository: "HybridPresetRepository"):
        self.repository = repository

    def suggest(self, table_name: str, screenshots: list[Image.Image], manifest: dict[str, Any]) -> dict[str, Any]:
        related = self.repository.local_repository.find_related_family_names(table_name)
        site = infer_supported_site(table_name)
        notes = []
        if site:
            notes.append(f"Detected site family: {site.display_name}")
        if related:
            notes.append(f"Closest existing preset: {related[0]}")
        if screenshots:
            notes.append(f"{len(screenshots)} screenshot(s) available for local validation and sample publishing.")
        return {
            "provider": self.provider_name,
            "site_guess": site.display_name if site else None,
            "base_preset": related[0] if related else None,
            "notes": notes,
        }


def _encode_data_url(image: Image.Image) -> str:
    return "data:image/png;base64," + base64.b64encode(_image_to_bytes(image)).decode("ascii")


def _extract_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    stripped = (text or "").strip()
    if not stripped:
        return None
    try:
        return decoder.raw_decode(stripped)[0]
    except Exception:
        pass
    for match in re.finditer(r"\{", stripped):
        try:
            return decoder.raw_decode(stripped[match.start():])[0]
        except Exception:
            continue
    return None


def _truncate_text(value: Any, limit: int = 400) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit - 3] + "..."


class CompositeAiAssistProvider(AiAssistProvider):
    provider_name = "composite"

    def __init__(self, providers: list[AiAssistProvider]):
        self.providers = [provider for provider in providers if provider is not None]

    def suggest(self, table_name: str, screenshots: list[Image.Image], manifest: dict[str, Any]) -> dict[str, Any]:
        combined = super().suggest(table_name, screenshots, manifest)
        providers_used = []
        notes = []
        for provider in self.providers:
            suggestion = provider.suggest(table_name, screenshots, manifest)
            providers_used.append(suggestion.get("provider", provider.provider_name))
            if not combined.get("site_guess") and suggestion.get("site_guess"):
                combined["site_guess"] = suggestion.get("site_guess")
            if not combined.get("base_preset") and suggestion.get("base_preset"):
                combined["base_preset"] = suggestion.get("base_preset")
            notes.extend(suggestion.get("notes", []))
            if suggestion.get("cloud_response"):
                combined["cloud_response"] = suggestion["cloud_response"]
            if suggestion.get("request_summary"):
                combined["request_summary"] = suggestion["request_summary"]
        combined["provider"] = "+".join(dict.fromkeys(providers_used)) if providers_used else self.provider_name
        combined["notes"] = notes
        return combined


class CloudAiAssistProvider(AiAssistProvider):
    provider_name = "cloud"

    def __init__(
        self,
        repository: "HybridPresetRepository",
        settings: dict[str, Any] | None = None,
        request_post=None,
    ):
        self.repository = repository
        self.settings = settings or {}
        self.request_post = request_post

    @property
    def enabled(self) -> bool:
        return self.settings.get("ai_mode", "local") == "cloud" and self.settings.get("ai_cloud_opt_in", False)

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        api_key = self.settings.get("ai_api_key")
        if not api_key:
            api_key_env = self.settings.get("ai_api_key_env")
            if api_key_env:
                api_key = os.environ.get(api_key_env, "")
        if api_key:
            headers["Authorization"] = api_key if api_key.lower().startswith("bearer ") else f"Bearer {api_key}"
        extra_headers_raw = self.settings.get("ai_extra_headers_json", "")
        if extra_headers_raw:
            try:
                parsed_headers = json.loads(extra_headers_raw)
                if isinstance(parsed_headers, dict):
                    headers.update({str(k): str(v) for k, v in parsed_headers.items()})
            except Exception as exc:
                log.warning("Ignoring invalid room_manager.ai_extra_headers_json: %s", exc)
        return headers

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        import requests

        endpoint = self.settings.get("ai_endpoint", "")
        timeout = max(5, int(self.settings.get("ai_timeout_seconds", DEFAULT_AI_TIMEOUT_SECONDS)))
        response = (self.request_post or requests.post)(
            endpoint,
            json=payload,
            headers=self._build_headers(),
            timeout=timeout,
        )
        response.raise_for_status()
        try:
            return response.json()
        except Exception:
            return {"text": response.text}

    @staticmethod
    def _sanitize_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
        return {
            "display_name": manifest.get("display_name"),
            "identity": copy.deepcopy(manifest.get("identity", {})),
            "table_data_keys": sorted(manifest.get("table_data", {}).keys()),
            "validation": copy.deepcopy(manifest.get("validation", {})),
            "fingerprint": {
                "hash": manifest.get("fingerprint", {}).get("hash"),
                "site_key": manifest.get("fingerprint", {}).get("site_key"),
            },
        }

    def _collect_screenshot_payload(
        self,
        table_name: str,
        screenshots: list[Image.Image],
        manifest: dict[str, Any],
    ) -> tuple[list[dict[str, str]], list[str]]:
        notes = []
        if not screenshots:
            return [], ["No screenshots available for cloud analysis."]

        limit = max(1, int(self.settings.get("ai_max_images", DEFAULT_AI_MAX_IMAGES)))
        allow_full = self.settings.get("ai_allow_full_screenshot", False)
        payload = []
        table_dict = None
        try:
            table_dict = self.repository.local_repository._manifest_to_table_dict(table_name, manifest)
        except Exception:
            table_dict = None

        for screenshot_index, screenshot in enumerate(screenshots[:limit]):
            working_image = screenshot
            if table_dict and "topleft_corner" in table_dict:
                try:
                    cropped, _ = _crop_with_topleft_corner(screenshot, table_dict["topleft_corner"])
                    if cropped:
                        working_image = cropped
                except Exception:
                    pass

            if allow_full:
                payload.append(
                    {
                        "label": f"full_table_{screenshot_index + 1}",
                        "mime_type": "image/png",
                        "image_url": _encode_data_url(working_image),
                    }
                )
            else:
                extracted = 0
                for area_name in ("buttons_search_area", "table_cards_area", "my_cards_area", "total_pot_area"):
                    coords = manifest.get("table_data", {}).get(area_name)
                    if not isinstance(coords, dict) or "x1" not in coords:
                        continue
                    crop = working_image.crop((coords["x1"], coords["y1"], coords["x2"], coords["y2"]))
                    payload.append(
                        {
                            "label": f"{area_name}_{screenshot_index + 1}",
                            "mime_type": "image/png",
                            "image_url": _encode_data_url(crop),
                        }
                    )
                    extracted += 1
                if extracted == 0:
                    notes.append(
                        "Cloud upload kept disabled for full screenshots and no mapped search areas were available to crop."
                    )
        if payload:
            notes.append(f"{len(payload)} cropped image(s) prepared for cloud assist.")
        return payload, notes

    def _build_openai_payload(
        self,
        table_name: str,
        manifest: dict[str, Any],
        screenshot_payload: list[dict[str, str]],
        local_hint: dict[str, Any],
    ) -> dict[str, Any]:
        prompt = {
            "task": "Suggest only safe poker room preset mapping hints. Never claim a preset is ready for auto-activation.",
            "table_name": table_name,
            "manifest": self._sanitize_manifest(manifest),
            "local_hint": {
                "site_guess": local_hint.get("site_guess"),
                "base_preset": local_hint.get("base_preset"),
                "notes": local_hint.get("notes", []),
            },
            "response_format": {
                "site_guess": "string or null",
                "base_preset": "string or null",
                "notes": ["short actionable notes"],
                "likely_changed_regions": ["labels for changed zones or buttons"],
                "safe_actions": ["manual next steps only"],
            },
        }
        content = [{"type": "text", "text": json.dumps(prompt, indent=2, sort_keys=True)}]
        for screenshot in screenshot_payload:
            content.append({"type": "text", "text": f"Image label: {screenshot['label']}"})
            content.append({"type": "image_url", "image_url": {"url": screenshot["image_url"]}})
        payload = {
            "model": self.settings.get("ai_model") or "vision-model",
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": "You are a cautious poker room preset assistant. Suggest hints only; never auto-approve changes.",
                },
                {"role": "user", "content": content},
            ],
        }
        return payload

    def _build_generic_payload(
        self,
        table_name: str,
        manifest: dict[str, Any],
        screenshot_payload: list[dict[str, str]],
        local_hint: dict[str, Any],
    ) -> dict[str, Any]:
        generic_images = []
        for screenshot in screenshot_payload:
            generic_images.append(
                {
                    "label": screenshot["label"],
                    "mime_type": screenshot["mime_type"],
                    "image_base64": screenshot["image_url"].split(",", 1)[1],
                }
            )
        return {
            "table_name": table_name,
            "manifest": self._sanitize_manifest(manifest),
            "local_hint": local_hint,
            "screenshots": generic_images,
            "instructions": "Return JSON only. Suggest hints only. Do not auto-approve or auto-publish preset changes.",
        }

    def _parse_openai_response(self, response_body: dict[str, Any]) -> dict[str, Any]:
        message = ""
        try:
            message = response_body["choices"][0]["message"]["content"]
        except Exception:
            message = response_body.get("text", "")
        if isinstance(message, list):
            message = "\n".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in message
            )
        parsed = _extract_json_object(message if isinstance(message, str) else str(message))
        if parsed:
            return parsed
        return {"notes": [_truncate_text(message or response_body)]}

    @staticmethod
    def _parse_generic_response(response_body: dict[str, Any]) -> dict[str, Any]:
        if isinstance(response_body, dict):
            if isinstance(response_body.get("suggestion"), dict):
                return response_body["suggestion"]
            return response_body
        return {"notes": [_truncate_text(response_body)]}

    def suggest(self, table_name: str, screenshots: list[Image.Image], manifest: dict[str, Any]) -> dict[str, Any]:
        response = super().suggest(table_name, screenshots, manifest)
        if not self.enabled:
            response["notes"] = ["Cloud AI assist is disabled. Only local assistance is active."]
            return response
        if not self.settings.get("ai_endpoint"):
            response["notes"] = ["Cloud AI assist is enabled but no API endpoint is configured."]
            return response

        local_hint = LocalAiAssistProvider(self.repository).suggest(table_name, screenshots, manifest)
        screenshot_payload, capture_notes = self._collect_screenshot_payload(table_name, screenshots, manifest)
        provider_type = self.settings.get("ai_provider_type", "openai_compatible")
        if provider_type == "generic_json":
            payload = self._build_generic_payload(table_name, manifest, screenshot_payload, local_hint)
        else:
            payload = self._build_openai_payload(table_name, manifest, screenshot_payload, local_hint)

        try:
            body = self._post_json(payload)
            suggestion = (
                self._parse_generic_response(body)
                if provider_type == "generic_json"
                else self._parse_openai_response(body)
            )
        except Exception as exc:
            response["notes"] = capture_notes + [f"Cloud AI assist failed: {_truncate_text(exc)}"]
            response["request_summary"] = {
                "provider_type": provider_type,
                "endpoint": self.settings.get("ai_endpoint"),
                "images_sent": len(screenshot_payload),
            }
            return response

        response.update(
            {
                "site_guess": suggestion.get("site_guess"),
                "base_preset": suggestion.get("base_preset"),
                "notes": capture_notes + list(suggestion.get("notes", [])),
                "cloud_response": suggestion,
                "request_summary": {
                    "provider_type": provider_type,
                    "endpoint": self.settings.get("ai_endpoint"),
                    "model": self.settings.get("ai_model"),
                    "images_sent": len(screenshot_payload),
                    "full_screenshot_allowed": self.settings.get("ai_allow_full_screenshot", False),
                },
            }
        )
        return response


def build_ai_assist_provider(
    repository: "HybridPresetRepository",
    settings: dict[str, Any] | None = None,
) -> AiAssistProvider:
    settings = settings or read_room_manager_settings()
    providers: list[AiAssistProvider] = [LocalAiAssistProvider(repository)]
    if settings.get("ai_mode", "local") == "cloud":
        providers.append(CloudAiAssistProvider(repository, settings=settings))
    if len(providers) == 1:
        return providers[0]
    return CompositeAiAssistProvider(providers)


class RemotePresetSync:
    """Optional adapter for the legacy remote preset API."""

    def __init__(self, url: str, login: str, password: str):
        self.url = url.rstrip("/") + "/"
        self.login = login
        self.password = password

    def _post_json(self, path: str, **kwargs) -> Any:
        import requests

        response = requests.post(self.url + path, timeout=20, **kwargs)
        response.raise_for_status()
        return response.json()

    def fetch_table(self, table_name: str) -> dict[str, Any]:
        from requests.exceptions import JSONDecodeError

        try:
            table = self._post_json("get_table", params={"table_name": table_name})
        except JSONDecodeError as exc:
            raise RuntimeError(
                "JSONDecodeError: Most likely this table has using neural network enabled but no neural network has "
                "been trained yet. Either train a neural network for this table, or untick the use neural network "
                "checkbox for the given table."
            ) from exc

        converted = {}
        for key, value in table.items():
            try:
                if isinstance(value, (dict, int, list, float)):
                    converted[key] = value
                elif isinstance(value, str) and value[0:2] == "iV":
                    converted[key] = base64.b64decode(value)
                else:
                    converted[key] = value
            except TypeError:
                pass
        return converted

    def get_available_tables(self, computer_name: str) -> list[str]:
        try:
            tables = self._post_json("get_available_tables", params={"computer_name": computer_name})
            return list(tables)
        except Exception as exc:  # pragma: no cover - network dependent
            log.debug("Remote preset listing failed: %s", exc)
            return []

    def get_table_owner(self, table_name: str) -> str | None:
        try:
            return self._post_json("get_table_owner", params={"table_name": table_name})
        except Exception as exc:  # pragma: no cover - network dependent
            log.debug("Remote owner lookup failed for %s: %s", table_name, exc)
            return None

    def create_new_table(self, table_name: str, computer_name: str) -> Any:
        try:
            import requests

            return requests.post(
                self.url + "create_new_table",
                params={"table_name": table_name, "computer_name": computer_name},
                timeout=20,
            )
        except Exception as exc:  # pragma: no cover - network dependent
            log.debug("Remote create_new_table failed for %s: %s", table_name, exc)
            return False

    def create_new_table_from_old(self, table_name: str, old_table_name: str, computer_name: str) -> Any:
        try:
            return self._post_json(
                "create_new_table_from_old",
                params={
                    "table_name": table_name,
                    "old_table_name": old_table_name,
                    "computer_name": computer_name,
                },
            )
        except Exception as exc:  # pragma: no cover - network dependent
            log.debug("Remote create_new_table_from_old failed for %s: %s", table_name, exc)
            return False

    def push_table(self, table_name: str, table_dict: dict[str, Any], owner: str) -> bool:
        """Best-effort export of a local preset to the legacy remote API."""
        try:
            self.create_new_table(table_name, owner)
            import requests
            from fastapi.encoders import jsonable_encoder

            for key, value in table_dict.items():
                if isinstance(value, bytes):
                    encoded = jsonable_encoder(value, custom_encoder={bytes: lambda v: base64.b64encode(v).decode("utf-8")})
                    requests.post(
                        self.url + "update_table_image",
                        json={"pil_image": encoded, "label": key, "table_name": table_name},
                        timeout=20,
                    )
                elif key == "_model":
                    continue
                elif key == "_class_mapping":
                    continue
                elif isinstance(value, dict):
                    requests.post(
                        self.url + "save_coordinates",
                        params={
                            "table_name": table_name,
                            "label": key,
                            "coordinates_dict": json.dumps(value),
                        },
                        timeout=20,
                    )
                else:
                    requests.post(
                        self.url + "update_state",
                        params={"state": value, "label": key, "table_name": table_name},
                        timeout=20,
                    )
            return True
        except Exception as exc:  # pragma: no cover - network dependent
            log.warning("Remote preset export failed for %s: %s", table_name, exc)
            return False


class LocalPresetRepository:
    """Versioned local storage for room presets."""

    def __init__(self, base_dir: str | Path | None = None):
        resolved_base = Path(base_dir) if base_dir else Path(get_dir("codebase", ROOM_PRESET_DIRNAME))
        self.base_dir = resolved_base
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _family_slug(self, table_name: str) -> str:
        return _slugify(table_name)

    def _family_dir(self, table_name_or_slug: str) -> Path:
        return self.base_dir / self._family_slug(table_name_or_slug)

    def _family_file(self, table_name_or_slug: str) -> Path:
        return self._family_dir(table_name_or_slug) / FAMILY_FILENAME

    def _draft_dir(self, table_name_or_slug: str) -> Path:
        return self._family_dir(table_name_or_slug) / "draft"

    def _draft_manifest_path(self, table_name_or_slug: str) -> Path:
        return self._draft_dir(table_name_or_slug) / MANIFEST_FILENAME

    def _versions_dir(self, table_name_or_slug: str) -> Path:
        return self._family_dir(table_name_or_slug) / "versions"

    def _version_dir(self, table_name_or_slug: str, version_id: str) -> Path:
        return self._versions_dir(table_name_or_slug) / version_id

    def _version_manifest_path(self, table_name_or_slug: str, version_id: str) -> Path:
        return self._version_dir(table_name_or_slug, version_id) / MANIFEST_FILENAME

    def _runtime_capture_dir(self, table_name_or_slug: str) -> Path:
        return self._family_dir(table_name_or_slug) / RUNTIME_CAPTURE_DIRNAME

    def list_family_names(self) -> list[str]:
        names = []
        for family_dir in sorted(self.base_dir.iterdir()) if self.base_dir.exists() else []:
            if not family_dir.is_dir():
                continue
            try:
                family = _read_json(family_dir / FAMILY_FILENAME)
            except FileNotFoundError:
                continue
            names.append(family["display_name"])
        return names

    def find_related_family_names(self, table_name: str) -> list[str]:
        target = infer_supported_site(table_name)
        related = []
        for family_name in self.list_family_names():
            site = infer_supported_site(family_name)
            if target and site and site.key == target.key:
                related.append(family_name)
        return related

    def has_local_table(self, table_name: str) -> bool:
        family_file = self._family_file(table_name)
        return family_file.exists()

    def create_new_table(self, table_name: str, owner: str = COMPUTER_NAME) -> bool:
        family_dir = self._family_dir(table_name)
        if family_dir.exists():
            return False

        family_dir.mkdir(parents=True, exist_ok=True)
        family = {
            "display_name": table_name,
            "slug": self._family_slug(table_name),
            "owner": owner,
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "active_version_id": None,
            "candidate_version_id": None,
            "versions": [],
            "runtime_aliases": [table_name],
        }
        _write_json(family_dir / FAMILY_FILENAME, family)
        manifest = self._build_empty_manifest(table_name, owner=owner)
        self._write_manifest(self._draft_dir(table_name), manifest)
        return True

    def create_new_table_from_old(self, table_name: str, old_table_name: str, owner: str = COMPUTER_NAME) -> bool:
        if not self.create_new_table(table_name, owner=owner):
            return False

        if not self.has_local_table(old_table_name):
            return False

        source_manifest = self._load_manifest_for_edit(old_table_name)
        family = self._load_family(table_name)
        family["identity"] = copy.deepcopy(source_manifest.get("identity", {}))
        family["updated_at"] = _utc_now()
        _write_json(self._family_file(table_name), family)
        cloned_manifest = copy.deepcopy(source_manifest)
        cloned_manifest["display_name"] = table_name
        cloned_manifest["owner"] = owner
        cloned_manifest["lifecycle"]["status"] = "draft"
        cloned_manifest["lifecycle"]["version_id"] = None
        cloned_manifest["lifecycle"]["parent_version_id"] = source_manifest["lifecycle"].get("version_id")
        cloned_manifest["lifecycle"]["updated_at"] = _utc_now()
        cloned_manifest["reference_samples"] = []
        source_dir = self._manifest_dir_from_loaded_manifest(old_table_name, source_manifest)
        draft_dir = self._draft_dir(table_name)
        if draft_dir.exists():
            shutil.rmtree(draft_dir)
        shutil.copytree(source_dir, draft_dir)
        self._write_manifest(self._draft_dir(table_name), cloned_manifest)
        return True

    def delete_table(self, table_name: str) -> bool:
        family_dir = self._family_dir(table_name)
        if not family_dir.exists():
            return False
        shutil.rmtree(family_dir)
        return True

    def get_table_owner(self, table_name: str) -> str | None:
        if not self.has_local_table(table_name):
            return None
        family = self._load_family(table_name)
        return family.get("owner")

    def get_available_tables(self, computer_name: str | None = None) -> list[str]:
        return self.list_family_names()

    def update_identity(self, table_name: str, identity_updates: dict[str, Any]) -> dict[str, Any]:
        manifest = self._load_manifest_for_edit(table_name)
        identity = manifest.setdefault("identity", {})
        for key, value in identity_updates.items():
            if value is None:
                continue
            identity[key] = value
        manifest["lifecycle"]["updated_at"] = _utc_now()
        self._write_manifest(self._draft_dir(table_name), manifest)
        family = self._load_family(table_name)
        family["identity"] = copy.deepcopy(identity)
        family["updated_at"] = _utc_now()
        _write_json(self._family_file(table_name), family)
        return manifest

    def update_table_image(self, table_name: str, label: str, pil_image: Image.Image) -> bool:
        manifest = self._load_manifest_for_edit(table_name)
        image_bytes = _image_to_bytes(pil_image)
        relative_path = f"{ASSET_DIRNAME}/{label}.png"
        _save_image_bytes(self._draft_dir(table_name) / relative_path, image_bytes)
        manifest.setdefault("assets", {})[label] = relative_path
        manifest["fingerprint"] = self._build_manifest_fingerprint(manifest)
        manifest["lifecycle"]["updated_at"] = _utc_now()
        self._write_manifest(self._draft_dir(table_name), manifest)
        self._invalidate_cached_templates()
        return True

    def update_state(self, table_name: str, label: str, state: Any) -> bool:
        manifest = self._load_manifest_for_edit(table_name)
        table_data = manifest.setdefault("table_data", {})
        table_data[label] = state
        manifest["lifecycle"]["updated_at"] = _utc_now()
        self._write_manifest(self._draft_dir(table_name), manifest)
        return True

    def save_coordinates(self, table_name: str, label: str, coordinates_dict: dict[str, Any]) -> bool:
        manifest = self._load_manifest_for_edit(table_name)
        table_data = manifest.setdefault("table_data", {})
        _set_nested_mapping(table_data, label, _json_safe(coordinates_dict))
        manifest["lifecycle"]["updated_at"] = _utc_now()
        self._write_manifest(self._draft_dir(table_name), manifest)
        return True

    def update_tensorflow_model(
        self,
        table_name: str,
        hdf5_file: bytes | None,
        model_str: str | None,
        class_mapping: str | dict[str, Any] | None,
    ) -> bool:
        manifest = self._load_manifest_for_edit(table_name)
        nn = manifest.setdefault("nn", {})
        if model_str is not None:
            nn["model_json"] = model_str
        if class_mapping is not None:
            nn["class_mapping"] = class_mapping
        if hdf5_file:
            weights_path = f"{MODEL_DIRNAME}/weights.h5"
            _save_image_bytes(self._draft_dir(table_name) / weights_path, hdf5_file)
            nn["weights_path"] = weights_path
        manifest["lifecycle"]["updated_at"] = _utc_now()
        self._write_manifest(self._draft_dir(table_name), manifest)
        return True

    def load_table_nn_weights(self, table_name: str) -> bytes | None:
        manifest = self._load_manifest_for_runtime(table_name)
        weights_path = manifest.get("nn", {}).get("weights_path")
        if not weights_path:
            return None
        full_path = self._manifest_dir_from_loaded_manifest(table_name, manifest) / weights_path
        if not full_path.exists():
            return None
        return full_path.read_bytes()

    def load_table_image(self, table_name: str, image_name: str) -> Image.Image:
        manifest = self._load_manifest_for_edit(table_name)
        asset_path = manifest.get("assets", {}).get(image_name)
        if not asset_path:
            raise KeyError(image_name)
        return Image.open(self._manifest_dir_from_loaded_manifest(table_name, manifest) / asset_path)

    def get_table(self, table_name: str, prefer_draft: bool = True) -> dict[str, Any]:
        manifest = self._load_manifest_for_edit(table_name) if prefer_draft else self._load_manifest_for_runtime(table_name)
        return self._manifest_to_table_dict(table_name, manifest)

    def get_runtime_versions(self, table_name: str) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
        if not self.has_local_table(table_name):
            return []
        family = self._load_family(table_name)
        active_versions = []
        active_version_id = family.get("active_version_id")
        if active_version_id:
            manifest = self._load_manifest(self._version_manifest_path(table_name, active_version_id))
            active_versions.append((table_name, manifest, self._manifest_to_table_dict(table_name, manifest)))
        elif self._draft_manifest_path(table_name).exists():
            manifest = self._load_manifest(self._draft_manifest_path(table_name))
            active_versions.append((table_name, manifest, self._manifest_to_table_dict(table_name, manifest)))

        identity = active_versions[0][1].get("identity", {}) if active_versions else {}
        site_key = identity.get("site") or self._infer_site_key(table_name)

        for family_name in self.list_family_names():
            if family_name == table_name:
                continue
            other_family = self._load_family(family_name)
            other_active = other_family.get("active_version_id")
            if not other_active:
                continue
            other_manifest = self._load_manifest(self._version_manifest_path(family_name, other_active))
            other_site_key = other_manifest.get("identity", {}).get("site") or self._infer_site_key(family_name)
            if site_key and other_site_key == site_key:
                active_versions.append(
                    (
                        family_name,
                        other_manifest,
                        self._manifest_to_table_dict(family_name, other_manifest),
                    )
                )

        return active_versions

    def get_all_runtime_versions(self, exclude_names: set[str] | None = None) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
        exclude_names = exclude_names or set()
        active_versions = []
        for family_name in self.list_family_names():
            if family_name in exclude_names:
                continue
            other_family = self._load_family(family_name)
            other_active = other_family.get("active_version_id")
            if not other_active:
                continue
            other_manifest = self._load_manifest(self._version_manifest_path(family_name, other_active))
            active_versions.append(
                (
                    family_name,
                    other_manifest,
                    self._manifest_to_table_dict(family_name, other_manifest),
                )
            )
        return active_versions

    def list_versions(self, table_name: str) -> list[dict[str, Any]]:
        family = self._load_family(table_name)
        versions = []
        for version_id in family.get("versions", []):
            manifest_path = self._version_manifest_path(table_name, version_id)
            if not manifest_path.exists():
                continue
            manifest = self._load_manifest(manifest_path)
            validation = manifest.get("validation", {})
            versions.append(
                {
                    "version_id": version_id,
                    "published_at": manifest.get("lifecycle", {}).get("published_at"),
                    "status": validation.get("status", manifest.get("lifecycle", {}).get("status")),
                    "score": validation.get("live_pass_rate"),
                    "rollback_target": manifest.get("lifecycle", {}).get("rollback_target"),
                    "is_active": family.get("active_version_id") == version_id,
                    "is_candidate": family.get("candidate_version_id") == version_id,
                }
            )
        return versions

    def get_room_summary(self, table_name: str) -> dict[str, Any]:
        family = self._load_family(table_name)
        draft_manifest = None
        if self._draft_manifest_path(table_name).exists():
            draft_manifest = self._load_manifest(self._draft_manifest_path(table_name))

        active_manifest = None
        if family.get("active_version_id"):
            active_manifest = self._load_manifest(
                self._version_manifest_path(table_name, family["active_version_id"])
            )

        candidate_manifest = None
        if family.get("candidate_version_id"):
            candidate_manifest = self._load_manifest(
                self._version_manifest_path(table_name, family["candidate_version_id"])
            )

        current_manifest = draft_manifest or active_manifest or candidate_manifest
        return {
            "family": copy.deepcopy(family),
            "draft": copy.deepcopy(draft_manifest) if draft_manifest else None,
            "active": copy.deepcopy(active_manifest) if active_manifest else None,
            "candidate": copy.deepcopy(candidate_manifest) if candidate_manifest else None,
            "current": copy.deepcopy(current_manifest) if current_manifest else None,
            "versions": self.list_versions(table_name),
        }

    def compare_versions(self, table_name: str, version_a: str, version_b: str) -> dict[str, Any]:
        manifest_a = self._load_manifest(self._version_manifest_path(table_name, version_a))
        manifest_b = self._load_manifest(self._version_manifest_path(table_name, version_b))
        keys_a = _flatten_nested_keys(manifest_a.get("table_data", {}))
        keys_b = _flatten_nested_keys(manifest_b.get("table_data", {}))
        assets_a = set(manifest_a.get("assets", {}))
        assets_b = set(manifest_b.get("assets", {}))
        return {
            "version_a": version_a,
            "version_b": version_b,
            "changed_keys": sorted(keys_a.symmetric_difference(keys_b)),
            "changed_assets": sorted(assets_a.symmetric_difference(assets_b)),
        }

    def rollback_to_version(self, table_name: str, version_id: str) -> bool:
        family = self._load_family(table_name)
        if version_id not in family.get("versions", []):
            raise RuntimeError(f"Unknown version {version_id} for {table_name}")
        family["active_version_id"] = version_id
        family["updated_at"] = _utc_now()
        _write_json(self._family_file(table_name), family)
        return True

    def validate(self, table_name: str, live_screenshots: list[Image.Image] | None = None, use_draft: bool = True) -> ValidationResult:
        manifest = self._load_manifest_for_edit(table_name) if use_draft else self._load_manifest_for_runtime(table_name)
        table_dict = self._manifest_to_table_dict(table_name, manifest)
        issues = []

        for key in MANDATORY_ASSET_LABELS:
            if key not in manifest.get("assets", {}):
                issues.append(f"Missing mandatory asset: {key}")
        for key in MANDATORY_COORDINATES:
            if key not in manifest.get("table_data", {}):
                issues.append(f"Missing mandatory mapping: {key}")

        golden_scores = []
        for sample in manifest.get("reference_samples", []):
            sample_path = self._manifest_dir_from_loaded_manifest(table_name, manifest) / sample["path"]
            if not sample_path.exists():
                issues.append(f"Missing reference sample file: {sample['path']}")
                golden_scores.append(0.0)
                continue
            sample_image = Image.open(sample_path)
            golden_scores.append(self._score_screenshot_against_table(table_dict, sample_image, sample=sample))

        live_reference_sample = manifest.get("reference_samples", [None])[0] if manifest.get("reference_samples") else None
        live_scores = [
            self._score_screenshot_against_table(table_dict, screenshot, sample=live_reference_sample)
            for screenshot in (live_screenshots or [])
        ]

        golden_pass_rate = min(golden_scores) if golden_scores else 1.0
        live_pass_rate = sum(live_scores) / len(live_scores) if live_scores else golden_pass_rate
        critical_anchor_score = self._score_critical_anchors(table_dict, (live_screenshots or [None])[0])

        if issues:
            status = "red"
        elif golden_pass_rate == 1.0 and live_pass_rate >= 0.95 and critical_anchor_score == 1.0:
            status = "green"
        elif critical_anchor_score == 1.0 and 0.80 <= live_pass_rate < 0.95:
            status = "yellow"
        else:
            status = "red"

        result = ValidationResult(
            status=status,
            golden_pass_rate=golden_pass_rate,
            live_pass_rate=live_pass_rate,
            critical_anchor_score=critical_anchor_score,
            issues=issues,
            evaluated_samples=len(golden_scores) + len(live_scores),
        )
        manifest["validation"] = result.as_dict()
        manifest["lifecycle"]["updated_at"] = _utc_now()
        if use_draft:
            self._write_manifest(self._draft_dir(table_name), manifest)
        else:
            self._write_manifest(self._manifest_dir_from_loaded_manifest(table_name, manifest), manifest)
        return result

    def publish_draft(
        self,
        table_name: str,
        screenshots: list[Image.Image] | None = None,
        ai_suggestion: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        manifest = self._load_manifest_for_edit(table_name)
        if ai_suggestion:
            manifest.setdefault("ai_assist", {})["last_suggestion"] = ai_suggestion
        if screenshots:
            manifest["reference_samples"] = self._build_reference_samples(table_name, manifest, screenshots)
        validation = self.validate(table_name, live_screenshots=screenshots or [], use_draft=True)
        manifest = self._load_manifest_for_edit(table_name)

        if validation.status == "red":
            raise RuntimeError("Preset validation failed. Fix the draft before publishing.")

        family = self._load_family(table_name)
        current_active = family.get("active_version_id")
        version_id = self._next_version_id(family.get("versions", []))
        manifest["lifecycle"].update(
            {
                "status": "published" if validation.status == "green" else "candidate",
                "version_id": version_id,
                "parent_version_id": current_active,
                "published_at": _utc_now(),
                "rollback_target": current_active,
            }
        )
        version_dir = self._version_dir(table_name, version_id)
        if version_dir.exists():
            shutil.rmtree(version_dir)
        shutil.copytree(self._draft_dir(table_name), version_dir)
        self._write_manifest(version_dir, manifest)
        family["versions"] = list(dict.fromkeys(family.get("versions", []) + [version_id]))
        family["updated_at"] = _utc_now()
        if validation.status == "green":
            family["active_version_id"] = version_id
        else:
            family["candidate_version_id"] = version_id
        family["identity"] = copy.deepcopy(manifest.get("identity", {}))
        _write_json(self._family_file(table_name), family)
        self._reset_draft_from_version(table_name, version_id)
        return {
            "version_id": version_id,
            "status": validation.status,
            "active_version_id": family.get("active_version_id"),
        }

    def sync_to_remote(self, table_name: str, remote_sync: RemotePresetSync | None) -> bool:
        if remote_sync is None:
            return False
        table_dict = self.get_table(table_name, prefer_draft=False)
        owner = self.get_table_owner(table_name) or COMPUTER_NAME
        return remote_sync.push_table(table_name, table_dict, owner)

    def import_remote_table(self, table_name: str, remote_sync: RemotePresetSync) -> dict[str, Any] | None:
        remote_table = remote_sync.fetch_table(table_name)
        if not self.has_local_table(table_name):
            self.create_new_table(table_name, owner=remote_sync.get_table_owner(table_name) or COMPUTER_NAME)
        manifest = self._load_manifest_for_edit(table_name)
        imported = self._manifest_from_table_dict(table_name, remote_table, owner=self.get_table_owner(table_name) or COMPUTER_NAME)
        imported["identity"] = manifest.get("identity", imported.get("identity", {}))
        self._write_manifest(self._draft_dir(table_name), imported)
        publish_result = self.publish_draft(table_name, screenshots=[])
        log.info("Imported remote preset %s into local storage as %s", table_name, publish_result["version_id"])
        return self.get_table(table_name, prefer_draft=False)

    def resolve_runtime_table(self, table_name: str, screenshot: Image.Image | None = None) -> tuple[dict[str, Any], RuntimeResolution]:
        if not screenshot or not self.has_local_table(table_name):
            table_dict = self.get_table(table_name, prefer_draft=False)
            manifest = self._load_manifest_for_runtime(table_name)
            version_id = manifest.get("lifecycle", {}).get("version_id")
            return table_dict, RuntimeResolution(
                table_name=table_name,
                resolved_table_name=table_name,
                family_slug=self._family_slug(table_name),
                version_id=version_id,
                score=1.0,
                fingerprint_hash=manifest.get("fingerprint", {}).get("hash", ""),
            )

        best_match = None
        candidates = self.get_runtime_versions(table_name)
        for candidate_name, manifest, table_dict in candidates:
            score, fingerprint_hash, diagnostics = self._score_runtime_candidate(table_dict, screenshot)
            if best_match is None or score > best_match[0]:
                best_match = (score, fingerprint_hash, diagnostics, candidate_name, manifest, table_dict)

        if best_match is None:
            table_dict = self.get_table(table_name, prefer_draft=False)
            return table_dict, RuntimeResolution(
                table_name=table_name,
                resolved_table_name=table_name,
                family_slug=self._family_slug(table_name),
                version_id=None,
                score=0.0,
                fingerprint_hash="",
                diagnostics=["No runtime candidate matched the current screenshot."],
            )

        requested_candidate_names = {candidate_name for candidate_name, _, _ in candidates}
        if best_match[0] < 0.75:
            fallback_candidates = self.get_all_runtime_versions(exclude_names=requested_candidate_names)
            for candidate_name, manifest, table_dict in fallback_candidates:
                score, fingerprint_hash, diagnostics = self._score_runtime_candidate(table_dict, screenshot)
                if best_match is None or score > best_match[0]:
                    diagnostics = list(diagnostics)
                    diagnostics.append(
                        f"Resolved outside the requested preset family after scanning all local presets from {table_name}."
                    )
                    best_match = (score, fingerprint_hash, diagnostics, candidate_name, manifest, table_dict)

        score, fingerprint_hash, diagnostics, resolved_name, manifest, table_dict = best_match
        resolution = RuntimeResolution(
            table_name=table_name,
            resolved_table_name=resolved_name,
            family_slug=self._family_slug(resolved_name),
            version_id=manifest.get("lifecycle", {}).get("version_id"),
            score=score,
            fingerprint_hash=fingerprint_hash,
            diagnostics=diagnostics,
        )
        return table_dict, resolution

    def observe_runtime_drift(self, table_name: str, screenshot: Image.Image) -> DriftResult:
        if not self.has_local_table(table_name):
            return DriftResult(status="red", table_name=table_name, score=0.0, diagnostics=["No local preset available."])

        runtime_manifest = self._load_manifest_for_runtime(table_name)
        runtime_table = self._manifest_to_table_dict(table_name, runtime_manifest)
        capture_path = self._store_runtime_capture(table_name, screenshot)
        validation = self.validate(table_name, live_screenshots=[screenshot], use_draft=False)
        diagnostics = [f"Runtime capture saved to {capture_path.name}"]
        diagnostics.extend(validation.issues)

        if validation.status == "green":
            new_version = self._create_auto_update_version(table_name, runtime_manifest, runtime_table, screenshot, validation)
            diagnostics.append(f"Auto-updated preset activated as version {new_version}.")
            return DriftResult("green", table_name, validation.live_pass_rate, version_id=new_version, diagnostics=diagnostics)
        if validation.status == "yellow":
            candidate_version = self._create_auto_update_version(
                table_name,
                runtime_manifest,
                runtime_table,
                screenshot,
                validation,
                candidate_only=True,
            )
            diagnostics.append(f"Candidate version created: {candidate_version}.")
            return DriftResult("yellow", table_name, validation.live_pass_rate, version_id=candidate_version, diagnostics=diagnostics)
        diagnostics.append("Critical anchors failed; no automatic update was applied.")
        return DriftResult("red", table_name, validation.live_pass_rate, version_id=None, diagnostics=diagnostics)

    def _create_auto_update_version(
        self,
        table_name: str,
        runtime_manifest: dict[str, Any],
        runtime_table: dict[str, Any],
        screenshot: Image.Image,
        validation: ValidationResult,
        candidate_only: bool = False,
    ) -> str:
        family = self._load_family(table_name)
        updated_table = copy.deepcopy(runtime_table)
        refreshed_assets = self._refresh_template_assets(updated_table, screenshot)
        updated_table.update(refreshed_assets)
        version_id = self._next_version_id(family.get("versions", []))
        version_dir = self._version_dir(table_name, version_id)
        if version_dir.exists():
            shutil.rmtree(version_dir)
        version_dir.mkdir(parents=True, exist_ok=True)
        manifest = self._manifest_from_table_dict(
            table_name,
            updated_table,
            owner=self.get_table_owner(table_name) or COMPUTER_NAME,
            target_dir=version_dir,
        )
        manifest["identity"] = copy.deepcopy(runtime_manifest.get("identity", {}))
        manifest["reference_samples"] = self._build_reference_samples(
            table_name,
            manifest,
            [screenshot],
            target_dir=version_dir,
            table_dict_override=updated_table,
        )
        manifest["validation"] = validation.as_dict()
        manifest["lifecycle"].update(
            {
                "status": "candidate" if candidate_only else "published",
                "version_id": version_id,
                "parent_version_id": family.get("active_version_id"),
                "published_at": _utc_now(),
                "rollback_target": family.get("active_version_id"),
            }
        )
        self._write_manifest(version_dir, manifest)
        family["versions"] = list(dict.fromkeys(family.get("versions", []) + [version_id]))
        family["updated_at"] = _utc_now()
        if candidate_only:
            family["candidate_version_id"] = version_id
        else:
            family["active_version_id"] = version_id
        _write_json(self._family_file(table_name), family)
        return version_id

    def _refresh_template_assets(self, table_dict: dict[str, Any], screenshot: Image.Image) -> dict[str, bytes]:
        cropped, _ = _crop_with_topleft_corner(screenshot, table_dict["topleft_corner"])
        if not cropped:
            return {}

        refreshed_assets = {}
        for label in CRITICAL_TEMPLATE_LABELS + OPTIONAL_TEMPLATE_LABELS:
            if label not in table_dict:
                continue
            search_area_name = "buttons_search_area"
            if label == "dealer_button":
                search_area_name = "button_search_area"
            elif label == "covered_card":
                search_area_name = "covered_card_area"
            search_area = table_dict.get(search_area_name)
            if not search_area:
                continue
            if isinstance(search_area, dict) and "x1" not in search_area:
                search_area = search_area.get("1") or next(iter(search_area.values()), None)
            if not search_area:
                continue
            template = Image.open(io.BytesIO(table_dict[label]))
            template_cv2 = _template_to_internal(table_dict[label])
            cropped_area = cropped.crop((search_area["x1"], search_area["y1"], search_area["x2"], search_area["y2"]))
            cropped_area_cv2 = _template_to_internal(_image_to_bytes(cropped_area))
            _, _, best_fit, _ = _find_template(template_cv2, cropped_area_cv2, 0.05)
            if best_fit is None:
                continue
            x, y = best_fit
            refreshed = cropped_area.crop((x, y, x + template.width, y + template.height))
            refreshed_assets[label] = _image_to_bytes(refreshed)
        return refreshed_assets

    def _score_runtime_candidate(self, table_dict: dict[str, Any], screenshot: Image.Image) -> tuple[float, str, list[str]]:
        diagnostics = []
        try:
            cropped, _ = _crop_with_topleft_corner(screenshot, table_dict["topleft_corner"])
        except Exception as exc:
            return 0.0, "", [f"Top-left detection failed: {exc}"]

        if not cropped:
            return 0.0, "", ["Top-left corner was not found for this candidate."]

        anchor_score = self._score_critical_anchors(table_dict, screenshot)
        if anchor_score == 0:
            diagnostics.append("Critical anchors were not found in the current screenshot.")

        fingerprint_hash = _hash_image(cropped.resize((320, 240)))
        return round(anchor_score, 4), fingerprint_hash, diagnostics

    def _score_critical_anchors(self, table_dict: dict[str, Any], screenshot: Image.Image | None) -> float:
        if screenshot is None:
            return 1.0
        try:
            cropped, _ = _crop_with_topleft_corner(screenshot, table_dict["topleft_corner"])
        except Exception:
            return 0.0

        if not cropped:
            return 0.0

        checks = []
        for label in CRITICAL_TEMPLATE_LABELS:
            if label not in table_dict:
                continue
            area_name = "buttons_search_area"
            player = None
            if label == "dealer_button":
                area_name = "button_search_area"
                player = "1" if isinstance(table_dict.get(area_name), dict) and "x1" not in table_dict.get(area_name, {}) else None
            elif label == "covered_card":
                area_name = "covered_card_area"
                player = "1" if isinstance(table_dict.get(area_name), dict) and "x1" not in table_dict.get(area_name, {}) else None
            try:
                checks.append(
                    1.0
                    if _template_in_search_area(table_dict, cropped, label, area_name, player=player)
                    else 0.0
                )
            except Exception:
                checks.append(0.0)
        return sum(checks) / len(checks) if checks else 0.0

    def _score_screenshot_against_table(
        self,
        table_dict: dict[str, Any],
        screenshot: Image.Image,
        sample: dict[str, Any] | None = None,
    ) -> float:
        try:
            cropped, _ = _crop_with_topleft_corner(screenshot, table_dict["topleft_corner"])
        except Exception:
            return 0.0
        if not cropped:
            return 0.0

        checks = []
        expected_assets = sample.get("expected_assets", []) if sample else list(CRITICAL_TEMPLATE_LABELS)
        for label in expected_assets:
            area_name = "buttons_search_area"
            player = None
            if label == "dealer_button":
                area_name = "button_search_area"
                player = "1" if isinstance(table_dict.get(area_name), dict) and "x1" not in table_dict.get(area_name, {}) else None
            elif label == "covered_card":
                area_name = "covered_card_area"
                player = "1" if isinstance(table_dict.get(area_name), dict) and "x1" not in table_dict.get(area_name, {}) else None
            try:
                found = _template_in_search_area(table_dict, cropped, label, area_name, player=player)
            except Exception:
                found = False
            checks.append(1.0 if found else 0.0)

        for area in (sample or {}).get("expected_numeric_areas", []):
            try:
                checks.append(1.0 if _ocr_float(cropped.crop(self._coords_to_tuple(table_dict[area]))) != -1.0 else 0.0)
            except Exception:
                checks.append(0.0)

        return sum(checks) / len(checks) if checks else 0.0

    @staticmethod
    def _coords_to_tuple(coords: dict[str, Any]) -> tuple[int, int, int, int]:
        return coords["x1"], coords["y1"], coords["x2"], coords["y2"]

    def _build_reference_samples(
        self,
        table_name: str,
        manifest: dict[str, Any],
        screenshots: list[Image.Image],
        target_dir: Path | None = None,
        table_dict_override: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        manifest_dir = target_dir or self._draft_dir(table_name)
        sample_dir = manifest_dir / SAMPLE_DIRNAME
        if sample_dir.exists():
            shutil.rmtree(sample_dir)
        sample_dir.mkdir(parents=True, exist_ok=True)

        table_dict = table_dict_override or self._manifest_to_table_dict(table_name, manifest)
        samples = []
        for idx, screenshot in enumerate(screenshots):
            sample_name = f"sample_{idx:03d}.png"
            sample_path = sample_dir / sample_name
            screenshot.save(sample_path)
            expected_assets = []
            expected_numeric_areas = []
            try:
                cropped, _ = _crop_with_topleft_corner(screenshot, table_dict["topleft_corner"])
            except Exception:
                cropped = None
            if cropped:
                for label in CRITICAL_TEMPLATE_LABELS + OPTIONAL_TEMPLATE_LABELS:
                    if label not in table_dict:
                        continue
                    area_name = "buttons_search_area"
                    player = None
                    if label == "dealer_button":
                        area_name = "button_search_area"
                        player = "1" if isinstance(table_dict.get(area_name), dict) and "x1" not in table_dict.get(area_name, {}) else None
                    elif label == "covered_card":
                        area_name = "covered_card_area"
                        player = "1" if isinstance(table_dict.get(area_name), dict) and "x1" not in table_dict.get(area_name, {}) else None
                    try:
                        if _template_in_search_area(table_dict, cropped, label, area_name, player=player):
                            expected_assets.append(label)
                    except Exception:
                        continue
                for area_name in NUMERIC_AREAS:
                    if area_name not in table_dict:
                        continue
                    try:
                        value = _ocr_float(cropped.crop(self._coords_to_tuple(table_dict[area_name])))
                    except Exception:
                        value = -1.0
                    if value != -1.0:
                        expected_numeric_areas.append(area_name)

            samples.append(
                {
                    "path": f"{SAMPLE_DIRNAME}/{sample_name}",
                    "created_at": _utc_now(),
                    "expected_assets": expected_assets,
                    "expected_numeric_areas": expected_numeric_areas,
                }
            )
        return samples

    def _store_runtime_capture(self, table_name: str, screenshot: Image.Image) -> Path:
        capture_dir = self._runtime_capture_dir(table_name)
        capture_dir.mkdir(parents=True, exist_ok=True)
        capture_name = f"capture_{int(time.time())}.png"
        capture_path = capture_dir / capture_name
        screenshot.save(capture_path)
        captures = sorted(capture_dir.glob("capture_*.png"))
        for stale in captures[:-MAX_RUNTIME_CAPTURES]:
            stale.unlink(missing_ok=True)
        return capture_path

    def _next_version_id(self, existing_versions: list[str]) -> str:
        return f"v{len(existing_versions) + 1:04d}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    def _reset_draft_from_version(self, table_name: str, version_id: str) -> None:
        version_dir = self._version_dir(table_name, version_id)
        draft_dir = self._draft_dir(table_name)
        if draft_dir.exists():
            shutil.rmtree(draft_dir)
        shutil.copytree(version_dir, draft_dir)
        manifest = self._load_manifest(self._draft_manifest_path(table_name))
        manifest["lifecycle"]["status"] = "draft"
        manifest["lifecycle"]["version_id"] = None
        manifest["lifecycle"]["updated_at"] = _utc_now()
        self._write_manifest(draft_dir, manifest)

    def _build_empty_manifest(self, table_name: str, owner: str) -> dict[str, Any]:
        site = infer_supported_site(table_name)
        return {
            "schema_version": SCHEMA_VERSION,
            "display_name": table_name,
            "owner": owner,
            "identity": {
                "site": site.key if site else _slugify(table_name),
                "network": site.display_name if site else table_name,
                "skin": table_name,
                "variant": "",
                "max_players": 6,
                "theme": "",
                "table_size": "default",
                "hero_seat": "bottom-right",
                "cash_or_tournament": "cash",
                "real_or_play": "real",
            },
            "table_data": {
                "table_name": table_name,
                "max_players": {"value": 6},
            },
            "assets": {},
            "nn": {},
            "reference_samples": [],
            "validation": ValidationResult(
                status="red",
                golden_pass_rate=0.0,
                live_pass_rate=0.0,
                critical_anchor_score=0.0,
                issues=["Draft not validated yet."],
                evaluated_samples=0,
            ).as_dict(),
            "fingerprint": {
                "hash": "",
                "site_key": site.key if site else _slugify(table_name),
                "asset_hashes": {},
            },
            "lifecycle": {
                "status": "draft",
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
                "published_at": None,
                "version_id": None,
                "parent_version_id": None,
                "rollback_target": None,
            },
            "ai_assist": {
                "provider": "local",
            },
        }

    def _build_manifest_fingerprint(self, manifest: dict[str, Any], manifest_dir_override: Path | None = None) -> dict[str, Any]:
        asset_hashes = {}
        manifest_dir = manifest_dir_override or (
            self._draft_dir(manifest["display_name"])
            if manifest["lifecycle"]["status"] == "draft"
            else self._manifest_dir_from_loaded_manifest(manifest["display_name"], manifest)
        )
        for label, relative_path in manifest.get("assets", {}).items():
            full_path = manifest_dir / relative_path
            if full_path.exists():
                asset_hashes[label] = _hash_bytes(full_path.read_bytes())
        raw = json.dumps(
            {
                "identity": manifest.get("identity", {}),
                "table_data": manifest.get("table_data", {}),
                "asset_hashes": asset_hashes,
            },
            sort_keys=True,
        ).encode("utf-8")
        return {
            "hash": _hash_bytes(raw),
            "site_key": manifest.get("identity", {}).get("site"),
            "asset_hashes": asset_hashes,
        }

    def _manifest_from_table_dict(
        self,
        table_name: str,
        table_dict: dict[str, Any],
        owner: str,
        target_dir: Path | None = None,
    ) -> dict[str, Any]:
        manifest = self._build_empty_manifest(table_name, owner=owner)
        manifest["table_data"] = {}
        manifest["assets"] = {}
        manifest["nn"] = {}
        target_dir = target_dir or self._draft_dir(table_name)
        for key, value in table_dict.items():
            if key == "table_name":
                continue
            if isinstance(value, bytes):
                relative_path = f"{ASSET_DIRNAME}/{key}.png"
                manifest["assets"][key] = relative_path
                _save_image_bytes(target_dir / relative_path, value)
            elif key == "_model":
                manifest["nn"]["model_json"] = value
            elif key == "_class_mapping":
                manifest["nn"]["class_mapping"] = value
            else:
                manifest["table_data"][key] = _json_safe(value)
        manifest["fingerprint"] = self._build_manifest_fingerprint(manifest, manifest_dir_override=target_dir)
        return manifest

    def _manifest_to_table_dict(self, table_name: str, manifest: dict[str, Any]) -> dict[str, Any]:
        table_dict = copy.deepcopy(manifest.get("table_data", {}))
        table_dict["table_name"] = table_name
        manifest_dir = self._manifest_dir_from_loaded_manifest(table_name, manifest)
        for label, relative_path in manifest.get("assets", {}).items():
            full_path = manifest_dir / relative_path
            if full_path.exists():
                table_dict[label] = _load_image_bytes(full_path)
        model_json = manifest.get("nn", {}).get("model_json")
        if model_json is not None:
            table_dict["_model"] = model_json
        class_mapping = manifest.get("nn", {}).get("class_mapping")
        if class_mapping is not None:
            table_dict["_class_mapping"] = class_mapping
        return table_dict

    def _manifest_dir_from_loaded_manifest(self, table_name: str, manifest: dict[str, Any]) -> Path:
        lifecycle = manifest.get("lifecycle", {})
        version_id = lifecycle.get("version_id")
        if version_id:
            return self._version_dir(table_name, version_id)
        return self._draft_dir(table_name)

    def _load_family(self, table_name_or_slug: str) -> dict[str, Any]:
        return _read_json(self._family_file(table_name_or_slug))

    def _load_manifest(self, manifest_path: Path) -> dict[str, Any]:
        return _read_json(manifest_path)

    def _load_manifest_for_edit(self, table_name: str) -> dict[str, Any]:
        draft_path = self._draft_manifest_path(table_name)
        if draft_path.exists():
            return self._load_manifest(draft_path)
        return self._load_manifest_for_runtime(table_name)

    def _load_manifest_for_runtime(self, table_name: str) -> dict[str, Any]:
        family = self._load_family(table_name)
        active_version_id = family.get("active_version_id")
        if active_version_id:
            return self._load_manifest(self._version_manifest_path(table_name, active_version_id))
        draft_path = self._draft_manifest_path(table_name)
        if draft_path.exists():
            return self._load_manifest(draft_path)
        raise RuntimeError(f"No active or draft preset found for {table_name}")

    def _write_manifest(self, manifest_dir: Path, manifest: dict[str, Any]) -> None:
        manifest = copy.deepcopy(manifest)
        manifest["fingerprint"] = self._build_manifest_fingerprint(manifest)
        _write_json(manifest_dir / MANIFEST_FILENAME, manifest)

    @staticmethod
    def _infer_site_key(table_name: str) -> str | None:
        site = infer_supported_site(table_name)
        return site.key if site else None

    @staticmethod
    def _invalidate_cached_templates() -> None:
        try:
            from poker.tools.screen_operations import load_table_template_cached

            load_table_template_cached.cache.clear()  # type: ignore[attr-defined]
        except Exception:
            pass


class HybridPresetRepository:
    """Hybrid local-first preset repository with optional remote compatibility."""

    def __init__(
        self,
        local_repository: LocalPresetRepository | None = None,
        remote_sync: RemotePresetSync | None = None,
    ):
        self.local_repository = local_repository or LocalPresetRepository()
        self.remote_sync = remote_sync
        self.ai_provider = build_ai_assist_provider(self)

    def refresh_ai_provider(self, settings: dict[str, Any] | None = None) -> AiAssistProvider:
        self.ai_provider = build_ai_assist_provider(self, settings=settings)
        return self.ai_provider

    def get_available_tables(self, computer_name: str = COMPUTER_NAME) -> list[str]:
        local_tables = self.local_repository.get_available_tables(computer_name)
        remote_tables = self.remote_sync.get_available_tables(computer_name) if self.remote_sync else []
        ordered = []
        seen = set()
        for name in local_tables + remote_tables:
            if name not in seen:
                seen.add(name)
                ordered.append(name)
        return ordered

    def get_room_summary(self, table_name: str) -> dict[str, Any]:
        if not self.local_repository.has_local_table(table_name):
            if self.remote_sync:
                self._ensure_local_copy(table_name)
            else:
                raise RuntimeError(f"No preset found for {table_name}")
        summary = self.local_repository.get_room_summary(table_name)
        summary["ai_settings"] = read_room_manager_settings()
        return summary

    def get_table(self, table_name: str, prefer_draft: bool = True) -> dict[str, Any]:
        if self.local_repository.has_local_table(table_name):
            return self.local_repository.get_table(table_name, prefer_draft=prefer_draft)
        if self.remote_sync:
            return self.remote_sync.fetch_table(table_name)
        raise RuntimeError(f"No preset found for {table_name}")

    def get_runtime_table(self, table_name: str, screenshot: Image.Image | None = None) -> tuple[dict[str, Any], RuntimeResolution]:
        if self.local_repository.has_local_table(table_name):
            return self.local_repository.resolve_runtime_table(table_name, screenshot=screenshot)
        table_dict = self.get_table(table_name, prefer_draft=False)
        return table_dict, RuntimeResolution(
            table_name=table_name,
            resolved_table_name=table_name,
            family_slug=None,
            version_id=None,
            score=1.0,
            fingerprint_hash="",
            diagnostics=["Using legacy remote preset without local runtime variants."],
        )

    def get_table_owner(self, table_name: str) -> str | None:
        if self.local_repository.has_local_table(table_name):
            return self.local_repository.get_table_owner(table_name)
        return self.remote_sync.get_table_owner(table_name) if self.remote_sync else None

    def create_new_table(self, table_name: str, owner: str = COMPUTER_NAME) -> bool:
        return self.local_repository.create_new_table(table_name, owner=owner)

    def create_new_table_from_old(self, table_name: str, old_table_name: str, owner: str = COMPUTER_NAME) -> bool:
        if self.local_repository.has_local_table(old_table_name):
            return self.local_repository.create_new_table_from_old(table_name, old_table_name, owner=owner)
        if self.remote_sync:
            remote_table = self.remote_sync.fetch_table(old_table_name)
            if not self.local_repository.create_new_table(table_name, owner=owner):
                return False
            manifest = self.local_repository._manifest_from_table_dict(table_name, remote_table, owner=owner)
            self.local_repository._write_manifest(self.local_repository._draft_dir(table_name), manifest)
            return True
        return False

    def delete_table(self, table_name: str) -> bool:
        if self.local_repository.has_local_table(table_name):
            return self.local_repository.delete_table(table_name)
        return False

    def update_table_image(self, table_name: str, label: str, pil_image: Image.Image) -> bool:
        if not self.local_repository.has_local_table(table_name):
            self._ensure_local_copy(table_name)
        return self.local_repository.update_table_image(table_name, label, pil_image)

    def update_state(self, table_name: str, label: str, state: Any) -> bool:
        if not self.local_repository.has_local_table(table_name):
            self._ensure_local_copy(table_name)
        return self.local_repository.update_state(table_name, label, state)

    def save_coordinates(self, table_name: str, label: str, coordinates_dict: dict[str, Any]) -> bool:
        if not self.local_repository.has_local_table(table_name):
            self._ensure_local_copy(table_name)
        return self.local_repository.save_coordinates(table_name, label, coordinates_dict)

    def update_tensorflow_model(self, table_name: str, hdf5_file: bytes | None, model_str: str | None, class_mapping: Any) -> bool:
        if not self.local_repository.has_local_table(table_name):
            self._ensure_local_copy(table_name)
        return self.local_repository.update_tensorflow_model(table_name, hdf5_file, model_str, class_mapping)

    def load_table_nn_weights(self, table_name: str) -> bytes | None:
        if self.local_repository.has_local_table(table_name):
            return self.local_repository.load_table_nn_weights(table_name)
        return None

    def load_table_image(self, table_name: str, image_name: str) -> Image.Image:
        if self.local_repository.has_local_table(table_name):
            return self.local_repository.load_table_image(table_name, image_name)
        if self.remote_sync:
            remote_table = self.remote_sync.fetch_table(table_name)
            return Image.open(io.BytesIO(remote_table[image_name]))
        raise KeyError(image_name)

    def validate(self, table_name: str, live_screenshots: list[Image.Image] | None = None, use_draft: bool = True) -> ValidationResult:
        if not self.local_repository.has_local_table(table_name):
            self._ensure_local_copy(table_name)
        return self.local_repository.validate(table_name, live_screenshots=live_screenshots, use_draft=use_draft)

    def publish_draft(self, table_name: str, screenshots: list[Image.Image] | None = None) -> dict[str, Any]:
        if not self.local_repository.has_local_table(table_name):
            self._ensure_local_copy(table_name)
        manifest = self.local_repository._load_manifest_for_edit(table_name)
        ai_suggestion = self.ai_provider.suggest(table_name, screenshots or [], manifest)
        return self.local_repository.publish_draft(table_name, screenshots=screenshots, ai_suggestion=ai_suggestion)

    def suggest(self, table_name: str, screenshots: list[Image.Image] | None = None) -> dict[str, Any]:
        if not self.local_repository.has_local_table(table_name):
            self._ensure_local_copy(table_name)
        manifest = self.local_repository._load_manifest_for_edit(table_name)
        return self.ai_provider.suggest(table_name, screenshots or [], manifest)

    def list_versions(self, table_name: str) -> list[dict[str, Any]]:
        return self.local_repository.list_versions(table_name)

    def compare_versions(self, table_name: str, version_a: str, version_b: str) -> dict[str, Any]:
        return self.local_repository.compare_versions(table_name, version_a, version_b)

    def rollback_to_version(self, table_name: str, version_id: str) -> bool:
        return self.local_repository.rollback_to_version(table_name, version_id)

    def update_identity(self, table_name: str, identity_updates: dict[str, Any]) -> dict[str, Any]:
        if not self.local_repository.has_local_table(table_name):
            self._ensure_local_copy(table_name)
        return self.local_repository.update_identity(table_name, identity_updates)

    def sync_to_remote(self, table_name: str) -> bool:
        return self.local_repository.sync_to_remote(table_name, self.remote_sync)

    def import_remote_table(self, table_name: str) -> dict[str, Any] | None:
        if not self.remote_sync:
            return None
        return self.local_repository.import_remote_table(table_name, self.remote_sync)

    def observe_runtime_drift(self, table_name: str, screenshot: Image.Image) -> DriftResult:
        if not self.local_repository.has_local_table(table_name):
            return DriftResult(
                status="red",
                table_name=table_name,
                score=0.0,
                diagnostics=["Drift watcher requires a local preset family."],
            )
        return self.local_repository.observe_runtime_drift(table_name, screenshot)

    def _ensure_local_copy(self, table_name: str) -> None:
        if self.local_repository.has_local_table(table_name):
            return
        if not self.remote_sync:
            self.local_repository.create_new_table(table_name)
            return
        self.local_repository.import_remote_table(table_name, self.remote_sync)


def get_preset_repository(remote_sync: RemotePresetSync | None = None) -> HybridPresetRepository:
    global _PRESET_REPOSITORY  # pylint: disable=global-statement
    if _PRESET_REPOSITORY is None:
        _PRESET_REPOSITORY = HybridPresetRepository(remote_sync=remote_sync)
    elif remote_sync is not None:
        _PRESET_REPOSITORY.remote_sync = remote_sync
    return _PRESET_REPOSITORY


def clear_preset_repository_cache() -> None:
    global _PRESET_REPOSITORY  # pylint: disable=global-statement
    _PRESET_REPOSITORY = None
