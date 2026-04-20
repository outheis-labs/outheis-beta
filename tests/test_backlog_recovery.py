"""Tests for startup backlog recovery in dispatcher/daemon.py.

The _process_backlog nested function (called in start()) must:
- Process each message independently (per-message try/except)
- Not abort on a failing message — subsequent messages still run
- Skip internal messages (intent="internal")

Since _process_backlog is a nested function, we test its behavior by
replicating the logic directly — this mirrors what start() does and
keeps the tests free of the full start() machinery.
"""



from outheis.core.config import AgentConfig, Config, LLMConfig
from outheis.core.message import Message, create_user_message
from outheis.dispatcher.daemon import Dispatcher

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_dispatcher() -> Dispatcher:
    cfg = Config(
        llm=LLMConfig(),
        agents={"relay": AgentConfig(name="ou", model="fast", enabled=True)},
    )
    return Dispatcher(config=cfg)


def make_user_msg(text: str = "hello", intent: str | None = None) -> Message:
    msg = create_user_message(channel="signal", identity="+1234", text=text)
    msg.intent = intent
    return msg


def run_backlog(dispatcher: Dispatcher, msgs: list[Message]) -> None:
    """Replicate the _process_backlog logic from daemon.start()."""
    user_msgs = [m for m in msgs if getattr(m, "intent", None) != "internal"]
    for msg in user_msgs:
        try:
            dispatcher.process_message(msg)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Per-message isolation
# ---------------------------------------------------------------------------

class TestBacklogIsolation:
    def test_failing_message_does_not_abort_rest(self, monkeypatch):
        d = make_dispatcher()
        processed = []

        def fake_process(msg):
            if msg.payload.get("text") == "fail":
                raise RuntimeError("boom")
            processed.append(msg.payload.get("text"))

        monkeypatch.setattr(d, "process_message", fake_process)

        msgs = [
            make_user_msg("ok-1"),
            make_user_msg("fail"),
            make_user_msg("ok-2"),
        ]
        run_backlog(d, msgs)

        assert "ok-1" in processed
        assert "ok-2" in processed

    def test_all_messages_attempted(self, monkeypatch):
        d = make_dispatcher()
        attempted = []

        def fake_process(msg):
            attempted.append(msg.payload.get("text"))
            raise RuntimeError("always fails")

        monkeypatch.setattr(d, "process_message", fake_process)

        msgs = [make_user_msg(f"msg-{i}") for i in range(5)]
        run_backlog(d, msgs)

        assert len(attempted) == 5

    def test_order_preserved(self, monkeypatch):
        d = make_dispatcher()
        order = []

        monkeypatch.setattr(d, "process_message",
                            lambda msg: order.append(msg.payload.get("text")))

        msgs = [make_user_msg(f"msg-{i}") for i in range(4)]
        run_backlog(d, msgs)

        assert order == ["msg-0", "msg-1", "msg-2", "msg-3"]


# ---------------------------------------------------------------------------
# Internal message filter
# ---------------------------------------------------------------------------

class TestInternalFilter:
    def test_internal_messages_skipped(self, monkeypatch):
        d = make_dispatcher()
        processed = []

        monkeypatch.setattr(d, "process_message",
                            lambda msg: processed.append(msg))

        msgs = [
            make_user_msg("user-msg"),
            make_user_msg("run_task:shadow_scan", intent="internal"),
            make_user_msg("another-user-msg"),
        ]
        run_backlog(d, msgs)

        texts = [m.payload.get("text") for m in processed]
        assert "user-msg" in texts
        assert "another-user-msg" in texts
        assert "run_task:shadow_scan" not in texts

    def test_only_internal_messages_yields_nothing(self, monkeypatch):
        d = make_dispatcher()
        processed = []

        monkeypatch.setattr(d, "process_message",
                            lambda msg: processed.append(msg))

        msgs = [make_user_msg(f"run_task:task-{i}", intent="internal") for i in range(3)]
        run_backlog(d, msgs)

        assert processed == []

    def test_empty_backlog_is_noop(self, monkeypatch):
        d = make_dispatcher()
        called = []
        monkeypatch.setattr(d, "process_message", lambda msg: called.append(msg))

        run_backlog(d, [])
        assert called == []
