# ha-notify

Send [Home Assistant](https://www.home-assistant.io/) notifications from the command line.

Built for unattended scripts — cron jobs, backups, CI — that need to put an alert on your
phone when something fails, including iOS **critical alerts** that break through silent mode
and Do Not Disturb.

```console
$ rsync -a /data /backup || ha-notify --critical "nightly backup failed: rsync exit $?"
```

## Install

```console
$ uv tool install ha-notify          # or: pipx install ha-notify
```

From a checkout:

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

Precedence is **flag → environment → built-in default**.

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
notify.mobile_app_alex_s_ipad
notify.persistent_notification
```

Set the one you want as `HA_NOTIFY_TARGET`, or pass `-T`. The `notify.` prefix is optional.

## Usage

```
ha-notify [-h] [-t TITLE] [-T TARGET] [-c] [--sound SOUND] [--volume VOLUME]
          [-u URL] [--timeout TIMEOUT] [-l] [-n] [--version] [message]
```

| Flag | Meaning |
| --- | --- |
| `-t`, `--title` | Notification title (default: this machine's short hostname) |
| `-T`, `--target` | Notify service, with or without the `notify.` prefix |
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

## Example: cron

```cron
0 3 * * * cd /srv/backup && ./nightly.sh 2>&1 || ha-notify -c "nightly backup failed"
```

`cd` into a directory containing `.env` and the token is picked up automatically.

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
