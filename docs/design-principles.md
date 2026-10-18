# Design principles

## Zero-knowledge / zero-memory

A person who only vaguely remembers the name **WIMS** must be able to get going.

- **Recognition over recall.** Show the next choice. Do not ask anyone to remember a flag, a path, or a port.
- **Zero-config.** The first start needs nothing typed. Files, radios, and an already-running WIMS are detected.
- **Auto-detect.** Find WSJT-X logs, an N1MM log, Python, and a console that is already up.
- **Progressive disclosure.** A Goal menu, then one menu that depends on that goal. Extra choices stay under Advanced.
- **Plain next step.** When something fails, say what to do next in ordinary words. Do not stop at a code or a stack trace.

Operator instructions (the top of the README, Setup page text, launcher messages, and `scripts/README.md`) do not ask for environment variables, `python -m`, or command-line flags. Those belong in a section titled **Developer**.

## Checklist

Verify this before calling a launcher change done.

1. **Findable by name.** A Desktop icon and a Start-menu (or app-menu) entry are named **WIMS**. `scripts/README.md` names the file that creates them.
2. **One click starts it and opens the browser.** Double-click **WIMS**. The window opens. Starting Operate or the site server opens `http://localhost:8787/`. A second double-click brings that WIMS window to the front. It does not open another window or the site console. If the window does not answer, WIMS says what to do next.
3. **Setup auto-detects.** The Setup page shows the Goal menu and the log lines WIMS found. No path is typed for a normal start.
4. **No typed commands.** The steps above do not ask the operator to set a variable, pass a flag, or run `python -m`.
5. **Plain-language errors.** Missing Python, a busy port, and “already open” each say what to do next.

## Clean builds

The GitHub check on Python 3.10, 3.12, and 3.14 is green before a change is merged. A green run's log does not contain `FAIL` or `ERROR` lines from a path that was supposed to succeed, or from a refusal the test expected. A failure email is fixed at the cause — the bug, the test, or the wording — so the mail stops.
