# Code review, 4 October 2026

A review of the whole repository on the `founder` branch: the committed code (`version -- 1.0.1`) and
the staged, uncommitted work of 4 October. Nothing was changed by the review. Items are listed so
they can be ticked off; when one is fixed, remove it from this file.

**Verdict.** The backend is in good shape for a one-machine product. The weak spots are the newest
front-end pages (six bugs, no automated tests), missing upload limits, and a repository carrying a
lot of dead weight.

## 1. What is good

- **Small and readable.** About 3,600 lines of backend and 3,700 of front end, no build step, clear module boundaries.
- **Workflows are data.** A ComfyUI file dropped into `workflows/` becomes a form with no code change.
- **The backend is tested.** 38 tests pass without ComfyUI or Ollama, including per-user isolation and credit refunds.
- **Security basics are right.** Scrypt passwords, session tokens stored only as hashes, HttpOnly
  SameSite=Lax cookies, and a password change signs out every other device.
- **The agent cannot spend on its own.** The server checks every proposed step against the real
  workflows, and nothing is queued until the user approves.

## 2. Bugs

All six are in the uncommitted front-end work. "Confirmed" means the path was followed in the code
to a wrong result; "traced" means the code allows it but it was not reproduced.

| # | Where | Problem | Status |
|---|---|---|---|
| 1 | `frontend/assets/js/pages/home.js:16` | A job started from the Home bar is filed under no project, but "Watch it on the Canvas" opens the last-opened project, whose canvas hides it (`canvas.js` only shows jobs of the current project). Neither the running frame nor the result appears there. | Confirmed |
| 2 | `frontend/assets/js/components/projects.js:24` | The project window creates the project, then saves the Brief. If saving the Brief fails, pressing Create again makes a duplicate project, and Cancel opens the one already created. | Confirmed |
| 3 | `frontend/assets/js/components/projects.js:39` | Cancel and Escape stay active while the create request is running. The window closes as cancelled, but the project is still created and the list is not reloaded. | Traced |
| 4 | `frontend/assets/js/pages/home.js:57` | `drawMade` does not discard slow responses. Switching All / Videos / Images quickly, or a library update mid-request, can leave the grid showing a different kind than the selected one. | Traced |
| 5 | `frontend/assets/js/main.js:50` | Signing in sets `location.hash` and then calls `showApp()`, so the page is routed once directly and again by the queued `hashchange`. Home is drawn twice, with duplicate requests. | Traced |
| 6 | `frontend/assets/js/dom.js:72` | `initials()` takes `word[0]`, which cuts a character made of two code units in half. A project name starting with an emoji shows a broken glyph. | Confirmed |

Already known, in the committed code: the `video_minimax_h3_i2v` workflow fails on the real server
with "SaveVideo.execute() missing 1 required positional argument: 'format'".

## 3. Risks in the older code

- **No size limit on reference uploads.** `POST /api/jobs` reads each reference file fully into
  memory (`upload.read()`). Assets check their 200 MB limit only after reading the whole file.
- **Thirteen endpoints accept any JSON** (`body: dict` or `settings: dict`). A wrong type gives a
  server error instead of a clear message; for example a non-numeric `start` in a timeline clip
  raises inside `float()` in `api/workspace.py`.
- **Timeline export runs inside the request.** A long cut keeps the request open until ffmpeg
  finishes, and nothing limits how many exports run at once.
- **Database and file work blocks the server.** SQLite calls and file reads run directly inside
  async handlers behind one global lock (`db.py`). Fine for a handful of users, not for many.
- **The login throttle never forgets.** `LoginThrottle.failures` keeps an entry for every email ever
  tried. It is keyed on email plus client address, so behind a proxy every user shares one address,
  and an attacker who changes the email on each attempt is never blocked.
- **Dependencies are unpinned.** `backend/requirements.txt` uses `>=` for all six packages and there
  is no lock file, so two installs can differ. There is no CI and no linter.

## 4. Unnecessary things and bloat

- **Screenshots.** `design/previews/` is 65 tracked files and 8 MB, about twenty times the size of
  the app's code. Most are from dropped stages (the teal palette, the black background, the first
  hard look). `HANDOVER.md` section 7 says which ones still show the current app.
- **Experimental workflows.** Five of the eight files in `workflows/video/` have no presets file,
  and the agent offers every readable workflow to the model as if it were finished.
  `workflows/archive/` holds three backups; two are used by a test.
- **`legacy/`.** A broken command-line script and its notes, still tracked.
- **The `main` branch.** Only compiled files and local data.
- **Dead front-end code.** Eight icons in `dom.js` are no longer used since the sidebar was trimmed:
  `sun`, `moon`, `monitor`, `bookmark`, `list`, `generate`, `canvas`, `timeline`.
- **Browser pop-ups.** 30 uses of the plain `prompt`, `alert` and `confirm` boxes remain, next to the
  app's own dialogs.

## 5. What could be improved

- **One place for job settings.** The logic that turns a form into a job exists three times:
  `pages/create.js`, `components/composer.js` and `backend/scene/agent.py` (`settings_for`). A change
  to how a workflow is described has to be made in all three.
- **Shared helpers.** The thumbnail code (`<video preload="metadata" muted>` or `<img>`) is repeated
  seven times, and the project picker is built separately on Canvas, Timeline, Library and Create.
- **Paging in the library.** `GET /api/library` returns up to 500 full records with their settings.
  Home fetches all of them to show 60, and Create to show 4. The Canvas creates an element for every one.
- **The stylesheet.** 596 lines with one rule per line, five of them over 300 characters. It works,
  but a change is hard to read in a diff.
- **Front-end tests.** Canvas, Timeline, the agent panel, Home and All projects have none. Every bug
  in section 2 is in that code.

## 6. Suggested order

1. Fix the six front-end bugs in section 2.
2. Add upload size limits, and validate the bodies of the endpoints that take raw JSON.
3. Delete the stale screenshots, the workflows that are not used, and `legacy/` (ask yogesh first:
   they are his files).
4. Pin dependency versions.
5. Pull the shared job-settings and thumbnail code into one place before adding more pages.

## How this review was done

An automated review of the uncommitted diff (`git diff HEAD`), followed by a manual pass over the
committed backend, front end, tests and repository contents: file sizes and counts, the session and
upload code, SQL building in the admin console, and searches for dead code and repeated code. The
test suite was run (38 pass). The app was not started and no page was rendered for this review.
