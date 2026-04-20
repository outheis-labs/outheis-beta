"""Tests for billing failsafe in dispatcher/daemon.py.

Covers _enter_fallback_mode, _exit_fallback_mode, and _probe_billing.
The Dispatcher is constructed minimally — no queue, no transports, no LLM calls.
"""


from outheis.core.config import AgentConfig, Config, LLMConfig
from outheis.dispatcher.daemon import Dispatcher

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

def make_dispatcher(local_fallback: str | None = "local-llama") -> Dispatcher:
    """Dispatcher with two cloud agents and no real I/O."""
    cfg = Config(
        llm=LLMConfig(local_fallback=local_fallback),
        agents={
            "relay":   AgentConfig(name="ou",   model="fast",    enabled=True),
            "agenda":  AgentConfig(name="cato",  model="capable", enabled=True),
        },
    )
    d = Dispatcher(config=cfg)
    # Suppress queue / status file I/O
    d._atomic_write = lambda *a, **kw: None
    return d


def _silence(dispatcher: Dispatcher, monkeypatch) -> None:
    """Patch out all side-effects that touch the filesystem or queue."""
    monkeypatch.setattr("outheis.dispatcher.daemon._atomic_write", lambda *a, **kw: None)
    monkeypatch.setattr("outheis.dispatcher.daemon.append", lambda *a, **kw: None)


# ---------------------------------------------------------------------------
# _enter_fallback_mode
# ---------------------------------------------------------------------------

class TestEnterFallbackMode:
    def test_sets_fallback_flag(self, monkeypatch):
        d = make_dispatcher()
        _silence(d, monkeypatch)
        d._enter_fallback_mode("credits exhausted")
        assert d._fallback_mode is True

    def test_overrides_agent_models(self, monkeypatch):
        d = make_dispatcher(local_fallback="local-llama")
        _silence(d, monkeypatch)
        d._enter_fallback_mode("credits exhausted")
        assert d.config.agents["relay"].model == "local-llama"
        assert d.config.agents["agenda"].model == "local-llama"

    def test_saves_original_models(self, monkeypatch):
        d = make_dispatcher(local_fallback="local-llama")
        _silence(d, monkeypatch)
        d._enter_fallback_mode("credits exhausted")
        assert d._original_models["relay"] == "fast"
        assert d._original_models["agenda"] == "capable"

    def test_idempotent_second_call(self, monkeypatch):
        d = make_dispatcher(local_fallback="local-llama")
        _silence(d, monkeypatch)
        d._enter_fallback_mode("first")
        # Manually change model to something unexpected
        d.config.agents["relay"].model = "other"
        d._enter_fallback_mode("second")
        # Models must not be overwritten again
        assert d.config.agents["relay"].model == "other"

    def test_no_local_fallback_configured(self, monkeypatch):
        d = make_dispatcher(local_fallback=None)
        _silence(d, monkeypatch)
        d._enter_fallback_mode("credits exhausted")
        assert d._fallback_mode is True
        # Models unchanged — no fallback to switch to
        assert d.config.agents["relay"].model == "fast"

    def test_clears_cached_agent_instances(self, monkeypatch):
        d = make_dispatcher(local_fallback="local-llama")
        _silence(d, monkeypatch)
        d._agents["relay"] = object()  # simulate cached agent
        d._enter_fallback_mode("credits exhausted")
        assert "relay" not in d._agents


# ---------------------------------------------------------------------------
# _exit_fallback_mode
# ---------------------------------------------------------------------------

class TestExitFallbackMode:
    def test_clears_fallback_flag(self, monkeypatch):
        d = make_dispatcher()
        _silence(d, monkeypatch)
        d._enter_fallback_mode("credits exhausted")
        d._exit_fallback_mode()
        assert d._fallback_mode is False

    def test_restores_original_models(self, monkeypatch):
        d = make_dispatcher(local_fallback="local-llama")
        _silence(d, monkeypatch)
        d._enter_fallback_mode("credits exhausted")
        d._exit_fallback_mode()
        assert d.config.agents["relay"].model == "fast"
        assert d.config.agents["agenda"].model == "capable"

    def test_original_models_cleared_after_exit(self, monkeypatch):
        d = make_dispatcher(local_fallback="local-llama")
        _silence(d, monkeypatch)
        d._enter_fallback_mode("credits exhausted")
        d._exit_fallback_mode()
        assert d._original_models == {}

    def test_noop_if_not_in_fallback(self, monkeypatch):
        d = make_dispatcher()
        _silence(d, monkeypatch)
        # Should not raise, should be a no-op
        d._exit_fallback_mode()
        assert d._fallback_mode is False


# ---------------------------------------------------------------------------
# _probe_billing
# ---------------------------------------------------------------------------

class TestProbeBilling:
    def test_returns_true_on_success(self, monkeypatch):
        d = make_dispatcher(local_fallback="local-llama")
        d._original_models = {"relay": "fast"}
        d._cloud_key_available = True  # pretend API key is present

        import outheis.core.llm as llm_mod
        monkeypatch.setattr(llm_mod, "call_llm", lambda **kw: "pong")

        assert d._probe_billing() is True

    def test_returns_false_on_billing_error(self, monkeypatch):
        from outheis.core.llm import BillingError
        d = make_dispatcher()
        d._original_models = {"relay": "fast"}

        import outheis.core.llm as llm_mod
        monkeypatch.setattr(llm_mod, "call_llm",
                            lambda **kw: (_ for _ in ()).throw(BillingError("no credits")))

        assert d._probe_billing() is False

    def test_returns_false_when_no_cloud_alias(self, monkeypatch):
        d = make_dispatcher()
        d._original_models = {}  # no saved originals
        # All agents use local- prefix so no cloud alias found
        d.config.agents["relay"].model = "local-llama"
        d.config.agents["agenda"].model = "local-llama"

        assert d._probe_billing() is False
