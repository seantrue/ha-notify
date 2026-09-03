"""
Send a notification through Home Assistant from the command line.

Intended for unattended scripts (cron, backups, CI) that need to alert a phone
when something fails.

Usage:
    ha-notify "rsync exit 23" --title "backup failed" --critical
    ha-notify --time-sensitive "disk 91% full"    # breaks through Focus
    rsync ... || ha-notify --critical "nightly backup failed"
    some-job | ha-notify --title "job output"     # message from stdin
    ha-notify -T all "the power is out"           # fan out to every device
    ha-notify --list-targets

Configuration (flags override environment, environment overrides defaults):
    HA_URL              base URL of Home Assistant  [http://homeassistant.lan:8123]
    HA_TOKEN            long-lived access token     (required)
    HA_NOTIFY_TARGET    default notify service      [mobile_app_iphone]
    HA_NOTIFY_INTERRUPTION_LEVEL
                        default iOS delivery priority         [unset]
    HA_NOTIFY_ALL_EXCLUDE
                        comma-separated services to skip for -T all  [unset]

If HA_TOKEN is not set, a .env file is read as a fallback (see find_dotenv), so
cron jobs work without sourcing it first.

Exit codes:
    0  notification delivered
    1  Home Assistant rejected the request or was unreachable
    2  usage / configuration error

With -T all the exit code is 1 if any target failed, even if others succeeded;
each failure is reported on stderr as it happens.
"""

import argparse
import json
import os
import socket
import sys
from pathlib import Path

import httpx

DEFAULT_URL = "http://homeassistant.lan:8123"
# Home Assistant slugifies notify targets, and apostrophes become an underscore:
# "Alex's iPhone" -> mobile_app_alex_s_iphone. Use --list-targets to see real names.
DEFAULT_TARGET = "mobile_app_iphone"
DEFAULT_TIMEOUT = 10.0

# --target all means "every phone/speaker", so skip the notify services that are
# aggregates or not a device at all. Site-specific ones (a kiosk, a test target)
# belong in $HA_NOTIFY_ALL_EXCLUDE rather than here.
DEFAULT_ALL_EXCLUDES = ("notify", "persistent_notification", "send_message")
ALL_TARGET = "all"

# iOS interruption levels, quietest first. 'critical' is deliberately absent: it needs a
# sound and volume as well, so it has its own --critical flag.
INTERRUPTION_LEVELS = ("passive", "active", "time-sensitive")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CONFIG = 2


def find_dotenv(start=None):
    """Return the nearest .env walking up from start (default: cwd), or None."""
    start = Path(start) if start else Path.cwd()
    start = start.resolve()
    for directory in [start, *start.parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


def load_dotenv(path=None):
    """Populate os.environ from a .env file, without overriding real env vars."""
    env_file = Path(path) if path else find_dotenv()
    if env_file is None or not env_file.is_file():
        return None
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)
    return env_file


def normalize_target(target):
    """Accept 'notify.foo', 'notify/foo' or 'foo' and return the bare service name."""
    return target.replace("notify.", "", 1).replace("notify/", "", 1)


def excluded_from_all(env=None):
    """Service names --target all should skip: the defaults plus $HA_NOTIFY_ALL_EXCLUDE."""
    env = os.environ if env is None else env
    extra = env.get("HA_NOTIFY_ALL_EXCLUDE", "")
    return set(DEFAULT_ALL_EXCLUDES) | {
        normalize_target(name.strip()) for name in extra.split(",") if name.strip()
    }


def default_title():
    """Short hostname, which is what you want to see on a phone at 3am."""
    return socket.gethostname().split(".")[0]


def build_payload(message, title=None, critical=False, sound="default", volume=1.0,
                  interruption_level=None):
    """Build the JSON body for the notify service call.

    A critical alert already outranks every interruption level, so --critical wins if
    both are given.
    """
    payload = {"message": message}
    if title:
        payload["title"] = title
    if critical:
        payload["data"] = {
            "push": {"sound": {"name": sound, "critical": 1, "volume": volume}}
        }
    elif interruption_level:
        payload["data"] = {"push": {"interruption-level": interruption_level}}
    return payload

def fetch_targets(url, token, timeout=DEFAULT_TIMEOUT):
    """Fetch every notify service. Returns (exit code, ['notify.foo', ...] or None)."""
    try:
        r = httpx.get(
            f"{url}/api/services",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
    except httpx.HTTPError as e:
        print(f"could not reach {url}: {e}", file=sys.stderr)
        return EXIT_FAILED, None
    if r.status_code != 200:
        print(f"could not list services: {r.status_code} {r.text}", file=sys.stderr)
        return EXIT_FAILED, None
    targets = []
    for domain in r.json():
        if domain["domain"] == "notify":
            targets.extend(f"notify.{service}" for service in sorted(domain["services"]))
    return EXIT_OK, targets


def list_targets(url, token, timeout=DEFAULT_TIMEOUT, out=None):
    """Print available notify services. Returns an exit code.

    Deliberately unfiltered: this is the command you run to find out why a target
    you expected is missing, so it has to show everything Home Assistant offers.
    """
    out = out or sys.stdout
    code, targets = fetch_targets(url, token, timeout)
    if code != EXIT_OK:
        return code
    for target in targets:
        print(target, file=out)
    return EXIT_OK


def expand_all(url, token, timeout=DEFAULT_TIMEOUT):
    """Resolve --target all to bare service names. Returns (exit code, [...] or None)."""
    code, targets = fetch_targets(url, token, timeout)
    if code != EXIT_OK:
        return code, None
    excluded = excluded_from_all()
    targets = [t for t in (normalize_target(t) for t in targets) if t not in excluded]
    if not targets:
        # Sending nothing and reporting success would be the worst outcome for a
        # cron job whose whole purpose is to shout when something broke.
        print(f"--target {ALL_TARGET} matched no notify services", file=sys.stderr)
        return EXIT_FAILED, None
    return EXIT_OK, targets


def send(url, token, target, payload, timeout=DEFAULT_TIMEOUT):
    """POST the notification. Returns an exit code, printing diagnostics on failure."""
    endpoint = f"{url}/api/services/notify/{target}"
    try:
        r = httpx.post(
            endpoint,
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=timeout,
        )
    except httpx.HTTPError as e:
        print(f"could not reach {url}: {e}", file=sys.stderr)
        return EXIT_FAILED

    if r.status_code == 200:
        return EXIT_OK

    print(f"notify failed: {r.status_code} {r.text}", file=sys.stderr)
    if r.status_code == 400:
        print(
            f"hint: 'notify.{target}' may not exist; run --list-targets to see valid names",
            file=sys.stderr,
        )
    elif r.status_code == 401:
        print("hint: HA_TOKEN is invalid or expired", file=sys.stderr)
    elif r.status_code == 500:
        print(
            f"hint: Home Assistant errored delivering to 'notify.{target}'; the "
            "integration behind it may be offline",
            file=sys.stderr,
        )
    return EXIT_FAILED


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="ha-notify",
        description="Send a notification through Home Assistant.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="If MESSAGE is omitted and stdin is a pipe, the message is read from stdin.",
    )
    parser.add_argument("message", nargs="?", help="notification body (default: read from stdin)")
    parser.add_argument(
        "-t", "--title", default=None,
        help="notification title (default: this machine's hostname)",
    )
    parser.add_argument(
        "-T", "--target",
        default=os.environ.get("HA_NOTIFY_TARGET", DEFAULT_TARGET),
        help="notify service, with or without the 'notify.' prefix; "
             f"'{ALL_TARGET}' sends to every device (see $HA_NOTIFY_ALL_EXCLUDE) "
             f"(default: $HA_NOTIFY_TARGET or {DEFAULT_TARGET})",
    )
    parser.add_argument(
        "--interruption-level", choices=INTERRUPTION_LEVELS,
        default=os.environ.get("HA_NOTIFY_INTERRUPTION_LEVEL"),
        help="iOS delivery priority (default: $HA_NOTIFY_INTERRUPTION_LEVEL, else whatever "
             "the companion app is configured for)",
    )
    parser.add_argument(
        "--time-sensitive", action="store_const", const="time-sensitive",
        dest="interruption_level",
        help="shorthand for --interruption-level time-sensitive; breaks through Focus "
             "modes and the notification summary without needing a critical alert",
    )
    parser.add_argument(
        "-c", "--critical", action="store_true",
        help="send as an iOS critical alert (bypasses silent/do-not-disturb)",
    )
    parser.add_argument("--sound", default="default",
                        help="critical alert sound name (default: default)")
    parser.add_argument("--volume", type=float, default=1.0,
                        help="critical alert volume, 0.0-1.0 (default: 1.0)")
    parser.add_argument(
        "-u", "--url", default=os.environ.get("HA_URL", DEFAULT_URL),
        help=f"Home Assistant base URL (default: $HA_URL or {DEFAULT_URL})",
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help=f"request timeout in seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("-l", "--list-targets", action="store_true",
                        help="list available notify services and exit")
    parser.add_argument("-n", "--dry-run", action="store_true",
                        help="print the request that would be sent, then exit")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    return parser.parse_args(argv)


def main(argv=None):
    """Entry point returning an exit code (does not call sys.exit)."""
    # Must run before parse_args(): the --url/--target defaults read os.environ.
    load_dotenv()
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if args.version:
        from ha_notify import __version__

        print(f"ha-notify {__version__}")
        return EXIT_OK

    args.url = args.url.rstrip("/")
    token = os.environ.get("HA_TOKEN")
    if not token:
        print("HA_TOKEN not set (and no .env found)", file=sys.stderr)
        return EXIT_CONFIG

    if args.list_targets:
        return list_targets(args.url, token, args.timeout)

    if args.message is None:
        if sys.stdin.isatty():
            print("no message given (pass one as an argument or pipe it in)", file=sys.stderr)
            return EXIT_CONFIG
        args.message = sys.stdin.read().strip()
    if not args.message:
        print("message is empty", file=sys.stderr)
        return EXIT_CONFIG

    if not 0.0 <= args.volume <= 1.0:
        print("--volume must be between 0.0 and 1.0", file=sys.stderr)
        return EXIT_CONFIG

    # argparse enforces choices on the flag but not on a default taken from the
    # environment, so a typo in HA_NOTIFY_INTERRUPTION_LEVEL has to be caught here.
    if args.interruption_level and args.interruption_level not in INTERRUPTION_LEVELS:
        print(
            f"unknown interruption level {args.interruption_level!r} "
            f"(expected one of: {', '.join(INTERRUPTION_LEVELS)})",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    # 'all' is matched after normalizing, so 'notify.all' means the same thing. It
    # shadows any real service actually named 'all'.
    target = normalize_target(args.target)
    if target == ALL_TARGET:
        code, targets = expand_all(args.url, token, args.timeout)
        if code != EXIT_OK:
            return code
    else:
        targets = [target]

    payload = build_payload(
        args.message,
        title=args.title if args.title is not None else default_title(),
        critical=args.critical,
        sound=args.sound,
        volume=args.volume,
        interruption_level=args.interruption_level,
    )

    worst = EXIT_OK
    delivered = 0
    for target in targets:
        if args.dry_run:
            print(f"POST {args.url}/api/services/notify/{target}")
            print(json.dumps(payload, indent=2))
            result = EXIT_OK
        else:
            result = send(args.url, token, target, payload, args.timeout)
        if result == EXIT_OK:
            delivered += 1
        else:
            worst = result
    if len(targets) > 1:
        print(f"sent to {delivered} of {len(targets)} targets", file=sys.stderr)
    return worst


def run():
    """Console-script wrapper: main() but exits the process."""
    sys.exit(main())


if __name__ == "__main__":
    run()
