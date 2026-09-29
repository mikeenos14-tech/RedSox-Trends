"""Guards against whole classes of wiring bugs that per-feature tests can miss."""
from __future__ import annotations

import ast
import asyncio
import builtins
from pathlib import Path

import pytest

from app import news

APP = Path(__file__).resolve().parents[1] / "app"


@pytest.mark.parametrize("path", sorted(APP.glob("*.py")), ids=lambda p: p.name)
def test_every_module_level_name_used_is_defined(path):
    """A module that calls http.session(...) without importing http imports
    fine and only fails when that code path runs (news.py did exactly this).
    Check statically: every Name loaded somewhere in the module must be
    bound somewhere in it (import, def, class, assignment, argument, loop,
    comprehension, with/except target) or be a builtin."""
    tree = ast.parse(path.read_text())
    bound: set[str] = set(dir(builtins)) | {"__file__", "__name__"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            bound |= {(a.asname or a.name).split(".")[0] for a in node.names}
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    assert used - bound == set()


RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Tolle to start Game 1 - MLB.com</title><link>https://example.com/a</link>
<pubDate>Tue, 29 Sep 2026 12:00:00 GMT</pubDate><source url="https://mlb.com">MLB.com</source></item>
<item><title>Old news - ESPN</title><link>https://example.com/b</link>
<pubDate>Tue, 01 Sep 2026 12:00:00 GMT</pubDate><source url="https://espn.com">ESPN</source></item>
</channel></rss>"""


def test_headlines_parse_and_drop_stale_items(fake_mlb, monkeypatch):
    from datetime import datetime, timezone

    fake_mlb.add("/rss/search", RSS)

    class FixedNow(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(news, "datetime", FixedNow)
    headlines = asyncio.run(news.get_recent_headlines())
    assert headlines == [
        {"title": "Tolle to start Game 1", "link": "https://example.com/a", "source": "MLB.com", "published": "2026-09-29T12:00:00+00:00"}
    ]
