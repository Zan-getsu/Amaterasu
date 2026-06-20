"""Phase 6.1 — Config smoke tests.

Tests bool/int/list coercion and ast.literal_eval safety.
"""

import pytest


def test_bool_coercion():
    """Config._convert_env_type correctly coerces strings to bools."""
    from bot.core.config_manager import Config
    # True values
    for val in ["true", "True", "1", "yes", "on", "t", "y"]:
        result = Config._convert_env_type("BOT_PM", val)
        assert result is True, f"{val} should coerce to True"
    # False values
    for val in ["false", "0", "no", "off", "f", "n", ""]:
        result = Config._convert_env_type("BOT_PM", val)
        assert result is False, f"{val} should coerce to False"


def test_int_coercion():
    """Config._convert_env_type correctly coerces strings to ints."""
    from bot.core.config_manager import Config
    assert Config._convert_env_type("OWNER_ID", "123456789") == 123456789
    assert Config._convert_env_type("OWNER_ID", "0") == 0
    # Invalid int falls back to original
    result = Config._convert_env_type("OWNER_ID", "not_a_number")
    assert result == Config.OWNER_ID  # falls back to default


def test_list_coercion():
    """Config._convert_env_type correctly coerces strings to lists."""
    from bot.core.config_manager import Config
    # JSON list
    result = Config._convert_env_type("IMG_SOURCES", '["wallpaperflare", "wallhaven"]')
    assert result == ["wallpaperflare", "wallhaven"]
    # Comma-separated
    result = Config._convert_env_type("IMG_SOURCES", "wallpaperflare,wallhaven")
    assert result == ["wallpaperflare", "wallhaven"]
    # Python-literal syntax (backward compat)
    result = Config._convert_env_type("IMG_SOURCES", "['a', 'b']")
    assert result == ["a", "b"]


def test_literal_eval_safety():
    """ast.literal_eval rejects names and calls (safe)."""
    from ast import literal_eval
    # Literals are accepted
    assert literal_eval("123") == 123
    assert literal_eval("'hello'") == "hello"
    assert literal_eval("[1, 2, 3]") == [1, 2, 3]
    assert literal_eval("{'a': 1}") == {"a": 1}
    # Names and calls are rejected
    with pytest.raises((ValueError, SyntaxError)):
        literal_eval("__import__('os')")
    with pytest.raises((ValueError, SyntaxError)):
        literal_eval("os.system('rm -rf /')")
    with pytest.raises((ValueError, SyntaxError)):
        literal_eval("open('/etc/passwd')")
