"""test_relay_register_signal — unit tests for Signal transport contact registration."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_transport(human_phones, human_name="Alice", allowed_contacts=None):
    """Build a SignalTransport with mocked config — no real signal-cli needed."""
    config = MagicMock()
    config.human.phone = human_phones
    config.human.name = human_name
    config.signal.bot_phone = "+49176000000"
    config.signal.allowed = allowed_contacts or []

    with patch("outheis.transport.signal.SignalRPC"), \
         patch("outheis.core.config.get_human_dir"):
        from outheis.transport.signal import SignalTransport
        t = SignalTransport.__new__(SignalTransport)
        t.bot_phone = config.signal.bot_phone
        t.allowed_phones = {}
        for phone in config.human.phone:
            t.allowed_phones[phone] = config.human.name
        for contact in config.signal.allowed:
            t.allowed_phones[contact.phone] = contact.name
        t.known_uuids = {}
        return t


# ---------------------------------------------------------------------------
# Allowed phones registration
# ---------------------------------------------------------------------------

class TestAllowedPhonesRegistration:

    def test_human_phone_is_allowed(self):
        t = make_transport(human_phones=["+49123456789"])
        assert "+49123456789" in t.allowed_phones

    def test_human_name_mapped_to_phone(self):
        t = make_transport(human_phones=["+49123456789"], human_name="Alice")
        assert t.allowed_phones["+49123456789"] == "Alice"

    def test_additional_allowed_contact_registered(self):
        extra = MagicMock()
        extra.phone = "+491760000001"
        extra.name = "Alice"
        t = make_transport(human_phones=["+49123456789"], allowed_contacts=[extra])
        assert "+491760000001" in t.allowed_phones
        assert t.allowed_phones["+491760000001"] == "Alice"

    def test_multiple_human_phones_all_allowed(self):
        t = make_transport(human_phones=["+49123456789", "+4917699999999"])
        assert "+49123456789" in t.allowed_phones
        assert "+4917699999999" in t.allowed_phones

    def test_no_allowed_contacts_only_human(self):
        t = make_transport(human_phones=["+49123456789"])
        assert len(t.allowed_phones) == 1

    def test_empty_human_phone_list(self):
        t = make_transport(human_phones=[])
        assert len(t.allowed_phones) == 0


# ---------------------------------------------------------------------------
# Signal state persistence
# ---------------------------------------------------------------------------

class TestSignalStatePersistence:

    def test_load_known_uuids_returns_dict_on_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            with patch("outheis.core.config.get_human_dir", return_value=Path(d)), \
                 patch("outheis.transport.signal.SignalRPC"):
                from outheis.transport.signal import SignalTransport
                t = SignalTransport.__new__(SignalTransport)
                t.bot_phone = "+49000"
                result = t._load_known_uuids()
        assert isinstance(result, dict)

    def test_load_known_uuids_reads_existing_state(self):
        with tempfile.TemporaryDirectory() as d:
            state_path = Path(d) / "signal.json"
            state_path.write_text(json.dumps({
                "user_phone": "+49123456789",
                "user_uuid": "abc-123"
            }), encoding="utf-8")
            with patch("outheis.core.config.get_human_dir", return_value=Path(d)), \
                 patch("outheis.transport.signal.SignalRPC"):
                from outheis.transport.signal import SignalTransport
                t = SignalTransport.__new__(SignalTransport)
                t.bot_phone = "+49000"
                result = t._load_known_uuids()
        assert result.get("+49123456789") == "abc-123"
