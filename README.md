# ha-notify

Send [Home Assistant](https://www.home-assistant.io/) notifications from the command line.

Built for unattended scripts — cron jobs, backups, CI — that need to put an alert on your
phone when something fails, including iOS **critical alerts** that break through silent mode
and Do Not Disturb.

```console
$ rsync -a /data /backup || ha-notify --critical "nightly backup failed: rsync exit $?"
```

## Install

This package is **not published to PyPI** — `uv tool install ha-notify` will fail. Install
from the repository:

```console
$ uv tool install git+https://github.com/seantrue/ha-notify.git@v0.2.0
```

...or from a wheel built locally, which is how the maintainer's hosts are updated:

```console
$ uv build
$ uv tool install --force dist/ha_notify-0.2.0-py3-none-any.whl
```

Note that `uv tool upgrade` cannot see a file-installed copy and will not keep it current.

From a checkout, for development:

```console
$ uv sync --extra dev
$ uv run ha-notify --version
```

## Configure

A long-lived access token is required. Create one in Home Assistant under
**Profile → Security → Long-lived access tokens**.

| Variable | Purpose | Default |
| --- | --- | --- |
| `HA_TOKEN` | Long-lived access token | *(required)* |
| `HA_URL` | Base URL of Home Assistant | `http://homeassistant.lan:8123` |
| `HA_NOTIFY_TARGET` | Notify service to send to | `mobile_app_iphone` |
| `HA_NOTIFY_INTERRUPTION_LEVEL` | Default iOS delivery priority | *(the app's own setting)* |
| `HA_NOTIFY_ALL_EXCLUDE` | Extra services `-T all` should skip, comma-separated | *(none)* |

Precedence is **flag → environment → built-in default**. A variable that is set but *empty* counts as unset, so a blanked or commented-out line in a sourced env file falls back to the default rather than overriding it with nothing.

If `HA_TOKEN` is not in the environment, `ha-notify` looks for a `.env` file in the current
directory and each parent. This is what makes it usable from cron, which starts with almost
no environment:

```sh
HA_TOKEN=eyJhbGciOi...
HA_URL=http://homeassistant.lan:8123
HA_NOTIFY_TARGET=mobile_app_alex_s_iphone
```

Real environment variables always win over `.env`.

### Finding your target

Home Assistant slugifies device names, and apostrophes become an underscore — "Alex's iPhone"
becomes `mobile_app_alex_s_iphone`, **not** `mobile_app_alexs_iphone`. Guessing wrong gets you
a bare `400: Bad Request` with no explanation, so ask instead:

```console
$ ha-notify --list-targets
notify.lg_tv
notify.mobile_app_alex_s_iphone
notify.notify
notify.persistent_notification
```

Set the one you want as `HA_NOTIFY_TARGET`, or pass `-T`. The `notify.` prefix is optional.

`--list-targets` is deliberately unfiltered — it shows everything Home Assistant offers,
including the aggregate services, because it is the command you reach for when a target you
expected is missing.

### Sending to everything

`-T all` expands to every notify service on the instance, which is what you want when the
alert matters more than the device — the power is out, the house is on fire, nobody is going
to be looking at one particular phone:

```console
$ ha-notify --critical -T all "sump pump has stopped"
```

The services that are aggregates rather than a device — `notify.notify`,
`notify.persistent_notification`, `notify.send_message` — are skipped, because sending through
them would double up on every phone. Anything else you never want paged (a wall-mounted kiosk,
a test target) goes in `HA_NOTIFY_ALL_EXCLUDE`, with or without the `notify.` prefix:

```sh
HA_NOTIFY_ALL_EXCLUDE=mobile_app_kiosk,notify.lg_tv
```

Delivery is attempted for every target even if one fails; see [Exit codes](#exit-codes).

## Usage

```
ha-notify [-h] [-t TITLE] [-T TARGET] [--interruption-level LEVEL]
          [--time-sensitive] [-c] [--sound SOUND] [--volume VOLUME]
          [-u URL] [--timeout TIMEOUT] [-l] [-n] [--version] [message]
```

| Flag | Meaning |
| --- | --- |
| `-t`, `--title` | Notification title (default: this machine's short hostname) |
| `-T`, `--target` | Notify service, with or without the `notify.` prefix; `all` for every device |
| `--interruption-level` | iOS delivery priority: `passive`, `active`, `time-sensitive` |
| `--time-sensitive` | Shorthand for `--interruption-level time-sensitive` |
| `-c`, `--critical` | Send as an iOS critical alert (bypasses silent / DND) |
| `--sound`, `--volume` | Critical alert sound name and volume, `0.0`–`1.0` |
| `-u`, `--url` | Home Assistant base URL |
| `--timeout` | Request timeout in seconds (default: 10) |
| `-l`, `--list-targets` | List available notify services and exit |
| `-n`, `--dry-run` | Print the request that would be sent, then exit |

The message can come from an argument or from stdin:

```console
$ ha-notify "disk 91% full"
$ df -h / | tail -1 | ha-notify --title "disk check"
```

The title defaults to the machine's hostname, which is usually what you want when several
boxes can page you.

## When only critical alerts get through

If `--critical` reliably reaches your phone but a plain `ha-notify` never seems to, the
notification is almost certainly arriving and being held back on the phone, not lost in
transit. Home Assistant returns `200` either way, so exit code `0` only means "handed to
Apple".

An ordinary notification is an `active` one, and iOS is free to hold those for a Focus mode
or roll them into the scheduled Notification Summary. Critical alerts are exempt from all of
that, which is why they feel like the only thing that works.

`--time-sensitive` is the middle ground: it breaks through Focus modes and the summary, and
unlike a critical alert it still respects the ringer switch and does not need the Critical
Alerts permission enabled.

```console
$ ha-notify --time-sensitive "disk 91% full"
```

To make that the default for every call, including cron jobs, put it in the environment or
`.env` rather than editing each call site:

```sh
HA_NOTIFY_INTERRUPTION_LEVEL=time-sensitive
```

Two things on the phone have to be right for this to take effect, both under
**Settings → Notifications → Home Assistant**: *Allow Notifications* on, and **Time Sensitive
Notifications** on. Check *Deliver Quietly* too — if a notification was ever swiped away with
"Deliver Quietly", every normal alert from the app goes straight to Notification Center with
no banner and no sound, which reads exactly like nothing arriving at all. If it is set, switch
the app back to *Deliver Prominently*.

Focus modes are configured separately: **Settings → Focus →** *(your mode)* **→ Apps**
controls which apps may interrupt, and *Time Sensitive Notifications* has to be allowed there
as well.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Notification delivered |
| `1` | Home Assistant rejected the request, or was unreachable |
| `2` | Usage or configuration error |

A calling script can distinguish "the job failed" from "the alert never got out":

```sh
if ! ha-notify --critical "backup failed"; then
    logger -p user.err "ha-notify could not deliver the alert"
fi
```

Unreachable hosts and timeouts print a single line rather than a traceback, because a stack
trace in cron mail is noise.

With `-T all`, one failing target does not stop the others: every target is attempted, each
failure is reported on stderr as it happens, and a `sent to 2 of 3 targets` summary follows.
The exit code is `1` if *any* target failed, so a zero exit means every device was reached. If
`all` expands to no targets, that is a `1` as well rather than a silent success.

## Example: cron

Cron does not read `.bashrc`, so the token has to reach the job some other way. Either `cd`
into a directory containing a `.env`:

```cron
0 3 * * * cd /srv/backup && ./nightly.sh || ha-notify -c "nightly backup failed"
```

...or keep the configuration in a mode-`600` file and source it, which avoids putting a
long-lived token in a world-readable `.bashrc`:

```sh
# ~/.config/ha-notify/env   (chmod 600)
export HA_TOKEN=eyJhbGciOi...
export HA_URL=http://homeassistant.lan:8123
export HA_NOTIFY_TARGET=mobile_app_alex_s_iphone
```

```cron
0 3 * * * . $HOME/.config/ha-notify/env; /srv/backup/nightly.sh || $HOME/.local/bin/ha-notify -c "nightly backup failed"
```

Use an absolute path to `ha-notify`: cron's `PATH` usually excludes `~/.local/bin`. Sourcing
the same file from `~/.bashrc` gives interactive shells the same configuration.

Without either, the command exits `2` with `HA_TOKEN not set`, rather than failing silently.

## Alternatives

**[`hass-cli`](https://github.com/home-assistant-ecosystem/home-assistant-cli)**
(`pip install homeassistant-cli`) is the general-purpose Home Assistant CLI — entities,
states, areas, templates, and service calls — and it is the right tool if you want to *drive*
Home Assistant from a terminal. It can send a notification:

```console
$ hass-cli service call notify.mobile_app_x --arguments message="backup failed"
```

Two things make it an awkward fit for the job `ha-notify` does. Its `--arguments` take flat
`key=value` pairs, so the nested `data.push.sound.critical` structure an iOS critical alert
requires is not straightforward to express — and critical alerts are the entire reason this
tool exists. And as of 1.0.0 it requires **Python 3.13+**, which rules it out on the older
boxes that tend to be the ones running the backup scripts. `ha-notify` supports 3.10+ and
depends only on `httpx`.

Otherwise the state of the art for this niche is a hand-rolled `curl` one-liner pasted out of
a blog post. That works — the prototype behind this package was exactly that — but it gives
you no `--list-targets` when Home Assistant answers a mistyped target with a bare
`400: Bad Request`, no distinction between "the alert failed to send" and "you invoked it
wrong", and a stack of shell quoting in your crontab.

If you are not tied to Home Assistant at all, [ntfy](https://ntfy.sh/) solves the same
"notify me from a shell script" problem with its own server and apps.

## Development

```console
$ uv sync --extra dev
$ uv run pytest -q
$ uv run ruff check .
```

The test suite is fully offline — `httpx` is monkeypatched, so no Home Assistant instance is
needed and no notifications are sent.

## License

MIT — see [LICENSE](LICENSE).
