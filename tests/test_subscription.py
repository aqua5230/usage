from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

import subscription


def _make_id_token(auth_claims: object) -> str:
    payload = json.dumps({"https://api.openai.com/auth": auth_claims}).encode()
    body = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    return f"header.{body}.signature"


def _make_raw_id_token(payload_claims: object) -> str:
    payload = json.dumps(payload_claims).encode()
    body = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    return f"header.{body}.signature"


def test_claude_subscription(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = tmp_path / ".claude.json"
    cfg.write_text(json.dumps({
        "oauthAccount": {
            "organizationType": "claude_pro",
            "subscriptionCreatedAt": "2026-04-12T03:29:57.721002Z",
            "emailAddress": "secret@example.com",
        }
    }))
    monkeypatch.setattr(subscription, "CLAUDE_CONFIG", cfg)
    sub = subscription._load_claude_subscription()
    assert sub == {"agent": "Claude Code", "plan": "Claude Pro", "since": "2026-04-12"}
    # never leak private fields
    assert "secret@example.com" not in json.dumps(sub)


def test_claude_unknown_plan_is_humanised(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = tmp_path / ".claude.json"
    cfg.write_text(json.dumps({"oauthAccount": {"organizationType": "claude_max_5x"}}))
    monkeypatch.setattr(subscription, "CLAUDE_CONFIG", cfg)
    sub = subscription._load_claude_subscription()
    assert sub is not None
    plan = sub["plan"]
    assert plan is not None and plan.startswith("Claude")
    assert sub["since"] is None


def test_codex_subscription(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({
        "auth_mode": "chatgpt",
        "tokens": {"id_token": _make_id_token({
            "chatgpt_plan_type": "plus",
            "chatgpt_subscription_active_start": "2026-03-23T13:23:07+00:00",
        })},
    }))
    monkeypatch.setattr(subscription, "CODEX_AUTH", auth)
    sub = subscription._load_codex_subscription()
    assert sub == {"agent": "Codex", "plan": "ChatGPT Plus", "since": "2026-03-23"}


def test_codex_api_key_mode_no_sub(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"auth_mode": "apikey"}))
    monkeypatch.setattr(subscription, "CODEX_AUTH", auth)
    assert subscription._load_codex_subscription() is None


def test_missing_files_return_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(subscription, "CLAUDE_CONFIG", tmp_path / "nope.json")
    monkeypatch.setattr(subscription, "CODEX_AUTH", tmp_path / "nope2.json")
    assert subscription.load_subscriptions() == []


def test_load_subscriptions_combines_both(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = tmp_path / ".claude.json"
    cfg.write_text(json.dumps({"oauthAccount": {"organizationType": "claude_pro"}}))
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({
        "auth_mode": "chatgpt",
        "tokens": {"id_token": _make_id_token({"chatgpt_plan_type": "pro"})},
    }))
    monkeypatch.setattr(subscription, "CLAUDE_CONFIG", cfg)
    monkeypatch.setattr(subscription, "CODEX_AUTH", auth)
    subs = subscription.load_subscriptions()
    assert [s["agent"] for s in subs] == ["Claude Code", "Codex"]
    assert subs[1]["plan"] == "ChatGPT Pro"


def test_load_subscriptions_ignores_json_array_roots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = tmp_path / ".claude.json"
    cfg.write_text("[]")
    auth = tmp_path / "auth.json"
    auth.write_text("[]")
    monkeypatch.setattr(subscription, "CLAUDE_CONFIG", cfg)
    monkeypatch.setattr(subscription, "CODEX_AUTH", auth)
    assert subscription.load_subscriptions() == []


def test_claude_subscription_ignores_non_dict_account(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = tmp_path / ".claude.json"
    cfg.write_text(json.dumps({"oauthAccount": []}))
    monkeypatch.setattr(subscription, "CLAUDE_CONFIG", cfg)
    assert subscription._load_claude_subscription() is None


@pytest.mark.parametrize("tokens_value", [None, [], "token", 123])
def test_codex_subscription_ignores_non_dict_tokens(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tokens_value: object
) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"auth_mode": "chatgpt", "tokens": tokens_value}))
    monkeypatch.setattr(subscription, "CODEX_AUTH", auth)
    assert subscription._load_codex_subscription() is None


def test_claude_subscription_non_string_fields_degrade(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = tmp_path / ".claude.json"
    cfg.write_text(json.dumps({
        "oauthAccount": {
            "organizationType": 123,
            "subscriptionCreatedAt": 1717000000,
        }
    }))
    monkeypatch.setattr(subscription, "CLAUDE_CONFIG", cfg)
    assert subscription._load_claude_subscription() is None


def test_claude_subscription_non_string_since_keeps_default_plan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = tmp_path / ".claude.json"
    cfg.write_text(json.dumps({
        "oauthAccount": {
            "organizationType": "claude_team",
            "subscriptionCreatedAt": 1717000000,
        }
    }))
    monkeypatch.setattr(subscription, "CLAUDE_CONFIG", cfg)
    assert subscription._load_claude_subscription() == {
        "agent": "Claude Code",
        "plan": "Claude Team",
        "since": None,
    }


def test_codex_subscription_non_string_fields_degrade(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({
        "auth_mode": "chatgpt",
        "tokens": {"id_token": _make_id_token({
            "chatgpt_plan_type": 456,
            "chatgpt_subscription_active_start": 1717000000,
        })},
    }))
    monkeypatch.setattr(subscription, "CODEX_AUTH", auth)
    assert subscription._load_codex_subscription() is None


def test_codex_subscription_ignores_non_dict_auth_claims(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({
        "auth_mode": "chatgpt",
        "tokens": {"id_token": _make_id_token([])},
    }))
    monkeypatch.setattr(subscription, "CODEX_AUTH", auth)
    assert subscription._load_codex_subscription() is None


@pytest.mark.parametrize("id_token", [None, 123, []])
def test_load_subscriptions_ignores_non_string_id_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, id_token: object
) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({
        "auth_mode": "chatgpt",
        "tokens": {"id_token": id_token},
    }))
    monkeypatch.setattr(subscription, "CODEX_AUTH", auth)
    monkeypatch.setattr(subscription, "CLAUDE_CONFIG", tmp_path / "nope.json")
    assert subscription.load_subscriptions() == []


def test_load_subscriptions_ignores_non_dict_jwt_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({
        "auth_mode": "chatgpt",
        "tokens": {"id_token": _make_raw_id_token(123)},
    }))
    monkeypatch.setattr(subscription, "CODEX_AUTH", auth)
    monkeypatch.setattr(subscription, "CLAUDE_CONFIG", tmp_path / "nope.json")
    assert subscription.load_subscriptions() == []


def test_codex_subscription_non_string_plan_type_keeps_default_plan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({
        "auth_mode": "chatgpt",
        "tokens": {"id_token": _make_id_token({
            "chatgpt_plan_type": 456,
            "chatgpt_subscription_active_start": "2026-03-23T13:23:07+00:00",
        })},
    }))
    monkeypatch.setattr(subscription, "CODEX_AUTH", auth)
    assert subscription._load_codex_subscription() == {
        "agent": "Codex",
        "plan": "ChatGPT",
        "since": "2026-03-23",
    }
