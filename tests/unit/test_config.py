"""The configuration guards.

Every variable is optional — the server runs with an empty environment — but a value that IS set and
is wrong must fail at import with the variable named, rather than surfacing later as a confusing
timeout or a 404 from an endpoint nobody realised was hardcoded.

config.py resolves on import, so each test reloads the module with a patched environment. The
expected exception is matched as ValueError, not ConfigError: importlib.reload REDEFINES the class,
so the object raised inside the reload is not the same object a reference captured beforehand would
be. ConfigError subclasses ValueError precisely so a caller never has to care about that.
"""

import importlib

import pytest

import rs_mcp_server.config as config_module


def load(**env: str):
    """Reload config with exactly `env` layered over a cleared environment."""
    with pytest.MonkeyPatch.context() as mp:
        for name in (
            "MCP_HOST",
            "MCP_PORT",
            "HTTP_TIMEOUT",
            "HTTP_MAX_RETRIES",
            "USER_AGENT",
            "RS3_WIKI_API",
            "OSRS_WIKI_API",
            "RS3_WIKI_BASE",
            "OSRS_WIKI_BASE",
            "OSRS_PRICES_BASE",
            "RS3_HISCORES_URL",
            "OSRS_HISCORES_URL",
        ):
            mp.delenv(name, raising=False)
        for key, value in env.items():
            mp.setenv(key, value)
        return importlib.reload(config_module)


@pytest.fixture(autouse=True)
def _restore():
    """Leave the module as the rest of the suite found it."""
    yield
    importlib.reload(config_module)


def test_empty_environment_is_valid():
    cfg = load()
    assert cfg.MCP_HOST == "127.0.0.1"
    assert cfg.MCP_PORT == 8000
    assert cfg.HTTP_TIMEOUT == 10.0
    assert cfg.HTTP_MAX_RETRIES == 2
    assert cfg.WIKI_APIS["rs3"] == "https://runescape.wiki/api.php"
    assert cfg.WIKI_APIS["osrs"] == "https://oldschool.runescape.wiki/api.php"
    assert cfg.HISCORES_URLS["osrs"].endswith("m=hiscore_oldschool/index_lite.json")


def test_dev_binds_loopback_not_every_interface():
    # A dev server that binds 0.0.0.0 the moment you run it is a surprise, not a convenience.
    # The container opts in explicitly.
    assert load().MCP_HOST == "127.0.0.1"
    assert load(MCP_HOST="0.0.0.0").MCP_HOST == "0.0.0.0"


def test_port_is_accepted_when_valid():
    assert load(MCP_PORT="9000").MCP_PORT == 9000


@pytest.mark.parametrize("bad", ["abc", "0", "70000", "-1", "8000.5"])
def test_bad_port_fails_naming_the_variable(bad):
    with pytest.raises(ValueError, match="MCP_PORT"):
        load(MCP_PORT=bad)


def test_endpoints_can_be_pointed_at_a_mirror():
    cfg = load(
        RS3_WIKI_API="https://mirror.example/api.php",
        OSRS_PRICES_BASE="http://localhost:9999/prices",
    )
    assert cfg.WIKI_APIS["rs3"] == "https://mirror.example/api.php"
    assert cfg.OSRS_PRICES_BASE == "http://localhost:9999/prices"
    # …and the one that was not overridden keeps its default.
    assert cfg.WIKI_APIS["osrs"] == "https://oldschool.runescape.wiki/api.php"


@pytest.mark.parametrize(
    "name", ["RS3_WIKI_API", "OSRS_WIKI_BASE", "OSRS_PRICES_BASE", "OSRS_HISCORES_URL"]
)
def test_a_bare_hostname_is_rejected_rather_than_silently_requested(name):
    # httpx would raise on this far downstream, inside a tool call, as an unhelpful error.
    with pytest.raises(ValueError, match=name):
        load(**{name: "example.com/api.php"})


def test_timeout_must_be_a_positive_number():
    assert load(HTTP_TIMEOUT="2.5").HTTP_TIMEOUT == 2.5
    with pytest.raises(ValueError, match="HTTP_TIMEOUT"):
        load(HTTP_TIMEOUT="0")
    with pytest.raises(ValueError, match="HTTP_TIMEOUT"):
        load(HTTP_TIMEOUT="soon")


def test_retries_may_be_disabled_but_not_negative():
    assert load(HTTP_MAX_RETRIES="0").HTTP_MAX_RETRIES == 0
    with pytest.raises(ValueError, match="HTTP_MAX_RETRIES"):
        load(HTTP_MAX_RETRIES="-1")


def test_user_agent_defaults_to_the_running_version_and_can_carry_a_contact():
    # The wikis ask that tools identify themselves; a deployment should be able to add a contact
    # address without editing source.
    assert load().USER_AGENT.startswith("RS-MCP-Server/")
    custom = "RS-MCP-Server/9 (+https://example.com/contact)"
    assert load(USER_AGENT=custom).USER_AGENT == custom
