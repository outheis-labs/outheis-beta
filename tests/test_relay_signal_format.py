"""Tests for _format_agenda_for_signal in relay.py.

Covers bullet prefixing (📅 Today, 🗓️ This Week, 💶 Cashflow),
checkbox conversion (🧘 Personal), section isolation, and edge cases.
"""

from outheis.agents.relay import _format_agenda_for_signal


class TestBulletSections:
    def test_today_lines_get_bullet(self):
        text = "## 📅 Today\nMeeting at 10\nLunch at 12"
        out = _format_agenda_for_signal(text)
        assert "▸ Meeting at 10" in out
        assert "▸ Lunch at 12" in out

    def test_week_lines_get_bullet(self):
        text = "## 🗓️ This Week\nSend report"
        out = _format_agenda_for_signal(text)
        assert "▸ Send report" in out

    def test_cashflow_lines_get_bullet(self):
        text = "## 💶 Cashflow\nRent 1200"
        out = _format_agenda_for_signal(text)
        assert "▸ Rent 1200" in out

    def test_empty_lines_not_bulleted(self):
        text = "## 📅 Today\n\nMeeting"
        out = _format_agenda_for_signal(text)
        lines = out.split("\n")
        # empty line must stay empty
        assert "" in lines
        assert "▸ Meeting" in out

    def test_header_line_not_bulleted(self):
        text = "## 📅 Today\nItem"
        out = _format_agenda_for_signal(text)
        assert out.startswith("## 📅 Today")


class TestCheckboxSection:
    def test_open_checkbox_converted(self):
        text = "## 🧘 Personal\n- [ ] Meditate"
        out = _format_agenda_for_signal(text)
        assert "🟩 Meditate" in out
        assert "- [ ]" not in out

    def test_done_checkbox_converted(self):
        text = "## 🧘 Personal\n- [x] Meditate"
        out = _format_agenda_for_signal(text)
        assert "✅ Meditate" in out
        assert "- [x]" not in out

    def test_plain_line_in_personal_not_bulleted(self):
        text = "## 🧘 Personal\nNote without checkbox"
        out = _format_agenda_for_signal(text)
        assert "▸" not in out


class TestSectionIsolation:
    def test_mode_resets_at_hr(self):
        text = "## 📅 Today\nItem\n---\nFree text"
        out = _format_agenda_for_signal(text)
        assert "▸ Item" in out
        assert "▸ Free text" not in out
        assert "Free text" in out

    def test_mode_resets_at_unknown_section(self):
        text = "## 📅 Today\nItem\n## 📝 Notes\nNote"
        out = _format_agenda_for_signal(text)
        assert "▸ Item" in out
        assert "▸ Note" not in out

    def test_non_agenda_text_unchanged(self):
        text = "Hello, here is your summary."
        assert _format_agenda_for_signal(text) == text

    def test_multiple_sections(self):
        text = (
            "## 📅 Today\nMeeting\n"
            "## 🧘 Personal\n- [ ] Zazen\n"
            "## 🗓️ This Week\nDeadline"
        )
        out = _format_agenda_for_signal(text)
        assert "▸ Meeting" in out
        assert "🟩 Zazen" in out
        assert "▸ Deadline" in out

    def test_empty_string(self):
        assert _format_agenda_for_signal("") == ""
