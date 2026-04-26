"""Tests for LLMConfig.resolve_model and call_llm provider fallback.

Scenarios:
- provider_aliases: normal resolution, fallback_order, skip_providers
- alias not defined on any provider
- all providers exhausted
- legacy path (flat models dict)
- call_llm retry loop: billing error triggers next provider
- call_llm: all providers fail → BillingError with failed_providers
- agent has no working model
"""

import pytest

from outheis.core.config import LLMConfig, ModelConfig, ModelResolutionError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_llm(provider_aliases, fallback_order=None, models=None):
    return LLMConfig(
        provider_aliases=provider_aliases,
        fallback_order=fallback_order or [],
        models=models or {},
    )


ALIASES = {
    "anthropic":   {"fast": "claude-haiku-4-5", "capable": "claude-sonnet-4-5"},
    "ollama.cloud": {"fast": "kimi-k2",          "capable": "deepseek-v4"},
    "ollama.local": {"fast": "gemma4:12b",        "capable": "devstral:24b"},
}


# ---------------------------------------------------------------------------
# resolve_model — provider_aliases path
# ---------------------------------------------------------------------------

class TestResolveModelProviderAliases:
    def test_returns_first_in_fallback_order(self):
        llm = make_llm(ALIASES, fallback_order=["ollama.cloud", "anthropic", "ollama.local"])
        mc, warning = llm.resolve_model("fast")
        assert mc.provider == "ollama.cloud"
        assert mc.name == "kimi-k2"
        assert warning is None

    def test_respects_fallback_order(self):
        llm = make_llm(ALIASES, fallback_order=["anthropic", "ollama.local"])
        mc, warning = llm.resolve_model("capable")
        assert mc.provider == "anthropic"

    def test_no_fallback_order_uses_sorted_keys(self):
        # sorted(["anthropic", "ollama.cloud", "ollama.local"]) → anthropic first
        llm = make_llm(ALIASES)
        mc, _ = llm.resolve_model("fast")
        assert mc.provider == "anthropic"

    def test_skip_providers_tries_next(self):
        llm = make_llm(ALIASES, fallback_order=["anthropic", "ollama.cloud", "ollama.local"])
        mc, warning = llm.resolve_model("fast", skip_providers={"anthropic"})
        assert mc.provider == "ollama.cloud"
        assert warning is not None
        assert "anthropic" in warning

    def test_skip_multiple_providers(self):
        llm = make_llm(ALIASES, fallback_order=["anthropic", "ollama.cloud", "ollama.local"])
        mc, _ = llm.resolve_model("fast", skip_providers={"anthropic", "ollama.cloud"})
        assert mc.provider == "ollama.local"

    def test_all_providers_skipped_raises(self):
        llm = make_llm(ALIASES, fallback_order=["anthropic", "ollama.cloud", "ollama.local"])
        with pytest.raises(ModelResolutionError, match="exhausted"):
            llm.resolve_model("fast", skip_providers={"anthropic", "ollama.cloud", "ollama.local"})

    def test_alias_not_on_any_provider_raises(self):
        llm = make_llm(ALIASES, fallback_order=["anthropic", "ollama.cloud"])
        with pytest.raises(ModelResolutionError, match="not defined"):
            llm.resolve_model("reasoning")

    def test_alias_only_on_skipped_provider_raises(self):
        aliases = {"anthropic": {"reasoning": "claude-opus-4-5"}}
        llm = make_llm(aliases, fallback_order=["anthropic"])
        with pytest.raises(ModelResolutionError):
            llm.resolve_model("reasoning", skip_providers={"anthropic"})

    def test_same_alias_on_multiple_providers(self):
        # same alias name on all three — fallback_order determines which is used
        llm = make_llm(ALIASES, fallback_order=["ollama.local", "anthropic"])
        mc, _ = llm.resolve_model("capable")
        assert mc.provider == "ollama.local"
        assert mc.name == "devstral:24b"

    def test_partial_coverage_alias_skips_missing_providers(self):
        # "reasoning" only exists on anthropic, not others
        aliases = {
            "anthropic":   {"fast": "claude-haiku-4-5", "reasoning": "claude-opus-4-5"},
            "ollama.local": {"fast": "gemma4:12b"},
        }
        llm = make_llm(aliases, fallback_order=["ollama.local", "anthropic"])
        mc, _ = llm.resolve_model("reasoning")
        # ollama.local doesn't have "reasoning" → falls through to anthropic
        assert mc.provider == "anthropic"
        assert mc.name == "claude-opus-4-5"


# ---------------------------------------------------------------------------
# resolve_model — legacy path (no provider_aliases)
# ---------------------------------------------------------------------------

class TestResolveModelLegacy:
    def test_finds_model_in_flat_dict(self):
        llm = LLMConfig(
            models={"fast": ModelConfig(provider="anthropic", name="claude-haiku-4-5")},
        )
        mc, warning = llm.resolve_model("fast")
        assert mc.provider == "anthropic"
        assert mc.name == "claude-haiku-4-5"
        assert warning is None

    def test_alias_not_in_models_raises(self):
        llm = LLMConfig(models={})
        with pytest.raises(ModelResolutionError, match="not defined"):
            llm.resolve_model("fast")

    def test_incomplete_model_raises(self):
        llm = LLMConfig(
            models={"fast": ModelConfig(provider="anthropic", name="")},
        )
        with pytest.raises(ModelResolutionError):
            llm.resolve_model("fast")

    def test_skip_providers_on_legacy_triggers_error(self):
        llm = LLMConfig(
            models={"fast": ModelConfig(provider="anthropic", name="claude-haiku-4-5")},
        )
        with pytest.raises(ModelResolutionError):
            llm.resolve_model("fast", skip_providers={"anthropic"})


# ---------------------------------------------------------------------------
# call_llm retry loop
# ---------------------------------------------------------------------------

class TestCallLlmFallback:
    def _make_config(self):
        from outheis.core.config import Config, AgentConfig, ProviderConfig
        return LLMConfig(
            providers={
                "anthropic":    ProviderConfig(api_key="sk-ant-test", base_url="https://api.anthropic.com"),
                "ollama.cloud": ProviderConfig(api_key="cloud-key",   base_url="https://ollama.com/v1"),
                "ollama.local": ProviderConfig(api_key="ollama-local", base_url="http://localhost:11434"),
            },
            provider_aliases=ALIASES,
            fallback_order=["anthropic", "ollama.cloud", "ollama.local"],
        )

    def test_billing_error_on_first_tries_second(self, monkeypatch):
        from outheis.core.llm import BillingError, call_llm
        import outheis.core.llm as llm_mod

        llm_config = self._make_config()
        monkeypatch.setattr(llm_mod, "get_llm_config", lambda: llm_config)

        calls = []
        def fake_do_call(model_config, *args, **kwargs):
            calls.append(model_config.provider)
            if model_config.provider == "anthropic":
                raise BillingError("no credits")
            return "ok"

        monkeypatch.setattr(llm_mod, "_do_call", fake_do_call)

        result = call_llm("fast", messages=[{"role": "user", "content": "hi"}])
        assert result == "ok"
        assert calls == ["anthropic", "ollama.cloud"]

    def test_all_providers_fail_raises_billing_error_with_failed_providers(self, monkeypatch):
        from outheis.core.llm import BillingError, call_llm
        import outheis.core.llm as llm_mod

        llm_config = self._make_config()
        monkeypatch.setattr(llm_mod, "get_llm_config", lambda: llm_config)

        def fake_do_call(model_config, *args, **kwargs):
            raise BillingError(f"{model_config.provider} unavailable")

        monkeypatch.setattr(llm_mod, "_do_call", fake_do_call)

        with pytest.raises(BillingError) as exc_info:
            call_llm("fast", messages=[{"role": "user", "content": "hi"}])

        assert exc_info.value.failed_providers == {"anthropic", "ollama.cloud", "ollama.local"}

    def test_non_billing_error_tries_fallback(self, monkeypatch):
        """Non-billing errors (e.g., 404 model not found, connection errors) should also try fallback providers."""
        from outheis.core.llm import call_llm
        import outheis.core.llm as llm_mod

        llm_config = self._make_config()
        monkeypatch.setattr(llm_mod, "get_llm_config", lambda: llm_config)

        calls = []
        def fake_do_call(model_config, *args, **kwargs):
            calls.append(model_config.provider)
            raise ConnectionError("network down")

        monkeypatch.setattr(llm_mod, "_do_call", fake_do_call)

        with pytest.raises(ConnectionError):
            call_llm("fast", messages=[{"role": "user", "content": "hi"}])

        # All providers tried — non-billing errors also trigger fallback
        assert calls == ["anthropic", "ollama.cloud", "ollama.local"]

    def test_no_provider_has_alias_raises_model_resolution_error(self, monkeypatch):
        from outheis.core.config import ModelResolutionError
        from outheis.core.llm import call_llm
        import outheis.core.llm as llm_mod

        llm_config = self._make_config()
        monkeypatch.setattr(llm_mod, "get_llm_config", lambda: llm_config)

        with pytest.raises(ModelResolutionError):
            call_llm("reasoning", messages=[{"role": "user", "content": "hi"}])

    def test_fallback_order_respected_in_retry(self, monkeypatch):
        from outheis.core.llm import BillingError, call_llm
        import outheis.core.llm as llm_mod

        llm_config = self._make_config()
        monkeypatch.setattr(llm_mod, "get_llm_config", lambda: llm_config)

        calls = []
        def fake_do_call(model_config, *args, **kwargs):
            calls.append(model_config.provider)
            if model_config.provider in ("anthropic", "ollama.cloud"):
                raise BillingError("unavailable")
            return "local_response"

        monkeypatch.setattr(llm_mod, "_do_call", fake_do_call)

        result = call_llm("fast", messages=[{"role": "user", "content": "hi"}])
        assert result == "local_response"
        assert calls == ["anthropic", "ollama.cloud", "ollama.local"]


# ---------------------------------------------------------------------------
# Agent has no working model
# ---------------------------------------------------------------------------

class TestAgentNoWorkingModel:
    def test_resolve_fails_when_alias_undefined(self):
        """Agent configured with an alias that exists on no provider."""
        llm = make_llm(
            {"anthropic": {"fast": "claude-haiku-4-5"}},
            fallback_order=["anthropic"],
        )
        with pytest.raises(ModelResolutionError, match="not defined"):
            llm.resolve_model("capable")  # "capable" is not in any provider

    def test_resolve_fails_when_all_providers_skipped(self):
        """All providers that have this alias are in skip_providers — agent cannot run."""
        llm = make_llm(ALIASES, fallback_order=["anthropic", "ollama.cloud", "ollama.local"])
        with pytest.raises(ModelResolutionError, match="exhausted"):
            llm.resolve_model("fast", skip_providers={"anthropic", "ollama.cloud", "ollama.local"})

    def test_resolve_fails_legacy_empty_models(self):
        """Legacy config with empty models dict — no alias can be resolved."""
        llm = LLMConfig(models={})
        with pytest.raises(ModelResolutionError):
            llm.resolve_model("fast")
