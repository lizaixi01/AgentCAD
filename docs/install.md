# Install AgentCAD

AgentCAD lets an AI agent (Claude Code, Codex, Claude Desktop or Cursor) draw and edit CAD files for you. This page
gets it running in about five minutes. You do not need to know Python, and you do not need to download the source
code.

## Easiest: double-click the installer

No terminal and nothing to type. A setup page opens in your browser, with big buttons and a progress bar, in
English or Chinese.

1. Download the installer for your computer:
   - **Windows:** [AgentCAD-Setup.cmd](https://github.com/lizaixi01/AgentCAD/releases/latest/download/AgentCAD-Setup.cmd)
   - **macOS / Linux:** [AgentCAD-Setup-mac.zip](https://github.com/lizaixi01/AgentCAD/releases/latest/download/AgentCAD-Setup-mac.zip)
2. Double-click it. On Windows a small window with a progress bar downloads what is needed (about a minute the
   first time), then the setup page opens in your browser. On macOS, double-click the .zip first: it unpacks to `AgentCAD-Setup.command`, still runnable
   (a plain download of that file would lose the permission to run).
   - Windows may say "Windows protected your PC". Click **More info**, then **Run anyway**.
   - macOS may say it cannot check the developer. Right-click the file, choose **Open**, then **Open** again.
3. On the page: tap **Start**, keep the apps it ticked (the ones found on your computer) and tap **Install now**.
   Each step gets a green tick as it finishes.
4. The last page says what is left (restart your app) and gives example sentences to copy to your assistant.
   Tap **Finish**; the installer window closes by itself.
5. From then on, double-click the **AgentCAD** icon setup put on your desktop: it opens your drawings in the live
   viewer (see [viewer.md](viewer.md)). With no drawing yet, it shows sentences to copy to your assistant.

Already installed, or something stopped working? Run the installer again and tap **Already installed? Check it**.
Every part gets a green tick or a sentence saying what to do, and **Fix it for me** reconnects the apps that need
it. Without FreeCAD, the page has a button to its free download; 2D drawings work without it.

The first run downloads uv and Python (about a minute). On macOS and Linux the installer shows its progress as text
in a Terminal window instead of a progress window. It does the same as `agentcad setup` below, so running it
again is safe. Under the hood: the installer runs `uvx --from <GitHub zip> agentcad setup --gui`, which serves the page
on `127.0.0.1` only, behind a random token in its link.

## With a terminal

There are three steps:

1. Install **uv**, a small tool that downloads and runs Python programs.
2. Run **one command** that connects AgentCAD to your apps.
3. Restart your app and try a first prompt.

### 1. Install uv

Open a terminal:

- **Windows:** press the Windows key, type `PowerShell`, press Enter.
- **macOS:** press Cmd+Space, type `Terminal`, press Enter.
- **Linux:** open your terminal app.

Paste this line and press Enter.

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

macOS and Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Close the terminal and open a new one** so it finds `uv`. If you already have uv, skip this step. uv also installs
Python for you if you don't have it.

### 2. Connect AgentCAD to your apps

Run this in the new terminal (the same line on Windows, macOS and Linux):

```bash
uvx --from git+https://github.com/lizaixi01/AgentCAD agentcad setup
```

The first run takes up to a minute while it downloads. Then it:

- asks which apps to connect (Claude Code, Codex, Claude Desktop, Cursor) and suggests the ones it found on your
  computer. Press Enter to accept;
- adds AgentCAD to each app's settings, keeping the other tools you already set up there;
- creates the folder where your drawings will be saved: `AgentCAD` in your home folder
  (`C:\Users\<you>\AgentCAD` on Windows, `/Users/<you>/AgentCAD` on macOS, `/home/<you>/AgentCAD` on Linux);
- looks for FreeCAD and AutoCAD (see below);
- prints what to do next.

Running it again is safe: it only changes what is out of date. To see what it would change without changing
anything, add `--dry-run`. To skip the question, name the apps: `--client claude-code --client cursor`, or
`--client all`.

How it starts AgentCAD: your app runs `uvx --from git+https://github.com/lizaixi01/AgentCAD agentcad-mcp` whenever it
needs it. uv keeps a copy, so this takes a couple of seconds, and it picks up new versions of AgentCAD by itself.

### 3. Try it

Restart the app you connected:

- **Claude Code:** start a new session. Type `/mcp` to see `agentcad` in the list.
- **Codex:** start a new session. Type `/mcp` to see `agentcad`.
- **Claude Desktop:** quit it completely (on Windows also from the icon next to the clock; on macOS with Cmd+Q) and
  open it again.
- **Cursor:** restart it, then check that `agentcad` is switched on under Settings > MCP.

Then ask:

> Draw a 200 x 100 mounting plate with R8 corners and four 12 mm holes 15 mm from the edges. Save it as plate.dxf,
> check it, and export plate.svg.

Open your `AgentCAD` folder: `plate.svg` opens in any web browser, and `plate.dxf` in any CAD program. Then try:

> Make the plate 240 wide and keep the holes 15 mm from the edges. Tell me what changed.

> Undo that.

## Check that everything works

```bash
uvx --from git+https://github.com/lizaixi01/AgentCAD agentcad doctor
```

It checks Python, AgentCAD, Pillow, FreeCAD, AutoCAD, your drawings folder and each app's settings. Every line says
`ok`, `missing` or `skip` (app not installed), and every problem comes with a one-line fix.

## Save drawings in another folder

Pass the folder to setup:

```bash
uvx --from git+https://github.com/lizaixi01/AgentCAD agentcad setup --root "D:\Drawings"
```

The agent can only read and write files inside this folder. Without `--root`, AgentCAD uses the `AGENTCAD_ROOT`
environment variable if you set one, and otherwise `AgentCAD` in your home folder. It never uses whatever folder the
app happened to start in.

## 3D parts: FreeCAD

2D drawings (DXF) work right away. 3D parts (`.FCStd`, STEP, STL) need **FreeCAD 1.1**: download it from
[freecad.org](https://www.freecad.org/downloads.php) and install it. Setup finds FreeCAD in its usual install folder.
If you put it somewhere else, or doctor says it is missing, tell setup where it is:

```bash
uvx --from git+https://github.com/lizaixi01/AgentCAD agentcad setup --freecad "D:\Tools\FreeCAD 1.1"
```

Give the FreeCAD folder (the one that holds `bin`), its `bin` folder, or the `freecadcmd` program.

## DWG files: AutoCAD (optional, Windows)

DXF needs nothing else. To open or save `.dwg` files, AgentCAD uses AutoCAD if it is installed on the same Windows
computer. Doctor shows whether it found it.

## Other ways to install

**Only Claude Code, one line.** If you have Claude Code's `claude` command:

```bash
claude mcp add agentcad --scope user -- uvx --from git+https://github.com/lizaixi01/AgentCAD agentcad-mcp
```

Your drawings then go to `AgentCAD` in your home folder. To pick another folder, add
`-e AGENTCAD_ROOT=D:/Drawings` after `--scope user`.

**A permanent install instead of uvx.** This puts an `agentcad` command on your PATH, and the apps run that copy:

```bash
uv tool install git+https://github.com/lizaixi01/AgentCAD
agentcad setup
```

Update it later with `uv tool upgrade agentcad-runtime`. With pipx it is
`pipx install git+https://github.com/lizaixi01/AgentCAD`, then `agentcad setup`. If you have pipx but not uv,
`pipx run --spec git+https://github.com/lizaixi01/AgentCAD agentcad setup` also works; the apps then start AgentCAD
with `pipx run`.

**From a clone (for development).** See "Get started" in the [README](../README.md). In a clone, `agentcad setup`
connects the apps to the clone's own Python, so they run your local changes.

AgentCAD's package name is `agentcad-runtime`. The `agentcad` package on PyPI is a different project: do not
`pip install agentcad`.

## Where setup writes

| App | Settings file |
|---|---|
| Claude Code | `claude mcp add --scope user` when the `claude` command exists; otherwise `.mcp.json` in your drawings folder (open Claude Code in that folder and approve `agentcad` when asked) |
| Codex | `~/.codex/config.toml` (`[mcp_servers.agentcad]`) |
| Claude Desktop | Windows `%APPDATA%\Claude\claude_desktop_config.json`, macOS `~/Library/Application Support/Claude/claude_desktop_config.json`, Linux `~/.config/Claude/claude_desktop_config.json` |
| Cursor | `~/.cursor/mcp.json` |

To remove AgentCAD from an app, delete its `agentcad` entry from that file (`claude mcp remove agentcad --scope user`
for Claude Code). Your drawings stay in their folder.

## Troubleshooting

- **`uvx` is not recognized / command not found:** open a new terminal after installing uv. On Windows you can also
  sign out and back in.
- **The app does not list agentcad:** restart the app completely, then run `agentcad doctor` (the `uvx ...` line
  above) and follow its fixes.
- **The first start times out:** the first start downloads AgentCAD. Run the setup command once more (that fills
  uv's cache), then restart the app.
- **"Path outside workspace":** the agent tried to use a file outside your drawings folder. Move the file into the
  folder, or run setup with `--root` pointing at the folder that holds it.
