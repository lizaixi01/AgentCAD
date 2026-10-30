# Reproducible verification and operational boundaries

Install the repository's supported dependency graph with `uv sync --locked --extra dev`.
`uv.lock` includes Python/platform markers and archive hashes, including optional
extras; the ordinary dev lane does not install CadQuery. Consumer package version
ranges remain compatible. Upgrade the lock deliberately, then rerun the checks.

```bash
uv lock --check
uv run --locked python scripts/gen_docs.py --check
uv run --locked python -m pytest -p no:cacheprovider --basetemp=/your/own/temporary/directory
```

The GitHub workflow runs Linux 3.10/3.12, Windows 3.11 and macOS 3.12. Its Linux
3.12 lane also runs the original pinned v8 evaluator through the real MCP adapter.
JUnit and benchmark artifacts are retained for 30 days. A workflow definition is
not evidence of a passing run: cite the completed run and commit. Missing optional
AutoCAD, FreeCAD, CadQuery or image-render dependencies are recorded as skips.
Local AutoCAD checks must remain serial because its registry profile is shared.

Generated operation documentation is checked against the registry; its test matrix
shows textual calls, not coverage quality. Historical benchmark reports and their
source hashes stay unchanged. New measurements belong in a new directory.

## Backend contract

| Capability | Native DXF | AutoCAD | FreeCAD |
|---|---|---|---|
| 2D drawing/editing, domain generators, validation | Main implementation | Saved DXF interoperability | Not used |
| DWG import/export and AUDIT | Requires optional backend | accoreconsole | Not used |
| Live GUI open/reload/pull/zoom | Revision/conflict checks | Optional Windows COM | Not used |
| Parametric 3D features and solid measurements | Not supported | Not used | Isolated native process |
| DXF/PDF/SVG/CSV/XLSX/JSON delivery | Main implementation | Not required | Not used |

This is a complementary backend design, not a claim that every 2D tool has an
independent COM implementation. Linux/macOS path discovery alone does not prove
native FreeCAD or AutoCAD behavior on those platforms.

## HTTP and long-running writers

`agentcad serve` defaults to loopback. A non-loopback bind is refused unless
`AGENTCAD_HTTP_TOKEN` supplies at least 32 non-whitespace ASCII characters. Every
request then needs `Authorization: Bearer <token>`, including the tool catalog.
Provide the token through a private environment; it is never printed in the URL
or log. A trusted TLS proxy is required for transport confidentiality on untrusted
networks; the built-in server itself is HTTP. Loopback also validates Host.
Browser Origin requests are refused, POST requires JSON, body lengths are bounded,
and runtime calls are serialized. This API does not expose a browser/CORS contract.

Writers use nonblocking OS locks held until the operation finishes or the process
exits. An old timestamp cannot evict a live writer. The persistent `write.lock`
file is normal; deleting it while writers are running is unsafe on POSIX. A legacy
`lock` marker is conservatively refused regardless of age and should be removed
only after confirming its old writer has exited. Do not mix old and new runtime
versions in one active workspace. Foreign editors that ignore the lock still need
the revision/hash conflict checks; this is not an OS-wide lock on the DXF file.

Script and raw AutoCAD-command execution remain disabled by default. Opting into
scripts grants trusted agent code the user's privileges; AST filtering and child
process isolation are not a security sandbox for hostile Python.
