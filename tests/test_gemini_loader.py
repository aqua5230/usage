import json
import shutil
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import gemini_loader


class TestGeminiLoader(unittest.TestCase):

    def test_estimate_tokens(self) -> None:
        # English test (approx 1 token per 4 chars)
        self.assertEqual(gemini_loader.estimate_tokens("hello"), 1)
        self.assertEqual(gemini_loader.estimate_tokens("hello world"), 2)
        # CJK test (approx 1.2 tokens per char)
        self.assertEqual(gemini_loader.estimate_tokens("你好"), 2)
        self.assertEqual(gemini_loader.estimate_tokens("你好，世界"), 6)

    def test_calculate_gemini_cost(self) -> None:
        # 1M input = $1.25, 1M output = $5.00
        cost = gemini_loader.calculate_gemini_cost(1_000_000, 1_000_000)
        self.assertAlmostEqual(cost, 6.25)

    def test_parse_transcript_per_turn(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            transcript_path = Path(temp_dir) / "transcript.jsonl"
            lines = [
                # Turn 0: User request
                {
                    "step_index": 0,
                    "source": "USER_EXPLICIT",
                    "type": "USER_INPUT",
                    "created_at": "2026-05-26T08:00:00Z",
                    "content": "First prompt"
                },
                # Turn 0: Model reply
                {
                    "step_index": 1,
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "created_at": "2026-05-26T08:01:00Z",
                    "thinking": "Thinking turn one",
                    "content": "Response one"
                },
                # Turn 1: User request
                {
                    "step_index": 2,
                    "source": "USER_EXPLICIT",
                    "type": "USER_INPUT",
                    "created_at": "2026-05-26T08:02:00Z",
                    "content": "Second prompt"
                },
                # Turn 1: Model reply
                {
                    "step_index": 3,
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "created_at": "2026-05-26T08:03:00Z",
                    "thinking": "Thinking turn two",
                    "content": "Response two"
                }
            ]
            with open(transcript_path, "w", encoding="utf-8") as f:
                for line in lines:
                    f.write(json.dumps(line) + "\n")

            entries = gemini_loader._parse_transcript(transcript_path, "test-session-id", None)
            self.assertEqual(len(entries), 2)

            first = entries[0]
            self.assertEqual(first.project, "Antigravity (Gemini)")
            self.assertEqual(first.model, "gemini-1.5-pro")
            self.assertEqual(first.session_id, "test-session-id")
            self.assertTrue(first.input_tokens > 0)
            self.assertTrue(first.output_tokens > 0)
            # Per-turn approach: cache_read is always zero
            self.assertEqual(first.cache_read_tokens, 0)

            # Second turn: per-turn context resets, so input is just the new prompt
            second = entries[1]
            self.assertTrue(second.input_tokens > 0)
            self.assertEqual(second.cache_read_tokens, 0)
            # input_tokens are now independent per-turn, not accumulated
            self.assertAlmostEqual(first.input_tokens, second.input_tokens, delta=5)

        finally:
            shutil.rmtree(temp_dir)

    def test_parse_transcript_tool_output_counted(self) -> None:
        """Tool outputs between user input and model response contribute to per-turn tokens."""
        temp_dir = tempfile.mkdtemp()
        try:
            transcript_path = Path(temp_dir) / "transcript.jsonl"
            lines = [
                {
                    "step_index": 0,
                    "source": "USER_EXPLICIT",
                    "type": "USER_INPUT",
                    "created_at": "2026-05-26T08:00:00Z",
                    "content": "List files"
                },
                {
                    "step_index": 1,
                    "source": "MODEL",
                    "type": "LIST_DIRECTORY",
                    "created_at": "2026-05-26T08:00:01Z",
                    "content": "file1.py\nfile2.py\nfile3.py\nfile4.py\nfile5.py"
                },
                {
                    "step_index": 2,
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "created_at": "2026-05-26T08:00:02Z",
                    "content": "Here are the files"
                },
            ]
            with open(transcript_path, "w", encoding="utf-8") as f:
                for line in lines:
                    f.write(json.dumps(line) + "\n")

            entries = gemini_loader._parse_transcript(transcript_path, "sess", None)
            self.assertEqual(len(entries), 1)
            # input should include both the user message and the tool output
            self.assertTrue(entries[0].input_tokens > 5)
        finally:
            shutil.rmtree(temp_dir)

    def test_gemini_rows(self) -> None:
        import menubar
        from history_loader import UsageEntry

        delegate = menubar.AppDelegate.alloc().initWithMock_interval_(False, 60)

        # 1. Test mock rows
        delegate.mock = True
        (session_row, weekly_row), gemini_5h_pct = delegate._gemini_rows([])
        self.assertEqual(session_row.title, "5h Limit")
        self.assertEqual(weekly_row.title, "7d Limit")
        self.assertAlmostEqual(session_row.percent, 15.0)
        self.assertAlmostEqual(weekly_row.percent, 14.5)
        self.assertEqual(gemini_5h_pct, 15)

        # 2. Test actual rows with empty entries (no log data → missing rows)
        delegate.mock = False
        with patch("gemini_loader.load_rate_limits", return_value=None):
            (session_row, weekly_row), gemini_5h_pct = delegate._gemini_rows([])
        self.assertFalse(session_row.available)
        self.assertFalse(weekly_row.available)
        self.assertIsNone(gemini_5h_pct)

        # 3. Test actual rows with custom entries
        now = datetime.now(UTC)
        entries = [
            UsageEntry(
                timestamp=now - timedelta(hours=6),  # older than 5h, but within 7d
                session_id="s1",
                message_id="m1",
                request_id="r1",
                model="gemini-1.5-pro",
                input_tokens=500,
                output_tokens=300,
                cache_creation_tokens=0,
                cache_read_tokens=0,
                cost_usd=0.15,
                project="Antigravity (Gemini)",
            ),
            UsageEntry(
                timestamp=now - timedelta(hours=2),  # within 5h and 7d
                session_id="s2",
                message_id="m2",
                request_id="r2",
                model="gemini-1.5-pro",
                input_tokens=800,
                output_tokens=400,
                cache_creation_tokens=0,
                cache_read_tokens=0,
                cost_usd=0.30,
                project="Antigravity (Gemini)",
            ),
        ]

        with patch("gemini_loader.load_rate_limits", return_value=None):
            (session_row, weekly_row), gemini_5h_pct = delegate._gemini_rows(entries)

        self.assertTrue(session_row.available)
        self.assertTrue(weekly_row.available)

        # 5h window has s2 only: 1 call / 360 limit ≈ 0.28%
        expected_5h_pct = 1 / gemini_loader.FIVE_HOUR_CALL_LIMIT * 100.0
        self.assertAlmostEqual(session_row.percent, expected_5h_pct, delta=0.1)
        self.assertEqual(gemini_5h_pct, min(100, round(expected_5h_pct)))
        self.assertIn("1", session_row.percent_text)
        self.assertIn(str(gemini_loader.FIVE_HOUR_CALL_LIMIT), session_row.percent_text)

        # 7d window has s1 + s2: 2 calls / 3600 limit ≈ 0.056%
        expected_7d_pct = 2 / gemini_loader.SEVEN_DAY_CALL_LIMIT * 100.0
        self.assertAlmostEqual(weekly_row.percent, expected_7d_pct, delta=0.01)
        self.assertIn("2", weekly_row.percent_text)
        self.assertIn(str(gemini_loader.SEVEN_DAY_CALL_LIMIT), weekly_row.percent_text)

    def test_gemini_rows_caps_at_100(self) -> None:
        """When CLI log confirms quota exhausted, percentage is shown as 100."""
        import menubar
        from history_loader import UsageEntry

        delegate = menubar.AppDelegate.alloc().initWithMock_interval_(False, 60)
        delegate.mock = False

        now = datetime.now(UTC)
        # One API call within the 5h window
        entries = [
            UsageEntry(
                timestamp=now - timedelta(hours=1),
                session_id="s1",
                message_id="m1",
                request_id="r1",
                model="gemini-1.5-pro",
                input_tokens=1000,
                output_tokens=500,
                cache_creation_tokens=0,
                cache_read_tokens=0,
                cost_usd=0.90,
                project="Antigravity (Gemini)",
            ),
        ]

        # Mock load_rate_limits to confirm 5h quota is exhausted
        mock_limits = gemini_loader.GeminiRateLimits(
            five_hour_exhausted=True,
            five_hour_resets_at=(now + timedelta(hours=1)).timestamp(),
            seven_day_exhausted=False,
            seven_day_resets_at=None,
            window_start_ts=(now - timedelta(hours=4)).timestamp(),
        )

        with patch("gemini_loader.load_rate_limits", return_value=mock_limits):
            (session_row, _weekly_row), gemini_5h_pct = delegate._gemini_rows(entries)

        # Bar percent is capped at 100 when log confirms exhaustion
        self.assertEqual(session_row.percent, 100.0)
        # Menu bar percentage also shows 100
        self.assertEqual(gemini_5h_pct, 100)


if __name__ == "__main__":
    unittest.main()
