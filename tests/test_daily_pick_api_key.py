from utils import daily_pick


def test_anthropic_provider_uses_only_anthropic_environment_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test-key")
    monkeypatch.setenv("ARK_API_KEY", "ark-test-key")
    monkeypatch.setattr(
        daily_pick,
        "_load_llm_config",
        lambda: {"provider": "anthropic", "api_key": ""},
    )

    assert daily_pick.get_api_key() == "anthropic-test-key"


def test_ark_provider_uses_only_ark_environment_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test-key")
    monkeypatch.setenv("ARK_API_KEY", "ark-test-key")
    monkeypatch.setattr(
        daily_pick,
        "_load_llm_config",
        lambda: {"provider": "ark", "api_key": ""},
    )

    assert daily_pick.get_api_key() == "ark-test-key"


def test_unknown_provider_fails_closed_even_with_configured_key(monkeypatch):
    monkeypatch.setattr(
        daily_pick,
        "_load_llm_config",
        lambda: {"provider": "unknown", "api_key": "configured-test-key"},
    )

    assert daily_pick.get_api_key() is None


def test_provider_specific_configured_key_takes_precedence(monkeypatch):
    monkeypatch.setenv("ARK_API_KEY", "ark-environment-key")
    monkeypatch.setattr(
        daily_pick,
        "_load_llm_config",
        lambda: {"provider": "ark", "api_key": "configured-test-key"},
    )

    assert daily_pick.get_api_key() == "configured-test-key"


def test_provider_name_is_normalized_once_for_key_and_dispatch(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test-key")
    monkeypatch.setattr(
        daily_pick,
        "_load_llm_config",
        lambda: {"provider": "  AnThRoPiC  ", "api_key": ""},
    )

    assert daily_pick._get_llm_provider() == "anthropic"
    assert daily_pick.get_api_key() == "anthropic-test-key"


def test_explicit_config_snapshot_is_not_reloaded(monkeypatch):
    monkeypatch.setenv("ARK_API_KEY", "ark-test-key")
    monkeypatch.setattr(
        daily_pick,
        "_load_llm_config",
        lambda: (_ for _ in ()).throw(AssertionError("config reloaded")),
    )

    assert daily_pick.get_api_key({"provider": "ark", "api_key": ""}) == "ark-test-key"
