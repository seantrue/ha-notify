import json
import os

import httpx
import pytest

from ha_notify import cli

TOKEN = "test-token"


# --- pure helpers ---------------------------------------------------------


@pytest.mark.parametrize(
    "given,expected",
    [
        ("mobile_app_x", "mobile_app_x"),
        ("notify.mobile_app_x", "mobile_app_x"),
        ("notify/mobile_app_x", "mobile_app_x"),
        # only the leading prefix is stripped
        ("notify.a_notify.b", "a_notify.b"),
    ],
)
def test_normalize_target(given, expected):
    assert cli.normalize_target(given) == expected


def test_build_payload_minimal():
    assert cli.build_payload("hi") == {"message": "hi"}


def test_build_payload_omits_empty_title():
    assert "title" not in cli.build_payload("hi", title="")


def test_build_payload_critical():
    payload = cli.build_payload("hi", title="t", critical=True, sound="alarm", volume=0.5)
    assert payload["title"] == "t"
    assert payload["data"]["push"]["sound"] == {
        "name": "alarm",
        "critical": 1,
        "volume": 0.5,
    }


def test_build_payload_non_critical_has_no_data():
    assert "data" not in cli.build_payload("hi", title="t", critical=False)


@pytest.mark.parametrize("level", cli.INTERRUPTION_LEVELS)
def test_build_payload_interruption_level(level):
    payload = cli.build_payload("hi", title="t", interruption_level=level)
    assert payload["data"] == {"push": {"interruption-level": level}}


def test_build_payload_critical_outranks_interruption_level():
    payload = cli.build_payload("hi", critical=True, interruption_level="passive")
    assert "interruption-level" not in payload["data"]["push"]
    assert payload["data"]["push"]["sound"]["critical"] == 1


def test_default_title_is_short_hostname(monkeypatch):
    monkeypatch.setattr(cli.socket, "gethostname", lambda: "buildhost.local")
    assert cli.default_title() == "buildhost"


# --- .env handling --------------------------------------------------------


def test_load_dotenv_sets_missing_vars(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('HA_TOKEN="abc"\nexport HA_URL=http://ha:8123\n# comment\n\nBAD_LINE\n')
    monkeypatch.chdir(tmp_path)
    assert cli.load_dotenv() == env
    assert os.environ["HA_TOKEN"] == "abc"
    assert os.environ["HA_URL"] == "http://ha:8123"


def test_load_dotenv_does_not_override_real_env(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("HA_TOKEN=from-file\n")
    monkeypatch.setenv("HA_TOKEN", "from-env")
    monkeypatch.chdir(tmp_path)
    cli.load_dotenv()
    assert os.environ["HA_TOKEN"] == "from-env"


def test_find_dotenv_walks_up(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("HA_TOKEN=x\n")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    assert cli.find_dotenv() == tmp_path / ".env"


def test_find_dotenv_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.find_dotenv() is None


# --- config / usage errors ------------------------------------------------


def test_missing_token_is_config_error(capsys):
    assert cli.main(["hello"]) == cli.EXIT_CONFIG
    assert "HA_TOKEN not set" in capsys.readouterr().err


def test_bad_volume_is_config_error(monkeypatch, capsys):
    monkeypatch.setenv("HA_TOKEN", TOKEN)
    assert cli.main(["hi", "--volume", "5"]) == cli.EXIT_CONFIG
    assert "--volume must be between" in capsys.readouterr().err


def test_empty_stdin_message_is_config_error(monkeypatch, capsys):
    monkeypatch.setenv("HA_TOKEN", TOKEN)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(cli.sys.stdin, "read", lambda: "   \n")
    assert cli.main([]) == cli.EXIT_CONFIG
    assert "message is empty" in capsys.readouterr().err


def test_no_message_on_tty_is_config_error(monkeypatch, capsys):
    monkeypatch.setenv("HA_TOKEN", TOKEN)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    assert cli.main([]) == cli.EXIT_CONFIG
    assert "no message given" in capsys.readouterr().err


def test_message_read_from_stdin(monkeypatch, capsys):
    monkeypatch.setenv("HA_TOKEN", TOKEN)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(cli.sys.stdin, "read", lambda: "  piped message\n")
    assert cli.main(["-n"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out.split("\n", 1)[1])["message"] == "piped message"


# --- dry run / precedence -------------------------------------------------


def test_dry_run_uses_defaults(monkeypatch, capsys):
    monkeypatch.setenv("HA_TOKEN", TOKEN)
    monkeypatch.setattr(cli.socket, "gethostname", lambda: "buildhost.local")
    assert cli.main(["boom", "-n"]) == cli.EXIT_OK
    line, body = capsys.readouterr().out.split("\n", 1)
    assert line == f"POST {cli.DEFAULT_URL}/api/services/notify/{cli.DEFAULT_TARGET}"
    assert json.loads(body) == {"message": "boom", "title": "buildhost"}


def test_env_overrides_builtin_defaults(monkeypatch, capsys):
    monkeypatch.setenv("HA_TOKEN", TOKEN)
    monkeypatch.setenv("HA_URL", "http://ha.example:8123")
    monkeypatch.setenv("HA_NOTIFY_TARGET", "mobile_app_phone")
    assert cli.main(["boom", "-n"]) == cli.EXIT_OK
    assert capsys.readouterr().out.splitlines()[0] == (
        "POST http://ha.example:8123/api/services/notify/mobile_app_phone"
    )


def test_flag_overrides_env(monkeypatch, capsys):
    monkeypatch.setenv("HA_TOKEN", TOKEN)
    monkeypatch.setenv("HA_URL", "http://from-env:8123")
    assert cli.main(["boom", "-n", "-u", "http://from-flag:8123/"]) == cli.EXIT_OK
    # trailing slash stripped
    assert capsys.readouterr().out.splitlines()[0].startswith("POST http://from-flag:8123/api/")


def test_dotenv_reaches_url_default(tmp_path, monkeypatch, capsys):
    """Regression: .env must load before parse_args() evaluates --url's default."""
    (tmp_path / ".env").write_text("HA_TOKEN=abc\nHA_URL=http://from-dotenv:8123\n")
    monkeypatch.chdir(tmp_path)
    assert cli.main(["boom", "-n"]) == cli.EXIT_OK
    assert capsys.readouterr().out.splitlines()[0].startswith("POST http://from-dotenv:8123/")


def test_version(capsys):
    from ha_notify import __version__

    assert cli.main(["--version"]) == cli.EXIT_OK
    assert capsys.readouterr().out.strip() == f"ha-notify {__version__}"


# --- send() ---------------------------------------------------------------


def mock_post(monkeypatch, response=None, raises=None, captured=None):
    def fake_post(url, **kwargs):
        if captured is not None:
            captured["url"] = url
            captured.update(kwargs)
        if raises is not None:
            raise raises
        return response

    monkeypatch.setattr(cli.httpx, "post", fake_post)


def make_response(status_code, text="", json_body=None):
    request = httpx.Request("POST", "http://ha/api")
    if json_body is not None:
        return httpx.Response(status_code, json=json_body, request=request)
    return httpx.Response(status_code, text=text, request=request)


def test_send_success(monkeypatch):
    captured = {}
    mock_post(monkeypatch, response=make_response(200, "[]"), captured=captured)
    rc = cli.send("http://ha:8123", TOKEN, "mobile_app_x", {"message": "hi"})
    assert rc == cli.EXIT_OK
    assert captured["url"] == "http://ha:8123/api/services/notify/mobile_app_x"
    assert captured["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert captured["json"] == {"message": "hi"}


def test_send_400_hints_at_target(monkeypatch, capsys):
    mock_post(monkeypatch, response=make_response(400, "400: Bad Request"))
    assert cli.send("http://ha:8123", TOKEN, "typo_target", {}) == cli.EXIT_FAILED
    err = capsys.readouterr().err
    assert "notify failed: 400" in err
    assert "notify.typo_target' may not exist" in err


def test_send_401_hints_at_token(monkeypatch, capsys):
    mock_post(monkeypatch, response=make_response(401, "Unauthorized"))
    assert cli.send("http://ha:8123", TOKEN, "x", {}) == cli.EXIT_FAILED
    assert "HA_TOKEN is invalid or expired" in capsys.readouterr().err


def test_send_500_hints_at_the_integration(monkeypatch, capsys):
    mock_post(monkeypatch, response=make_response(500, "Internal Server Error"))
    assert cli.send("http://ha:8123", TOKEN, "lg_tv", {}) == cli.EXIT_FAILED
    err = capsys.readouterr().err
    assert "notify failed: 500" in err
    assert "notify.lg_tv" in err


def test_send_unreachable_is_not_a_traceback(monkeypatch, capsys):
    mock_post(monkeypatch, raises=httpx.ConnectTimeout("timed out"))
    assert cli.send("http://ha:8123", TOKEN, "x", {}) == cli.EXIT_FAILED
    assert "could not reach http://ha:8123" in capsys.readouterr().err


def test_main_end_to_end_critical(monkeypatch):
    monkeypatch.setenv("HA_TOKEN", TOKEN)
    captured = {}
    mock_post(monkeypatch, response=make_response(200, "[]"), captured=captured)
    rc = cli.main(["rsync exit 23", "-t", "backup failed", "--critical", "-T", "notify.phone"])
    assert rc == cli.EXIT_OK
    assert captured["url"].endswith("/api/services/notify/phone")
    assert captured["json"] == {
        "message": "rsync exit 23",
        "title": "backup failed",
        "data": {"push": {"sound": {"name": "default", "critical": 1, "volume": 1.0}}},
    }


def test_main_end_to_end_time_sensitive(monkeypatch):
    monkeypatch.setenv("HA_TOKEN", TOKEN)
    captured = {}
    mock_post(monkeypatch, response=make_response(200, "[]"), captured=captured)
    rc = cli.main(["disk 91% full", "-t", "disk check", "--time-sensitive", "-T", "phone"])
    assert rc == cli.EXIT_OK
    assert captured["json"] == {
        "message": "disk 91% full",
        "title": "disk check",
        "data": {"push": {"interruption-level": "time-sensitive"}},
    }


def test_interruption_level_defaults_from_environment(monkeypatch):
    monkeypatch.setenv("HA_NOTIFY_INTERRUPTION_LEVEL", "time-sensitive")
    args = cli.parse_args(["hi"])
    assert args.interruption_level == "time-sensitive"


def test_interruption_level_flag_beats_environment(monkeypatch):
    monkeypatch.setenv("HA_NOTIFY_INTERRUPTION_LEVEL", "time-sensitive")
    args = cli.parse_args(["hi", "--interruption-level", "passive"])
    assert args.interruption_level == "passive"


def test_bad_interruption_level_in_environment_is_a_config_error(monkeypatch, capsys):
    monkeypatch.setenv("HA_TOKEN", TOKEN)
    monkeypatch.setenv("HA_NOTIFY_INTERRUPTION_LEVEL", "urgent")
    assert cli.main(["hi"]) == cli.EXIT_CONFIG
    assert "unknown interruption level 'urgent'" in capsys.readouterr().err


# --- list_targets ---------------------------------------------------------


SERVICES_BODY = [
    {"domain": "light", "services": {"turn_on": {}}},
    {"domain": "notify", "services": {"mobile_app_b": {}, "mobile_app_a": {}, "lg_tv": {}}},
]


def test_list_targets_sorted(monkeypatch, capsys):
    monkeypatch.setattr(
        cli.httpx, "get", lambda url, **kw: make_response(200, json_body=SERVICES_BODY)
    )
    assert cli.list_targets("http://ha:8123", TOKEN) == cli.EXIT_OK
    assert capsys.readouterr().out.split() == [
        "notify.lg_tv",
        "notify.mobile_app_a",
        "notify.mobile_app_b",
    ]


def test_list_targets_unreachable(monkeypatch, capsys):
    def boom(url, **kw):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(cli.httpx, "get", boom)
    assert cli.list_targets("http://ha:8123", TOKEN) == cli.EXIT_FAILED
    assert "could not reach" in capsys.readouterr().err


def test_list_targets_is_unfiltered(monkeypatch, capsys):
    """--list-targets shows aggregates too; it is how you debug a missing target."""
    body = [{"domain": "notify", "services": {"notify": {}, "mobile_app_a": {}}}]
    monkeypatch.setattr(
        cli.httpx, "get", lambda url, **kw: make_response(200, json_body=body)
    )
    assert cli.list_targets("http://ha:8123", TOKEN) == cli.EXIT_OK
    assert capsys.readouterr().out.split() == ["notify.mobile_app_a", "notify.notify"]


def test_list_targets_failure_does_not_fall_through_to_sending(monkeypatch, capsys):
    monkeypatch.setenv("HA_TOKEN", TOKEN)
    monkeypatch.setattr(cli.httpx, "get", lambda url, **kw: make_response(500, "boom"))
    mock_post(monkeypatch, raises=AssertionError("must not send a notification"))
    assert cli.main(["--list-targets"]) == cli.EXIT_FAILED
    assert "could not list services: 500" in capsys.readouterr().err


# --- --target all ---------------------------------------------------------


def mock_get(monkeypatch, json_body=SERVICES_BODY, status_code=200):
    monkeypatch.setattr(
        cli.httpx, "get", lambda url, **kw: make_response(status_code, json_body=json_body)
    )


def test_excluded_from_all_defaults():
    excluded = cli.excluded_from_all(env={})
    assert excluded == set(cli.DEFAULT_ALL_EXCLUDES)


def test_excluded_from_all_extends_from_environment():
    env = {"HA_NOTIFY_ALL_EXCLUDE": "mobile_app_kiosk, notify.lg_tv ,"}
    excluded = cli.excluded_from_all(env=env)
    assert {"mobile_app_kiosk", "lg_tv"} <= excluded
    assert set(cli.DEFAULT_ALL_EXCLUDES) <= excluded


def test_expand_all_drops_aggregates_and_strips_prefix(monkeypatch):
    body = [
        {"domain": "light", "services": {"turn_on": {}}},
        {
            "domain": "notify",
            "services": {
                "mobile_app_b": {},
                "mobile_app_a": {},
                "notify": {},
                "persistent_notification": {},
                "send_message": {},
            },
        },
    ]
    mock_get(monkeypatch, json_body=body)
    assert cli.expand_all("http://ha:8123", TOKEN) == (
        cli.EXIT_OK,
        ["mobile_app_a", "mobile_app_b"],
    )


def test_expand_all_honours_the_exclude_environment_variable(monkeypatch):
    monkeypatch.setenv("HA_NOTIFY_ALL_EXCLUDE", "lg_tv")
    mock_get(monkeypatch)
    assert cli.expand_all("http://ha:8123", TOKEN) == (
        cli.EXIT_OK,
        ["mobile_app_a", "mobile_app_b"],
    )


def test_expand_all_with_no_surviving_targets_is_a_failure(monkeypatch, capsys):
    mock_get(monkeypatch, json_body=[{"domain": "notify", "services": {"notify": {}}}])
    assert cli.expand_all("http://ha:8123", TOKEN) == (cli.EXIT_FAILED, None)
    assert "matched no notify services" in capsys.readouterr().err


def test_expand_all_propagates_a_fetch_failure(monkeypatch, capsys):
    mock_get(monkeypatch, status_code=401)
    assert cli.expand_all("http://ha:8123", TOKEN) == (cli.EXIT_FAILED, None)
    assert "could not list services: 401" in capsys.readouterr().err


def test_all_sends_to_every_target(monkeypatch, capsys):
    monkeypatch.setenv("HA_TOKEN", TOKEN)
    mock_get(monkeypatch)
    sent = []

    def fake_post(url, **kwargs):
        sent.append(url)
        return make_response(200, "[]")

    monkeypatch.setattr(cli.httpx, "post", fake_post)
    assert cli.main(["-T", "all", "power is out"]) == cli.EXIT_OK
    assert sent == [
        "http://homeassistant.lan:8123/api/services/notify/lg_tv",
        "http://homeassistant.lan:8123/api/services/notify/mobile_app_a",
        "http://homeassistant.lan:8123/api/services/notify/mobile_app_b",
    ]
    assert "sent to 3 of 3 targets" in capsys.readouterr().err


def test_notify_all_is_the_same_as_all(monkeypatch):
    monkeypatch.setenv("HA_TOKEN", TOKEN)
    mock_get(monkeypatch)
    sent = []

    def fake_post(url, **kwargs):
        sent.append(url)
        return make_response(200, "[]")

    monkeypatch.setattr(cli.httpx, "post", fake_post)
    assert cli.main(["-T", "notify.all", "hi"]) == cli.EXIT_OK
    assert len(sent) == 3


def test_all_keeps_going_after_a_failure_but_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setenv("HA_TOKEN", TOKEN)
    mock_get(monkeypatch)
    sent = []

    def fake_post(url, **kwargs):
        sent.append(url)
        if url.endswith("mobile_app_a"):
            return make_response(500, "Internal Server Error")
        return make_response(200, "[]")

    monkeypatch.setattr(cli.httpx, "post", fake_post)
    assert cli.main(["-T", "all", "power is out"]) == cli.EXIT_FAILED
    assert len(sent) == 3, "a failure must not abort the remaining targets"
    err = capsys.readouterr().err
    assert "notify.mobile_app_a" in err
    assert "sent to 2 of 3 targets" in err


def test_all_builds_the_payload_once_per_run(monkeypatch):
    """Every target gets the same body, and the hostname is resolved once."""
    monkeypatch.setenv("HA_TOKEN", TOKEN)
    mock_get(monkeypatch)
    hostname_calls = []

    def gethostname():
        hostname_calls.append(1)
        return "buildhost.local"

    monkeypatch.setattr(cli.socket, "gethostname", gethostname)
    bodies = []

    def fake_post(url, **kwargs):
        bodies.append(kwargs["json"])
        return make_response(200, "[]")

    monkeypatch.setattr(cli.httpx, "post", fake_post)
    assert cli.main(["-T", "all", "hi"]) == cli.EXIT_OK
    assert bodies == [{"message": "hi", "title": "buildhost"}] * 3
    assert len(hostname_calls) == 1


def test_all_dry_run_prints_every_target(monkeypatch, capsys):
    monkeypatch.setenv("HA_TOKEN", TOKEN)
    mock_get(monkeypatch)
    mock_post(monkeypatch, raises=AssertionError("dry run must not send"))
    assert cli.main(["-T", "all", "hi", "-n"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert out.count("POST ") == 3
    assert "/api/services/notify/lg_tv" in out


def test_all_unreachable_does_not_send(monkeypatch, capsys):
    monkeypatch.setenv("HA_TOKEN", TOKEN)

    def boom(url, **kw):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(cli.httpx, "get", boom)
    mock_post(monkeypatch, raises=AssertionError("must not send a notification"))
    assert cli.main(["-T", "all", "hi"]) == cli.EXIT_FAILED
    assert "could not reach" in capsys.readouterr().err


def test_all_from_the_environment(monkeypatch):
    monkeypatch.setenv("HA_TOKEN", TOKEN)
    monkeypatch.setenv("HA_NOTIFY_TARGET", "all")
    mock_get(monkeypatch)
    sent = []
    monkeypatch.setattr(
        cli.httpx, "post", lambda url, **kw: (sent.append(url), make_response(200, "[]"))[1]
    )
    assert cli.main(["hi"]) == cli.EXIT_OK
    assert len(sent) == 3
