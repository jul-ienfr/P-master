"""F-04 — garde-fou : `config.json` versionné ne doit contenir aucun secret en clair.

`config.json` est suivi par git (l'audit du 17/11/2026, constat F-04) : toute clé
API ou identifiant qui y serait écrit serait commité. Les secrets attendus
passent par des placeholders d'environnement (``${VAR:-défaut}``) ou des chaînes
vides ; ce test échoue si une valeur ressemble à un secret réel.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONFIG_PATH = ROOT / "config.json"

# Valeurs autorisées : placeholder d'environnement, vide, ou défaut manifestement
# factice (`__CHANGE_ME__`). Toute autre valeur non vide sur une clé sensible est
# un échec.
_SENSITIVE_KEY = re.compile(
    r"(api[_-]?key|secret|token|password|passwd|credential|private[_-]?key|dsn|webhook)",
    re.IGNORECASE,
)
_ENV_PLACEHOLDER = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*(?::-[^}]*)?\}$")
_PLACEHOLDER_MARKERS = ("__CHANGE_ME__", "change_me", "your_", "<", "xxx")


def _iter_sensitive_values(node, path="$"):
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}"
            if _SENSITIVE_KEY.search(str(key)) and isinstance(value, str):
                yield child, value
            yield from _iter_sensitive_values(value, child)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _iter_sensitive_values(value, f"{path}[{index}]")


def test_config_json_has_no_plaintext_secret():
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    offenders = []
    for path, value in _iter_sensitive_values(payload):
        if not value:
            continue
        if _ENV_PLACEHOLDER.match(value):
            continue
        lowered = value.lower()
        if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
            continue
        offenders.append(f"{path} = {value!r}")

    assert not offenders, (
        "config.json (versionné) contient des valeurs sensibles en clair ; "
        "utiliser un placeholder ${VAR:-...} ou une variable d'environnement : "
        + ", ".join(offenders)
    )
