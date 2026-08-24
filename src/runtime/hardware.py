"""Hardware auto-adaptatif — Phase 2.0

Détection VRAM au lancement → 3 profils (3G / 12G / CPU) + overrides env.
Un seul binaire : aucun cap hard-codé, le profil s'applique avant toute
allocation CUDA (appelé en tête de src/main.py).

Overrides (priorité sur la détection) :
  POKER_GPU_PROFILE=auto|3g|12g|cpu
  POKER_VRAM_CAP=0.70          (fraction max VRAM allouable)
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)

PROFILES_3G = "3g"
PROFILES_12G = "12g"
PROFILES_CPU = "cpu"
_VALID_PROFILES = (PROFILES_3G, PROFILES_12G, PROFILES_CPU)

# Seuils de classification (MiB de VRAM totale)
_MIB_3G = 4 * 1024        # < 4 Go → profil 3G (1060 3Go…)
_MIB_12G = 8 * 1024       # >= 8 Go → profil 12G (3060 12Go prod) ; 4-8 Go → 12G dégradé


@dataclass(frozen=True)
class HardwareProfile:
    name: str
    vram_cap_fraction: float
    cuda_alloc_conf: str | None      # valeur PYTORCH_CUDA_ALLOC_CONF, None = défaut torch
    cudnn_benchmark: bool
    yolo_model: str                  # sélection modèle via HardwareProfile.yolo_model
    surya_batch: int
    observation_capture: bool
    concurrent_tables: int
    time_budget_ms: int
    torch_compile: bool
    gpu_name: str = ""
    vram_total_mib: int = 0

    def describe(self) -> str:
        if self.name == PROFILES_CPU:
            return "CPU fallback (CPUExecutionProvider)"
        return (
            f"{self.name.upper()} ({self.gpu_name}, {self.vram_total_mib} MiB) -> "
            f"{self.yolo_model}, cap {int(self.vram_cap_fraction * 100)}%, "
            f"Surya batch {self.surya_batch}"
        )


_PROFILES: dict[str, HardwareProfile] = {
    # GTX 1060 3Go / Pascal CC 6.1 : pas de Tensor Cores, TRT deconseillé,
    # cuDNN benchmark penalise, split 128 Mo contre la fragmentation.
    PROFILES_3G: HardwareProfile(
        name=PROFILES_3G,
        vram_cap_fraction=0.70,
        cuda_alloc_conf="max_split_size_mb:128",
        cudnn_benchmark=False,
        yolo_model="yolov12n_fp32",
        surya_batch=1,
        observation_capture=False,
        concurrent_tables=1,
        time_budget_ms=1000,
        torch_compile=False,
    ),
    # RTX 3060 12Go / Ampere : benchmark OK, compile inductor OK, large marge.
    PROFILES_12G: HardwareProfile(
        name=PROFILES_12G,
        vram_cap_fraction=0.90,
        cuda_alloc_conf=None,
        cudnn_benchmark=True,
        yolo_model="yolov12s_fp16",
        surya_batch=4,
        observation_capture=True,
        concurrent_tables=4,
        time_budget_ms=1000,
        torch_compile=True,
    ),
    PROFILES_CPU: HardwareProfile(
        name=PROFILES_CPU,
        vram_cap_fraction=0.0,
        cuda_alloc_conf=None,
        cudnn_benchmark=False,
        yolo_model="yolov12n_cpu",
        surya_batch=1,
        observation_capture=False,
        concurrent_tables=1,
        time_budget_ms=1200,
        torch_compile=False,
    ),
}


def _read_vram_via_nvidia_smi() -> tuple[int, str] | None:
    """Fallback si torch absent/initialisation impossible : nvidia-smi."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return None
    try:
        out = subprocess.run(
            [smi, "--query-gpu=memory.total,name", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    first_line = (out.stdout or "").strip().splitlines()
    if not first_line:
        return None
    parts = [p.strip() for p in first_line[0].split(",")]
    if len(parts) < 2 or not parts[0].isdigit():
        return None
    return int(parts[0]), parts[1]


def _detect_cuda(torch_module) -> tuple[int, str] | None:
    try:
        if not torch_module.cuda.is_available():
            return None
        props = torch_module.cuda.get_device_properties(0)
        return int(props.total_memory / (1024 * 1024)), getattr(props, "name", "") or "CUDA GPU"
    except Exception:  # CUDA cassé/mid-driver update → fallback nvidia-smi
        return None


def classify_profile(vram_total_mib: int | None) -> str:
    if not vram_total_mib or vram_total_mib <= 0:
        return PROFILES_CPU
    if vram_total_mib < _MIB_3G:
        return PROFILES_3G
    return PROFILES_12G


def detect_gpu_profile(torch_module=None) -> HardwareProfile:
    """Détecte la VRAM et retourne le profil. Overrides env prioritaires."""
    forced = os.getenv("POKER_GPU_PROFILE", "auto").strip().lower()
    if forced not in _VALID_PROFILES and forced != "auto":
        logger.warning("POKER_GPU_PROFILE inconnu (%r), auto-detection", forced)

    if forced in _VALID_PROFILES:
        return _apply_cap_override(_PROFILES[forced])

    detected = None
    if torch_module is not None:
        detected = _detect_cuda(torch_module)
    if detected is None:
        detected = _read_vram_via_nvidia_smi()

    name = classify_profile(detected[0] if detected else None)
    profile = _PROFILES[name]
    if detected:
        profile = HardwareProfile(
            **{
                **profile.__dict__,
                "gpu_name": detected[1],
                "vram_total_mib": detected[0],
            }
        )
    return _apply_cap_override(profile)


def _apply_cap_override(profile: HardwareProfile) -> HardwareProfile:
    cap_override = os.getenv("POKER_VRAM_CAP")
    if not cap_override or profile.name == PROFILES_CPU:
        return profile
    try:
        return replace_cap(profile, float(cap_override))
    except ValueError:
        logger.warning("POKER_VRAM_CAP invalide (%r), ignore", cap_override)
        return profile


def replace_cap(profile: HardwareProfile, cap: float) -> HardwareProfile:
    cap = min(1.0, max(0.10, cap))
    return HardwareProfile(
        **{
            **profile.__dict__,
            "vram_cap_fraction": cap,
        }
    )


_active_profile: HardwareProfile | None = None


def get_active_hardware_profile() -> HardwareProfile:
    """Profil appliqué au dernier appel apply_hardware_profile (fallback: re-détection)."""
    global _active_profile
    if _active_profile is None:
        _active_profile = detect_gpu_profile()
    return _active_profile


def apply_hardware_profile(torch_module=None) -> HardwareProfile:
    """Applique le profil détecté : alloc conf, memory fraction, cudnn.

    À appeler en tout premier dans src/main.py, avant toute allocation CUDA.
    Tolérant : si torch est absent ou CUDA indisponible, ne fait rien de risqué.
    """
    if torch_module is None:
        try:
            import torch as torch_module  # noqa: PLC0415
        except ImportError:
            torch_module = None

    profile = detect_gpu_profile(torch_module)

    global _active_profile
    _active_profile = profile

    if profile.cuda_alloc_conf:
        os.environ["PYTORCH_CUDA_ALLOC_CONF"] = profile.cuda_alloc_conf
    elif profile.name == PROFILES_CPU:
        os.environ.pop("PYTORCH_CUDA_ALLOC_CONF", None)

    if torch_module is None or profile.name == PROFILES_CPU:
        logger.info("Hardware profile: %s", profile.describe())
        return profile

    try:
        if torch_module.cuda.is_available():
            if profile.vram_cap_fraction > 0:
                torch_module.cuda.set_per_process_memory_fraction(
                    profile.vram_cap_fraction, device=0
                )
            torch_module.backends.cudnn.benchmark = profile.cudnn_benchmark
    except Exception:
        logger.warning("Application du profil hardware partielle", exc_info=True)

    logger.info("Hardware profile: %s", profile.describe())
    return profile
