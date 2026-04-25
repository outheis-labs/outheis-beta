"""Tests for billing failsafe in dispatcher/daemon.py.

Covers _enter_fallback_mode, _exit_fallback_mode, and _probe_billing.
The Dispatcher is constructed minimally — no queue, no transports, no LLM calls.
"""


from outheis.core.config import AgentConfig, Config, LLMConfig
from outheis.dispatcher.daemon import Dispatcher


def make_dispatcher() -> Dispatcher:
    """Dispatcher with two cloud agents and no real I/O."""
    cfg = Config(
        llm=LLMConfig(
            provider_aliases={
                "anthropic": {"fast": "claude-haiku-4-5", "capable": "claude-sonnet-4-5"},
                "ollama.local": {"fast": "gemma4:12b", "capable": "devstral:24b"},
            },
            fallback_order=["anthropic", "ollama.local"],
        ),
        agents={
            "relay":  AgentConfig(name="ou",   model="fast",    enabled=True),
            "agenda": AgentConfig(name="cato", model="capable", enabled=True),
        },
    )
    return Dispatcher(config=cfg)


def _silence(dispatcher: Dispatcher, monkeypatch) -> None:
    monkeypatch.setattr("outheis.dispatcher.daemon._atomic_write", lambda *a, **kw: None)
    monkeypatch.setattr("outheis.dispatcher.daemon.append", lambda *a, **kw: None)


# ---------------------------------------------------------------------------
# _enter_fallback_mode
# ---------------------------------------------------------------------------

class TestEnterFallbackMode:
    def test_sets_fallback_flag(self, monkeypatch):
        d = make_dispatcher()
        _silence(d, monkeypatch)
        d._enter_fallback_mode("all providers exhausted")
        assert d._fallback_mode is True

    def test_idempotent_second_call(self, monkeypatch):
        d = make_dispatcher()
        _silence(d, monkeypatch)
        d._enter_fallback_mode("first")
        d._enter_fallback_mode("second")
        # Still in fallback, no error
        assert d._fallback_mode is True

    def test_agent_models_unchanged(self, monkeypatch):
        """Provider-level fallback is handled by call_llm, not by overriding agent models."""
        d = make_dispatcher()
        _silence(d, monkeypatch)
        d._enter_fallback_mode("all providers exhausted")
        assert d.config.agents["relay"].model == "fast"
        assert d.config.agents["agenda"].model == "capable"

    def test_writes_failed_providers_to_status(self, monkeypatch):
        written = {}
        monkeypatch.setattr("outheis.dispatcher.daemon._atomic_write",
                            lambda path, data: written.update({"data": data}))
        monkeypatch.setattr("outheis.dispatcher.daemon.append", lambda *a, **kw: None)
        d = make_dispatcher()
        d._enter_fallback_mode("billing error", failed_providers={"anthropic", "ollama.local"})
        import json
        status = json.loads(written["data"])
        assert set(status["failed_providers"]) == {"anthropic", "ollama.local"}
        assert status["mode"] == "fallback"


# ---------------------------------------------------------------------------
# _exit_fallback_mode
# ---------------------------------------------------------------------------

class TestExitFallbackMode:
    def test_clears_fallback_flag(self, monkeypatch):
        d = make_dispatcher()
        _silence(d, monkeypatch)
        d._enter_fallback_mode("exhausted")
        d._exit_fallback_mode()
        assert d._fallback_mode is False

    def test_noop_if_not_in_fallback(self, monkeypatch):
        d = make_dispatcher()
        _silence(d, monkeypatch)
        d._exit_fallback_mode()
        assert d._fallback_mode is False


# ---------------------------------------------------------------------------
# _probe_billing
# ---------------------------------------------------------------------------

class TestProbeBilling:
    def test_returns_true_on_success(self, monkeypatch):
        d = make_dispatcher()
        d._cloud_key_available = True
        import outheis.core.llm as llm_mod
        monkeypatch.setattr(llm_mod, "call_llm", lambda **kw: "pong")
        assert d._probe_billing() is True

    def test_returns_false_on_billing_error(self, monkeypatch):
        from outheis.core.llm import BillingError
        d = make_dispatcher()
        d._cloud_key_available = True
        import outheis.core.llm as llm_mod
        monkeypatch.setattr(llm_mod, "call_llm",
                            lambda **kw: (_ for _ in ()).throw(BillingError("no credits")))
        assert d._probe_billing() is False
