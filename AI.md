# AI Contributions

*About AI slop.* This code is the result of a set of conversations between the human author and Claude Code. Does that make it slop? Is instant ramen slop? Sure, and it has also kept a lot of people fed. But you don't have to take the analogy on faith — the rest of this file is a line-by-line accounting of who did what, including two defects in AI-written code that testing caught before they shipped. Read it and decide. Bon appétit, but mind the sodium content.

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
arrive on my iPhone." Confirmed the fix should become the default for all sends, and verified
the result on the device — the only step that could confirm it, since nothing visible from the
API side distinguishes a delivered notification from a suppressed one.

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

Confirmed on the device: a non-critical send from a maintainer host carrying
`interruption-level: time-sensitive` arrived with sound. This validates the diagnosis rather
than merely the code path — an `active` notification was being suppressed, and raising the
interruption level was sufficient to clear it without resorting to a critical alert. It also
rules out the competing explanation, a stale device registration: the instance has two iPhone
registrations (`mobile_app_alex_s_iphone` and `mobile_app_alex_s_iphone_15`), and the one in
use is demonstrably live.

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

## 0.3.0: `--target all`

Notable as the first change where the **human wrote the implementation and the AI reviewed
it** — the inverse of every prior entry.

**Human.** Designed and implemented the feature: a `--target all` that fans a single message
out to every notify service, the exclusion of aggregate services from that fan-out, a
`list_targets` reshaped to return the names rather than print them, and per-target error
handling. Requested a review rather than a rewrite.

**AI (Claude Code).** Reviewed the working tree and reported 13 findings, then applied them.
Four were defects that would have shipped:

- `EXIT_ERROR` was never defined, so the `--target all` listing-failure path raised
  `NameError` instead of returning an exit code.
- `--list-targets` returned early only on success. On failure it fell through into the
  message-handling path and went on to *send a notification*, so a bare `--list-targets`
  against an unreachable instance exited `2` complaining about a missing message.
- An `all` that expanded to zero targets sent nothing and returned `0`. For a tool whose
  entire job is to shout when a cron job fails, silently reporting success while notifying
  nobody is the worst available outcome; it is now `1`.
- A duplicated `elif r.status_code == 401` branch, the second unreachable.

The substantive design finding was that the exclusion list was applied to `--list-targets`
as well as to the `all` fan-out. That is the wrong place for it twice over: `--list-targets`
is the command you run to find out why an expected target is missing, so filtering it hides
the evidence — and the list contained `mobile_app_kiosk`, a fact about the maintainer's house
hard-coded into a published general-purpose package. The filter now applies only to `all`,
the built-in defaults cover only genuinely non-device services (`notify`,
`persistent_notification`, `send_message`), and site-specific exclusions move to
`HA_NOTIFY_ALL_EXCLUDE`.

`list_targets` was split into `fetch_targets` (returns names) and `list_targets` (prints, one
exit code) rather than changing the latter's contract in place — which restored two tests the
change had broken and kept the `out=` seam the tests use. Fan-out logic moved into
`expand_all`. Remaining fixes: `all` matched after `normalize_target` so `notify.all` works;
payload built once instead of per target (it was identical each pass, and re-resolved the
hostname every time); diagnostics moved from stdout to stderr to match the rest of the file;
result aggregation reduced to one variable; a `sent to N of M targets` summary added for
multi-target runs.

16 tests added (54 total), covering exclusion defaults and the environment variable, `all`
expansion, `notify.all`, partial failure continuing to the remaining targets while exiting
non-zero, the empty-expansion failure, dry-run fan-out, payload built once, and
`--list-targets` neither filtering nor falling through to a send.

Also fixed a pre-existing test-isolation defect, unrelated to this change and not caught
earlier because it only fails on a machine that has the variable set: `conftest.py` cleaned
`HA_TOKEN`, `HA_URL` and `HA_NOTIFY_TARGET` from the environment but not
`HA_NOTIFY_INTERRUPTION_LEVEL`, so `test_dry_run_uses_defaults` failed in the maintainer's
own shell.

## 0.3.0: public-repo preparation

**Human.** Decided to make the repository public and directed the check for prior art, the
README update, and the configuration scan.

**AI (Claude Code).** Scanned the working tree and the full git history for credentials and
site configuration. Nothing sensitive was found: no token-shaped strings in any commit, no
`.env` ever tracked (`.gitignore` has covered it and `dist/` since the first commit), and the
eleven tracked files are the only files that have ever existed in the history. What is
was disclosed was ordinary rather than sensitive: the maintainer's name and public commit
email, and the household's real device slugs.

At the maintainer's direction the personal identifiers were then removed anyway. The device
slugs throughout the documentation, and the machine name in the test suite, are now neutral
placeholders; the sample `--list-targets` output no longer reads as an inventory of the
household's devices. The apostrophe-slugification example survives intact — it is the failure
the tool was built to diagnose, so it needs a name with an apostrophe in it, just not a real
one. The only remaining occurrence of the maintainer's identity outside `LICENSE` and
`pyproject.toml` is the GitHub account in the repository URL, which is structural.

Surveyed prior art. `ha-notify` is free on PyPI; `hanotify` is taken but unrelated (a 2014
HockeyApp crash reporter). The one real neighbour is `homeassistant-cli` (`hass-cli`), the
general-purpose Home Assistant CLI. It can send a notification, but its `--arguments` are flat
`key=value` pairs, which does not express the nested `data.push.sound.critical` structure an
iOS critical alert needs, and as of 1.0.0 it requires Python 3.13+ — a poor fit for the older
hosts that run backup scripts. No packaged single-purpose tool for this niche appears to
exist; the alternative in practice is a hand-rolled `curl` one-liner. A README "Alternatives"
section now says so plainly, including a pointer to ntfy for people not tied to Home
Assistant.

Also updated the install instructions from `git+ssh://` and "private repository" to
`git+https://`, and added `[project.urls]` to `pyproject.toml`.

## 0.3.0: set-but-empty environment variables

**Human.** Approved the fix after it was reported.

**AI (Claude Code).** Found while smoke-testing the freshly published package from its public
URL — not by reading the code. `os.environ.get("HA_URL", DEFAULT_URL)` returns `""` for a
variable that is set but empty, so the built-in default was never reached:

    $ HA_URL= HA_NOTIFY_TARGET= ha-notify "x" -n
    POST /api/services/notify/

This matters for the deployment shape the tool was built for. The maintainer's configuration
is a sourced env file, and a blanked or commented-out `HA_NOTIFY_TARGET=` line in one would
silently produce a POST to `notify/` with no target, which Home Assistant answers with the
same bare `400: Bad Request` that motivated `--list-targets` in the first place.

Added an `env_default()` helper treating set-but-empty as unset, and routed all four reads
(`HA_URL`, `HA_NOTIFY_TARGET`, `HA_NOTIFY_INTERRUPTION_LEVEL`, `HA_TOKEN`) through it. The
`HA_TOKEN` path already behaved correctly via a separate `if not token` check; it goes through
the helper for consistency. 6 tests added (60 total).

Notable as a defect that four rounds of review, 54 passing tests and a live-instance check all
missed, and that surfaced immediately on actually running the shipped artifact with an
adversarial environment.

## Approximate LOC at 0.3.0

| File | Lines | Author |
| --- | --- | --- |
| `src/ha_notify/cli.py` | 366 | Mixed: human feature, AI review and rework |
| `tests/test_cli.py` | 553 | AI |
| `tests/conftest.py` | 18 | AI |
| `README.md` | 266 | AI |
| `src/ha_notify/__init__.py` | 6 | AI |

60 tests, all offline. Growth since 0.2.0: +84 `cli.py`, +245 tests, +70 README. The
`--target all` feature is the first human-written code in the package since the prototype;
the AI contribution to it is review, correction and tests rather than authorship.

## Review status

0.1.0: all AI-written code was executed and verified against a live Home Assistant
instance, and the packaged wheel was installed into a clean environment and re-tested.

0.2.0: the flag, environment default, precedence and rejected-typo paths were exercised
against the live instance, and end-to-end delivery was confirmed by the maintainer — a
time-sensitive notification sent from a maintainer host arrived on the phone with sound. Not
published to PyPI — released by tag and wheel only, installed directly on the maintainer's
hosts.

0.3.0: reviewed and reworked by AI, with an offline test suite. The AI verified the
read-only half against the live instance — `--list-targets` returns the full service list and
`all` expands it to the device targets, dropping the three aggregates. The maintainer
confirmed the sending half: a real multi-device fan-out reaches the phones. As with the 0.2.0
interruption-level work, that is the step only the maintainer's devices can perform.

The set-but-empty environment fix was verified by running the published artifact directly:
the reported repro now resolves to the built-in defaults, a blank `HA_TOKEN` still exits `2`,
and real values still win. First release published from a public repository; the history was
rewritten before publication to remove the maintainer's personal identifiers, and a fresh
clone from GitHub was scanned to confirm none remain in any commit, message or tag.

No release has had a line-by-line human review.

## The note at the top

**Human.** Wrote the original preface — the argument, the soup comparison and the sodium
line are the maintainer's, as was the decision that the file should answer the slop question
at all rather than ignore it.

**AI (Claude Code).** Reviewed and revised it. Cut a dated pop-culture reference that would
have misfired on the readers the argument is aimed at, and rewrote the second half to point
at this file's accounting instead of resting on the analogy. The maintainer chose the final
wording and made it standing practice for all AI.md files.
