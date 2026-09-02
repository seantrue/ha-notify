# AI Contributions

Tracks the split between the human maintainer and AI assistants (Claude Code) for this
project. Updated whenever a commit message is written.

## Origin

`ha-notify` was extracted from a prototype (`foo.py`) in the maintainer's `esphome`
repository. The prototype established the requirement and the working shape of the
Home Assistant REST call, including the iOS critical-alert payload.

## Split by area

| Area | Human | AI |
| --- | --- | --- |
| Requirement & problem framing | All | — |
| Original prototype (`foo.py`, ~25 LOC) | All | — |
| Critical-alert payload shape | Original | Carried forward unchanged |
| Root-cause diagnosis of the send failure | Reported symptom | Diagnosis |
| CLI design (flags, defaults, exit codes) | Direction: "appropriate defaults" | Design & implementation |
| Package layout, `pyproject.toml`, build | Direction | All |
| Test suite | — | All |
| README / AI.md | — | All |

## Detail

**Human.** Identified the need for a phone alert from unattended backup scripts, wrote the
original prototype against the Home Assistant REST API, and determined the correct
`data.push.sound` structure for an iOS critical alert — that payload was correct in the
prototype and is unchanged here. Reported that the prototype was not delivering alerts, and
directed the extraction into a standalone, installable tool.

**AI (Claude Code).** Diagnosed the delivery failure: the target service name was
`mobile_app_alexs_iphone`, but Home Assistant slugifies "Alex's iPhone" to
`mobile_app_alex_s_iphone`. HA answers an unknown service with a bare `400: Bad Request`
and no detail, which is why the cause was not visible. Verified against the live instance
by enumerating `/api/services`.

Built the CLI around that finding — `--list-targets` and the `400` hint exist specifically
so this failure diagnoses itself next time. Added argparse flags, three-level configuration
precedence (flag → environment → built-in), `.env` discovery walking up from the working
directory so cron jobs work without a sourced environment, distinct exit codes separating
"alert failed to send" from "invoked wrong", stdin message input, and single-line error
reporting for unreachable hosts instead of tracebacks in cron mail.

Packaged the project (hatchling, `src/` layout, `ha-notify` console script), wrote the
offline test suite, and wrote the documentation.

Two defects in AI-written code were caught by AI testing before commit: `.env` was loaded
after `parse_args()` had already evaluated the `--url` and `--target` defaults, so only
`HA_TOKEN` benefited from it (covered now by `test_dotenv_reaches_url_default`); and the
default title used the full `.local` FQDN rather than the short hostname.

## 0.2.0: iOS interruption levels

**Human.** Reported the symptom: "unless I assert a notification is critical, they do not
arrive on my iPhone." Confirmed the fix should become the default for all sends.

**AI (Claude Code).** Identified that this was not a defect in the request payload — a plain
send was already valid and Home Assistant was returning `200` — but an iOS delivery-priority
question. An ordinary notification is an `active` one, which iOS may hold for a Focus mode or
the Notification Summary; a critical alert is exempt from both, so critical appeared to be the
only thing that worked. The tool could express only those two extremes.

Added `--interruption-level {passive,active,time-sensitive}` with a `--time-sensitive`
shorthand and an `HA_NOTIFY_INTERRUPTION_LEVEL` environment default, following the existing
flag → environment → built-in precedence. `--critical` continues to outrank it, so the two are
safe to combine. Argparse validates `choices` on the flag but not on a default sourced from
the environment, so a typo in `HA_NOTIFY_INTERRUPTION_LEVEL` is caught explicitly and exits
`2` rather than being sent to Home Assistant. Documented the phone-side settings that must
also be right (Time Sensitive enabled, app not set to Deliver Quietly, Focus per-app rules),
since the flag alone cannot force delivery.

A `400: Bad Request` seen while testing this change was environmental, not a regression: the
maintainer's configuration lives in `~/.config/ha-notify/env`, which only interactive shells
source, so a non-interactive invocation fell back to the built-in `mobile_app_iphone` default,
which does not exist on that instance. The existing `--list-targets` hint pointed at the cause
directly, as it was designed to. `HA_NOTIFY_INTERRUPTION_LEVEL=time-sensitive` was then added
to that file.

Not yet confirmed: that a time-sensitive notification actually clears whatever is currently
suppressing normal ones on the maintainer's phone. The send returns `0`, which means only that
Home Assistant accepted it — arrival on the device has not been reported back. The instance
also has two iPhone registrations (`mobile_app_alex_s_iphone` and
`mobile_app_alex_s_iphone_15`); a stale registration remains an untested alternative
explanation for the original symptom.

8 tests added (38 total), covering each interruption level, critical outranking a level, the
environment default and the flag overriding it, and the rejected environment typo.

## Approximate LOC at 0.2.0

| File | Lines | Author |
| --- | --- | --- |
| `src/ha_notify/cli.py` | 282 | AI, from a ~25-line human prototype |
| `tests/test_cli.py` | 308 | AI |
| `tests/conftest.py` | 12 | AI |
| `README.md` | 196 | AI |
| `src/ha_notify/__init__.py` | 6 | AI |

38 tests, all offline. Growth since 0.1.0 (+37 `cli.py`, +44 tests, +61 README, +39 AI.md)
is entirely AI-written.

## Review status

0.1.0: all AI-written code was executed and verified against a live Home Assistant
instance, and the packaged wheel was installed into a clean environment and re-tested.

0.2.0: the flag, environment default, precedence and rejected-typo paths were exercised
against the live instance, and a time-sensitive notification was accepted by Home Assistant
(exit `0`). Delivery to the maintainer's phone has not been confirmed back, so the fix is
verified as far as the API boundary and no further. Not published to PyPI — released by tag
and wheel only, installed directly on the maintainer's hosts.

Neither release has had a line-by-line human review.
