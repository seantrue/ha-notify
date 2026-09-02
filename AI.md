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

## Approximate LOC at 0.1.0

| File | Lines | Author |
| --- | --- | --- |
| `src/ha_notify/cli.py` | 245 | AI, from a ~25-line human prototype |
| `tests/test_cli.py` | 264 | AI |
| `tests/conftest.py` | 12 | AI |
| `README.md` | 135 | AI |
| `src/ha_notify/__init__.py` | 6 | AI |

30 tests, all offline.

## Review status

All AI-written code in this release was executed and verified against a live Home Assistant
instance, and the packaged wheel was installed into a clean environment and re-tested. The
code has not yet had a line-by-line human review.
