# F95Checker — Developer Reference

## What This Is
Python 3.11 desktop app for tracking adult games on F95zone.
Stack: Dear ImGui (pyimgui) UI · SQLite via aiosqlite · aiohttp async HTTP · GLFW/OpenGL

## Launch
```powershell
# Non-blocking (preferred during testing — run from repo root):
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "main.py"

# Or double-click start.bat at repo root
# Debug mode (tracebacks visible):
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "main-debug.py"
```

## Key Files
| File | Purpose |
|------|---------|
| `main.py` | Entry point → patches → db → api → MainGUI → gui.main_loop() |
| `common/structs.py` | All dataclasses: Game, Settings, Label, Tab, SearchResult, etc. |
| `common/meta.py` | Version string, paths, frozen/debug flags |
| `modules/globals.py` | Runtime state hub: `games`, `settings`, `popup_stack`, `cookies` |
| `modules/db.py` | SQLite schema, migrations, read/write |
| `modules/api.py` | F95zone HTTP, search, login, refresh (~1100 lines) |
| `modules/gui.py` | ImGui draw loop, all popups, sidebar, game list/grid/kanban (~10k lines) |
| `modules/callbacks.py` | User-action handlers: add game, launch, scan folder, import |
| `modules/utils.py` | `normalize_version()`, `push_popup()`, file helpers |
| `external/async_thread.py` | Background asyncio loop; `run(coro)` → Future |
| `start.bat` | Double-clickable launcher (repo root) |
| `db.bat` | Test DB tool: `db.bat clear-games`, `db.bat list`, etc. (repo root) |

## Database
- **Windows path:** `%APPDATA%\f95checker\db.sqlite3`
- App must be **closed** before running direct SQLite commands
- Key tables: `games`, `settings` (single row), `cookies`, `timeline_events`, `labels`, `tabs`

### Common DB operations (while app is closed)
```powershell
# Clear games for testing:
echo y | .\db.bat clear-games

# Quick game list:
.\db.bat list

# Arbitrary SQL:
.\db.bat sql "SELECT id, name, installed FROM games LIMIT 10"
```

## Core Async Pattern
**Never call blocking I/O on the GUI thread.** All async work goes through the background event loop:

```python
from external import async_thread

# Fire-and-forget from GUI/sync code:
async_thread.run(some_coroutine(args))

# From within an async context, offload blocking work to thread pool:
loop = asyncio.get_running_loop()
result = await loop.run_in_executor(None, blocking_function)
```

## ImGui Patterns

### State in popups (retained-mode — no widget stores state)
```python
state = type("_", (), {"value": initial})()  # mutable namespace
def popup_content():
    changed, state.value = imgui.input_text("##id", state.value)
```
Or use a plain dict (as the scan-folder feature does with `result['detected_name']` etc.)

### Popup system
```python
utils.push_popup(
    utils.popup,
    "Window Title",
    popup_content_callable,        # called each frame
    buttons={"OK": callback, "Cancel": None},  # None = just close
    closable=True,
    outside=False,                 # don't close on click-outside
)
```
- `buttons` callbacks are called then the popup closes automatically
- `popup_content()` returning `True` also closes it
- `utils.push_popup(filepicker.FilePicker(...).tick)` — push a file picker

### Disabled widgets
```python
imgui.push_disabled()
# ... greyed-out widgets ...
imgui.pop_disabled()
```

### Scaling
Always `self.scaled(n)` for pixel values — never raw ints.

### Icons
```python
from modules import icons
icons.folder_open_outline, icons.cancel, icons.magnify, icons.download, icons.play
# Link-type icons used in download popup:
icons.link           # chain link — XPath/direct URLs
icons.domino_mask    # mask — F95zone masked links
icons.open_in_app    # open-in-app — plain F95zone links
```

### Bold font
```python
imgui.push_font(imgui.fonts.bold)
imgui.text("Bold heading")
imgui.pop_font()
```

## Game Model Critical Rules

### Version comparison — always normalize
```python
# CORRECT:
game.updated = utils.normalize_version(installed) != utils.normalize_version(game.version)

# WRONG — misses "0.5" vs "v0.5 Public":
game.updated = installed != game.version
```
`normalize_version` strips leading `v`/`V` and trailing `Public`, `EA`, `Fix2`, `Hotfix`, `Patch`, `Build`, `Demo`, `Preview`, `Final`, `Release`, `Beta`, `Alpha`.

### Setting installed version
```python
game.add_timeline_event(TimelineEventType.GameInstalled, version_string)
game.installed = version_string
game.updated = utils.normalize_version(version_string) != utils.normalize_version(game.version)
```

### `game.updated` tri-state
- `True` → shows update badge (installed < latest)
- `False` → user dismissed or up-to-date
- `None` → not installed or not meaningful

### Executables
- Stored as `list[str]` in `game.executables`
- Paths can be absolute or relative to `globals.settings.default_exe_dir[globals.os]`
- After setting `game.executables`, call `game.validate_executables()` — it relativizes against `default_exe_dir` and saves to DB

## Folder Scanner (callbacks.py)

### Rules
- **Already-imported detection**: compare subfolder path against `game.executables` paths, not game names
- **Version detection**: use `VERSION_PATTERNS` regexes already in `callbacks.py`

### Name parsing pipeline
1. Strip separators (`-`, `_`) → spaces
2. CamelCase split pass 1: `([a-z\d])([A-Z])` → insert space
3. CamelCase split pass 2: `([A-Z]+)([A-Z][a-z])` → insert space
4. `_split_trailing_stop_words()` — peels stop words from token ends, iterates until stable

### Stop word rules
Stop words used: `from`, `into`, `with`, `and`, `the`, `but`, `for`, `nor`, `of`, `an`, `in`, `on`
- **Not included** (too many false positives): `a`, `or`, `at`, `to`, `by`, `as`
- `in` and `on` require ≥5 chars before them (avoids `Begin`→`Beg in`, `Martin`→`Mart in`)
- `an` requires ≥4 chars before it

### Async exe scan pattern
Exe scanning (`scan_exes_for_result`) uses `run_in_executor` — walking directory trees is blocking.
The GUI polls `result['found_exes'] is None` each frame to trigger the scan, then renders results as they arrive. Scan state: `None` = not started, `[]` = started/done (may be empty list).

## Search
```python
# Sanitize first (removes Redis stop words that break the search index):
sanitized = api.latest_updates_search_sanitize_query(query)

results = await api.latest_updates_search(
    category="games",
    search="search",   # or "creator"
    query=sanitized,
    sort="likes",
    count=15,
)
# Returns list[SearchResult] with .id, .title, .creator, .url
```

## Download Links Button (modules/gui.py)

`draw_game_download_links_button(game, label="")` on `MainGUI` renders a button that opens an ImGui popup listing all available mirrors from `game.downloads`, each opening in the integrated browser.

### `game.downloads` structure
`tuple[tuple[str, list[tuple[str, str]]]]` — each entry is `(name, mirrors)`:
- **Non-empty mirrors** → platform group: `("Win/Linux", [("PIXELDRAIN", "https://..."), ...])`
- **Empty mirrors** → named section header: `("Update Patch 0.02→0.03", [])`
- "Regular Downloads" is synthesised automatically if the list starts with platform entries

### Mirror link dispatch (same logic as Downloads tab)
```python
if link.startswith("//"):                          # icons.link
    callbacks.redirect_xpath_link(game.url, link)
elif link.startswith(f"{api.f95_host}/masked/"):   # icons.domino_mask
    callbacks.redirect_masked_link(link)
else:                                              # icons.open_in_app
    callbacks.open_webpage(link)
```

### Placement
- Updated games sidebar (between Copy Link and More Info)
- More Info expanded view (between Copy Link and ID)
- Grid/kanban cell — **outside** `if action_items:` block, before cluster data
- List view — `download_links` column in the `Columns` class; case in `draw_games_list` match/case

### Hitbox click-through fix
When a button inside a cell opens a floating popup, the overlapping cell hitbox also reports as clicked, setting `game_hitbox_click = True`. When the mouse is released over the popup (which floats above a different game), that game's info popup spuriously opens. Fix: set `self._suppress_hitbox_click = True` when opening the Download popup; `handle_game_hitbox_events` checks this flag before setting `game_hitbox_click` and resets it at the end of each cell.

## Common Gotchas
- `zipfile_deflate64` import must be wrapped in `try/except` in patches.py — not available without C++ compiler
- `Game.__setattr__` auto-saves to DB on assignment to tracked fields — no need to call `db.update_game()` manually
- Auto-migration runs every startup: adds missing columns, drops deprecated ones
- `globals.popup_stack` is iterated each frame; removing an item closes the popup
- The fast-check cache API (`api.f95checker.dev`) does bulk checks; full-check hits F95zone directly
