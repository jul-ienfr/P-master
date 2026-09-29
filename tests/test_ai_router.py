"""Tests du routeur IA — provider jev/djev/auto, 100 % mockés, zéro réseau."""

from unittest import mock

from src.bot import ai_router as router
from src.bot.ai_router import AiGateConfig
from src.bot.jev_gate import JevDecision


def _dec(go=0.83):
    return JevDecision(verdict=None, reason="parsed", go=go, tier="fast",
                       tier_confidence=0.9, risky=0.2, effort=0.5)


def test_unknown_provider_falls_back_to_auto():
    cfg = AiGateConfig.from_env({"provider": "whatever"})
    assert cfg.provider == "auto"


def test_provider_jev_calls_jev_gate():
    cfg = AiGateConfig.from_env({"provider": "jev"})
    with mock.patch("src.bot.ai_router.jev_decide",
                     return_value=(True, _dec(), "observer (agree)")) as m:
        allowed, dec, reason, source = router.decide({"x": 1}, True, config=cfg)
    assert m.call_count == 1
    assert source == "jev" and allowed is True


def test_provider_jev_fail_open_never_raises():
    cfg = AiGateConfig.from_env({"provider": "jev"})
    with mock.patch("src.bot.ai_router.jev_decide",
                     side_effect=RuntimeError("boom")):
        allowed, dec, reason, source = router.decide({"x": 1}, True, config=cfg)
    assert allowed is True and dec.verdict is None and source == "jev"


def test_provider_djev_missing_module_fail_open():
    cfg = AiGateConfig.from_env({"provider": "djev"})
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if "djev_gate" in str(name):
            raise ImportError("no module")
        return real_import(name, *args, **kwargs)

    with mock.patch("builtins.__import__", side_effect=fake_import):
        allowed, dec, reason, source = router.decide({"x": 1}, False,
                                                     config=cfg)
    assert allowed is False and dec.verdict is None


def test_auto_offline_uses_loopback_never_wan(monkeypatch):
    monkeypatch.setenv("POKER_OFFLINE_MODE", "1")
    cfg = AiGateConfig.from_env(
        {"provider": "auto",
         "djev": {"lan_url": "http://127.0.0.1:4000",
                  "cloud_url": "https://api.typesafe.ai/v1/systemone"}})
    with mock.patch("src.bot.ai_router._via_djev",
                     return_value=(True, _dec(), "ok", "djev-lan")) as m:
        allowed, _, _, source = router.decide({"x": 1}, True, config=cfg)
    assert source == "djev-lan"
    assert m.call_count == 1


def test_auto_online_with_key_uses_djev_cloud(monkeypatch):
    monkeypatch.delenv("POKER_OFFLINE_MODE", raising=False)
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    # Voie online explicite (lock: offline_mode True par defaut -> djev-lan).
    cfg = AiGateConfig.from_env({"provider": "auto", "offline_mode": False})
    with mock.patch("src.bot.ai_router._via_djev",
                     return_value=(True, _dec(), "ok", "djev-cloud")) as m:
        _, _, _, source = router.decide({"x": 1}, True, config=cfg)
    assert source == "djev-cloud" and m.call_count == 1


def test_auto_online_without_key_falls_back_jev(monkeypatch):
    monkeypatch.delenv("POKER_OFFLINE_MODE", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    # Voie online explicite (lock: offline_mode True par defaut -> djev-lan).
    cfg = AiGateConfig.from_env({"provider": "auto", "offline_mode": False})
    with mock.patch("src.bot.ai_router.jev_decide",
                     return_value=(True, _dec(), "observer (agree)")):
        _, _, _, source = router.decide({"x": 1}, True, config=cfg)
    assert source == "jev"


def test_provider_jev_with_key_never_touches_cloud(monkeypatch):
    """Verrou LAN : provider=jev + clé cloud présente => jev seul, zéro appel djev/cloud."""
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake-key-pour-test")
    cfg = AiGateConfig.from_env({"provider": "jev"})
    with mock.patch("src.bot.ai_router.jev_decide",
                     return_value=(True, _dec(), "observer (agree)")) as m_jev:
        with mock.patch("src.bot.ai_router._via_djev",
                         side_effect=AssertionError("cloud touched!")):
            allowed, _, _, source = router.decide({"x": 1}, True, config=cfg)
    assert m_jev.call_count == 1
    assert source == "jev" and allowed is True


def test_from_env_precedence(monkeypatch):
    base = {"bot": {"ai_gate": {"provider": "jev", "offline_mode": False}}}
    assert AiGateConfig.from_env(base=base).provider == "jev"
    monkeypatch.setenv("POKER_AI_PROVIDER", "djev")
    assert AiGateConfig.from_env(base=base).provider == "djev"
    cfg = AiGateConfig.from_env(overrides={"provider": "auto"}, base=base)
    assert cfg.provider == "auto"  # overrides bat env...

    monkeypatch.delenv("POKER_AI_PROVIDER", raising=False)
    cfg2 = AiGateConfig.from_env(overrides={"provider": "jev"},
                                 base={"bot": {"ai_gate": {"provider": "auto"}}})
    assert cfg2.provider == "jev"  # ...et env absente, overrides bat base
