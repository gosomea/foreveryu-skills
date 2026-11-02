---
name: dsh-plugin-isolated-test
description: Choose test layers and isolation for a DeepSeek Harness (DSH) plugin, then validate installation, composition, host behavior, and optional client UI without disturbing a daily instance. Use for DSH plugin integration or release testing; ordinary standalone unit tests need no DSH host.
---

# DSH Plugin Isolated Test

Test the behavior the plugin actually provides. Use the least isolation that protects the daily DSH process, sessions, profile, and served artifacts. Record what each layer proves and what remains untested.

## Choose layers by the question

| # | Layer | Host? | Minimum evidence |
| --- | --- | --- | --- |
| 1 | Standalone logic | No | Focused tests cover the relevant behavior. Tests called *pure* must not depend on ambient environment, files, or network. Controlled tests with temporary files or injected dependencies are still hostless integration tests. |
| 2 | Build and package | No | Project checks and build pass. Inspect the packed artifact: every declared runtime, client, type, and bundle-patch entry resolves; no secrets or test state are included. Do not require a type entry or `cordis.patch.yml` when the package declares neither. |
| 3 | External service, if used | No DSH host | A synthetic request exercises the service contract and failure policy without exposing credentials. It may still need network access or a mock server. |
| 4 | Profile composition | No running host | Install through the intended path; inspect the profile manifest and `--dump-config` for the expected dependency, selected bundle when applicable, and enabled plugin row. |
| 5 | Real host | Yes | The plugin loads, reaches the expected state, receives its intended event or request, and produces the expected observable result. Choose Web, TUI, or another suitable persistent host; only a network listener needs a port. |
| 6 | Browser UI, if contributed | Web host | A normal user action opens the page; rendered state matches an independent data source. Use a negative control when testing that data comes from that source. |

`--dump-config` composes patch layers without mounting plugins or evaluating `!!js`. It proves configuration presence, **not** successful module loading, service injection, or runtime behavior. Verify those in the real-host layer. A hand-made symlink plus overlay can diagnose resolution, but does not prove the supported `dsh plugin add link:/absolute/path` installation path.

For browser data checks, compare against storage or another independent source outside the browser. If the UI intentionally caches data, a blocked fetch alone does not imply zero rows; use a fresh context or clear the cache and assert the documented empty/error state.

## Choose isolation by what changes

| Change under test | Isolation needed |
| --- | --- |
| Standalone logic, package inspection, or config composition | No host or port. Use a dedicated test home for profile installation/composition. |
| Plugin-only host code, no rebuild of artifacts served by the daily host | Dedicated `DSH_HOME` and profile; choose a separate port **if** the test host listens. Install the plugin with an absolute `link:`. |
| DSH core, client bundle, or any artifact served by the daily host is rebuilt | Separate source checkout, dedicated `DSH_HOME`, profile links repointed into that checkout, and a separate port if listening. |
| Packed or published package behavior | Clean test home; install the packed/published artifact rather than a source `link:`. |

`DSH_HOME`, source/profile `link:` targets, and listener ports isolate different things. A different port cannot protect a daily Web instance from rebuilding files it serves: DSH polls those artifacts and may reload its page. For source rebuilds read [the source-instance how-to](../../knowledge/Agent%E5%B7%A5%E7%A8%8B/%E6%A1%86%E6%9E%B6%E6%BA%90%E7%A0%81/DSH/dsh-isolated-source-instance.md). For concrete host commands and the optional reviewer example read [the runbook](references/runbook.md) only when those steps apply.

Reuse one isolated source checkout and test home across compatible verification gates. Do not create a new Git worktree for each gate unless parallel edits genuinely require separate branches. After integration, remove clean temporary worktrees with `git worktree remove`; check for uncommitted files, unique commits, active processes, and profile links first. Retain the branch or other recovery record until its work is confirmed in the main checkout.

## Find an existing deployment before creating one

Use the bundled [environment registry](references/environment-registry.md) before starting or handing off a host test. Its Python script stores project, purpose, source/plugin paths, test home, profile, Host identity, and case workspace/Session references in a persistent local SQLite database outside TMP and Git. A deployment can serve multiple case workspaces and Sessions; a new case does not by itself require a new Host, home, or source checkout.

Run `scripts/environments.py list --project <canonical-plugin-project>` and `check <id>`, then inspect the preferred matching deployment and its handoff notes. Reuse it when the build/profile and active work are compatible. Register existing deployments mentioned by the user before inventing a replacement. If another deployment is necessary, record the conflict or parallel-test reason with `register --reason`. Register a new deployment as soon as its paths are allocated, then update its PID/URL after launch and bind each case after Session creation. This lets concurrent conversations discover the allocation before the Host is ready.

The registry is an inventory, not a deployment controller or a lock on the Host. Its process checks do not prove model health or an idle Session. Before changing served artifacts, restarting, or cleaning up, check current activity and retained user-validation work. Keep user-validation deployments available; update the handoff note and record lifecycle state rather than silently replacing them. The script never stops processes or deletes workspaces.

## Choose the test workspace automatically

After choosing the deployment, look up its case workspaces. Reuse a compatible workspace for the same case; for a new case needing fresh fixtures, create a clean workspace under the operating system's temporary directory (`TMPDIR` or the platform temp-directory API). Keep it separate from the DSH source checkout, plugin source, and test home. Add only the fixtures required by this case.

Bind that absolute path to the test Session through the target version's supported CLI, SDK, or Host API. Verify the Session's recorded working directory before sending a model task. Creating the directory or starting the Host there alone does not prove the Session uses it. Follow the [workspace setup procedure](references/runbook.md#prepare-the-test-workspace).

Do not make clicking through the Web folder picker or asking the user to choose a workspace a routine prerequisite. Use an existing directory only when the test actually depends on that project or existing files; resolve the required directory from the task context and prefer a disposable copy when the test writes to it. Exercise the folder picker when directory selection itself is under test, or as a documented fallback if the target version has no supported direct binding interface. Prepare the workspace and Session before handing the isolated environment to the user for validation.

## Workflow

1. **Baseline and registry before changes.** Query the registry for the project and check existing deployments before allocating another. Identify the actual daily process, its checkout, `DSH_HOME`, listener if any, session-store state, relevant versions, and Git status. Do not assume port `3080` or `~/.dsh` belongs to it.
2. **Test without a host first.** Run relevant focused tests, build checks, package inspection, and external-service contract tests. Skip layers the plugin does not implement.
3. **Reuse or install in a dedicated test home.** Reuse a compatible registered deployment. If a new deployment is required, record why, select a shipped profile appropriate for the test, then use the supported plugin installation path. When rebuilding DSH artifacts, first isolate the source checkout and repoint checkout-local links.
4. **Inspect composition and model parity.** Verify dependency and bundle selection where applicable, plus the final plugin row and config. For real-model tests, reuse the daily Host's effective provider/model route and relevant model settings in the isolated Host's profile or settings; do not treat a missing credential in the test home as an acceptable substitute for this test. Treat runtime loading and injections as pending until the host test. Read the [runbook's model-configuration procedure](references/runbook.md#reuse-the-daily-model-configuration) when a real model call is needed.
5. **Exercise the smallest suitable host behavior.** Create and bind the temporary workspace using the procedure above; use an existing project only when required by the case. Capture an event, response, state change, or persisted record specific to the plugin. For model-dependent behavior, prove that both the main request and any reviewer request reached the intended route. For asynchronous post-turn work, use a persistent host or an explicit exit/job barrier.
6. **Exercise optional paths separately.** For dispatching plugins, check the child lineage and settled result. For client plugins, check an actionable browser interaction and data fidelity. Test production thresholds separately from any clearly labelled test overlay.
7. **Close and compare.** Stop only the identified test process, remove or disable test-only overlays, and compare the daily process and session store with the baseline. Reuse the test home for the same plugin where appropriate; keep it when needed to reproduce a finding or when the user requests retention. Remove clean, superseded worktrees after their changes are integrated.

## Reuse the daily model route

For real-model plugin tests, the isolated Host should select the **same effective provider/model route as the daily Web Host** — typically the host's `agent-default-model` (provider + model), which is usually the first model under the daily profile's configured LLM provider. Re-read the live daily profile before each run; the route is a current value, not a timeless default.

Record at least: `agent-default-model.provider`, `agent-default-model.model`, the provider's API adapter and base URL, and the **credential environment-variable reference** (never the key itself).

Copy the route and credential reference into the isolated home without exposing the key. Compare both composed profiles, check the running Hosts' new-session selection, and complete a real isolated model request before plugin tasks. If the host offers multiple proxy routes for the same vendor, make sure you copy the one the daily Host actually uses. Follow the [runbook](references/runbook.md#reuse-the-daily-model-configuration) for the procedure and runtime evidence.

## DSH-specific pitfalls

- Use a Node version supported by the target checkout (`^22.19` or `>=24` in the examined checkout). Node 23 can exit `0` without invoking a source CLI that relies on `import.meta.main`.
- Prefer the target checkout's CLI over an older global `dsh`. Keep launcher flags such as `--patch` before application flags such as Web `--port`.
- A profile row patch replaces that row's entire `config` object. A test overlay must restate all owned fields it needs.
- Keep `DSH_HOME`, Sessions, and the test process isolated while reusing the daily model configuration for real-model tests. Supply the corresponding credential through the isolated launch environment or an isolated credential store; do not point the test home at the daily home or link to its writable credentials file.
- Host processes capture environment variables at start. Restart the isolated host after changing a required key. Check presence without printing its value; never put keys in patches or logs.
- For the DSH Web app described in the runbook, **do not background it with stdin from `/dev/null`**: its stdin-EOF handler can exit immediately. Prefer a foreground host; if backgrounding is needed, follow the runbook's open-stdin recipe and redirect output to a regular file.
- DSH Web prints a process-specific `?token=` startup URL even with `--no-open`. Open that full URL once in the intended browser to receive its authentication cookie; a bare `http://127.0.0.1:<port>/` works only in a browser profile already authenticated for that authority. Keep the startup line available privately, never replace it with a bare URL when handing off a fresh browser, and do not commit or quote its token. If the line was discarded, first reuse a working authenticated tab; otherwise recover access by a controlled isolated-host restart after accounting for active jobs. Follow [the Web authentication procedure](references/runbook.md#web-browser-authentication).
- One-shot headless may exit after the root agent becomes idle while untracked post-turn work is still pending. A missing sidecar result in that case is a lifecycle finding, not proof that event routing failed.
- When a plugin extracts the human request from persisted `user/message` events, inspect `source.kind`; DSH also persists injected runtime and skill-catalog messages. For external review, bound and redact evidence and omit tool arguments/results unless the plugin's contract explicitly requires them.

## Report results precisely

For each applicable layer, give the command or action, independent observation, result, and limitation. Mark absent capabilities **not applicable**; mark applicable but unrun checks **untested**. Report isolation separately: identify the daily process/home checked, the test home, and whether test sessions appeared only in the test home. A config dump alone must never be reported as a loaded plugin, and a new session count alone must never be reported as successful dispatch.

Do not stop a process by port number alone. Resolve its PID, command, cwd, supervisor, and `DSH_HOME` first. Preserve unrelated profile and Git changes.
