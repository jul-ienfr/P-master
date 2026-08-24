"""Tests Phase 2.0 — auto-détection hardware 3G/12G/CPU."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.runtime.hardware import (
    PROFILES_12G,
    PROFILES_3G,
    PROFILES_CPU,
    apply_hardware_profile,
    classify_profile,
    detect_gpu_profile,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("POKER_GPU_PROFILE", raising=False)
    monkeypatch.delenv("POKER_VRAM_CAP", raising=False)


def _fake_torch(total_bytes, name="Fake GPU", available=True):
    cuda = SimpleNamespace(
        is_available=lambda: available,
        get_device_properties=lambda idx: SimpleNamespace(
            total_memory=total_bytes, name=name
        ),
        set_per_process_memory_fraction=lambda frac, device=0: calls.append(("cap", frac)),
    )
    calls = []
    return (
        SimpleNamespace(
            cuda=cuda,
            backends=SimpleNamespace(cudnn=SimpleNamespace(benchmark=False)),
        ),
        calls,
    )


def test_classify_profile_buckets():
    assert classify_profile(None) == PROFILES_CPU
    assert classify_profile(0) == PROFILES_CPU
    assert classify_profile(3072) == PROFILES_3G
    assert classify_profile(6144) == PROFILES_12G
    assert classify_profile(12288) == PROFILES_12G


def test_detect_cpu_fallback_without_cuda(monkeypatch):
    torch, _ = _fake_torch(0, available=False)
    monkeypatch.setenv("POKER_GPU_PROFILE", "auto")
    monkeypatch.setattr("src.runtime.hardware._read_vram_via_nvidia_smi", lambda: None)
    profile = detect_gpu_profile(torch)
    assert profile.name == PROFILES_CPU


def test_detect_3g_profile_for_pascal_3gb(monkeypatch):
    torch, _ = _fake_torch(3 * 1024**3, name="NVIDIA GeForce GTX 1060 3GB")
    monkeypatch.setattr("src.runtime.hardware._read_vram_via_nvidia_smi", lambda: None)
    profile = detect_gpu_profile(torch)
    assert profile.name == PROFILES_3G
    assert profile.vram_cap_fraction == 0.70
    assert profile.cuda_alloc_conf == "max_split_size_mb:128"
    assert profile.cudnn_benchmark is False
    assert "GTX 1060" in profile.describe()


def test_detect_12g_profile_for_ampere(monkeypatch):
    torch, _ = _fake_torch(12 * 1024**3, name="NVIDIA GeForce RTX 3060")
    monkeypatch.setattr("src.runtime.hardware._read_vram_via_nvidia_smi", lambda: None)
    profile = detect_gpu_profile(torch)
    assert profile.name == PROFILES_12G
    assert profile.vram_cap_fraction == 0.90
    assert profile.cudnn_benchmark is True
    assert profile.surya_batch == 4


def test_env_forced_profile_overrides_detection(monkeypatch):
    torch, _ = _fake_torch(12 * 1024**3, name="NVIDIA GeForce RTX 3060")
    monkeypatch.setenv("POKER_GPU_PROFILE", "3g")
    profile = detect_gpu_profile(torch)
    assert profile.name == PROFILES_3G
    assert profile.vram_total_mib == 0


def test_vram_cap_override_clamped(monkeypatch):
    torch, _ = _fake_torch(3 * 1024**3)
    monkeypatch.setattr("src.runtime.hardware._read_vram_via_nvidia_smi", lambda: None)
    monkeypatch.setenv("POKER_VRAM_CAP", "1.5")
    profile = detect_gpu_profile(torch)
    assert profile.vram_cap_fraction == 1.0

    monkeypatch.setenv("POKER_VRAM_CAP", "abc")
    profile = detect_gpu_profile(torch)
    assert profile.vram_cap_fraction == 0.70


def test_apply_hardware_profile_sets_alloc_conf_and_cap(monkeypatch):
    torch, calls = _fake_torch(3 * 1024**3, name="NVIDIA GeForce GTX 1060 3GB")
    monkeypatch.setattr("src.runtime.hardware._read_vram_via_nvidia_smi", lambda: None)
    monkeypatch.delenv(os.environ.get("PYTORCH_CUDA_ALLOC_CONF") or "__absent__", raising=False)

    profile = apply_hardware_profile(torch)

    assert profile.name == PROFILES_3G
    assert os.environ["PYTORCH_CUDA_ALLOC_CONF"] == "max_split_size_mb:128"
    assert ("cap", 0.70) in calls
    assert torch.backends.cudnn.benchmark is False


def test_apply_hardware_profile_cpu_removes_alloc_conf(monkeypatch):
    torch, calls = _fake_torch(0, available=False)
    monkeypatch.setattr("src.runtime.hardware._read_vram_via_nvidia_smi", lambda: None)
    monkeypatch.setenv("PYTORCH_CUDA_ALLOC_CONF", "max_split_size_mb:128")

    profile = apply_hardware_profile(torch)

    assert profile.name == PROFILES_CPU
    assert "PYTORCH_CUDA_ALLOC_CONF" not in os.environ
    assert calls == []


def test_apply_hardware_profile_survives_broken_cuda():
    broken = SimpleNamespace(cuda=None)
    profile = apply_hardware_profile(broken)
    assert profile.name == PROFILES_CPU or profile.vram_total_mib > 0
