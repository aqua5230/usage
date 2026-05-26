import json
import shutil
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

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

    def test_parse_transcript_accumulates_context(self) -> None:
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

            # First turn:
            # Input context should be: "\nUser: First prompt"
            # Output context should be: "Thinking:\nThinking turn one\nResponse:\nResponse one"
            first = entries[0]
            self.assertEqual(first.project, "Antigravity (Gemini)")
            self.assertEqual(first.model, "gemini-1.5-pro")
            self.assertEqual(first.session_id, "test-session-id")
            self.assertTrue(first.input_tokens > 0)
            self.assertTrue(first.output_tokens > 0)

            # Second turn:
            # Input context should be accumulated turn 0 + turn 1 prompt:
            # "\nUser: First prompt\nAssistant: Response one\nUser: Second prompt"
            second = entries[1]
            self.assertTrue(second.input_tokens > first.input_tokens)
        finally:
            shutil.rmtree(temp_dir)

    def test_gemini_rows(self) -> None:
        from datetime import timedelta

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
        
        # 2. Test actual rows with empty entries
        delegate.mock = False
        (session_row, weekly_row), gemini_5h_pct = delegate._gemini_rows([])
        self.assertFalse(session_row.available)
        self.assertFalse(weekly_row.available)
        self.assertIsNone(gemini_5h_pct)
        
        # 3. Test actual rows with custom entries
        now = datetime.now(UTC)
        entries = [
            UsageEntry(
                timestamp=now - timedelta(hours=6), # older than 5h, but within 7d
                session_id="s1",
                message_id="m1",
                request_id="r1",
                model="gemini-1.5-pro",
                input_tokens=100000,
                output_tokens=50000,
                cache_creation_tokens=0,
                cache_read_tokens=0,
                cost_usd=0.375,  # 100k * 1.25/1M + 50k * 5.0/1M
                project="Antigravity (Gemini)",
            ),
            UsageEntry(
                timestamp=now - timedelta(hours=2), # within 5h and 7d
                session_id="s2",
                message_id="m2",
                request_id="r2",
                model="gemini-1.5-pro",
                input_tokens=200000,
                output_tokens=100000,
                cache_creation_tokens=0,
                cache_read_tokens=0,
                cost_usd=0.75,  # 200k * 1.25/1M + 100k * 5.0/1M
                project="Antigravity (Gemini)",
            ),
        ]
        
        (session_row, weekly_row), gemini_5h_pct = delegate._gemini_rows(entries)
        
        self.assertTrue(session_row.available)
        self.assertTrue(weekly_row.available)
        
        # 5h window has s2: cost = 0.75. limit = 10.00. pct = 7.5%
        self.assertAlmostEqual(session_row.percent, 7.5)
        self.assertEqual(gemini_5h_pct, 8)
        self.assertIn("$0.75", session_row.percent_text)
        self.assertIn("$10.00", session_row.percent_text)
        
        # 7d window has s1 and s2: cost = 0.375 + 0.75 = 1.125. limit = 100.00. pct = 1.125%
        self.assertAlmostEqual(weekly_row.percent, 1.125)
        self.assertIn("$1.12", weekly_row.percent_text)
        self.assertIn("$100.00", weekly_row.percent_text)


if __name__ == "__main__":
    unittest.main()
