# Code review, 4 October 2026

A review of the whole repository on the `founder` branch: the committed code (`version -- 1.0.1`) and
the staged, uncommitted work of 4 October. Nothing was changed by the review. Items are listed so
they can be ticked off; when one is fixed, remove it from this file.

> **Update, end of 4 October.** A great deal was built after this review: the canvas panel, rows of
> shots, audio, the agent's tools and attachments, motion graphics. None of that code has been
> reviewed. What follows is the review of the code as it stood that morning, with fixed items removed.

**Verdict.** The backend is in good shape for a one-machine product. The weak spots are the newest
front-end pages (no automated tests) and a repository carrying a lot of dead weight.

## 1. What is good

- **Small and readable.** About 3,600 lines of backend and 3,700 of front end, no build step, clear module boundaries.
- **Workflows are data.** A ComfyUI file dropped into `workflows/` becomes a form with no code change.
- **The backend is tested.** 60 tests pass without ComfyUI, Ollama or Node.js, including per-user isolation and credit refunds.
- **Security basics are right.** Scrypt passwords, session tokens stored only as hashes, HttpOnly
  SameSite=Lax cookies, and a password change signs out every other device.
- **The agent cannot spend on its own.** The server checks every proposed step against the real
  workflows, and nothing is queued until the user approves.

## 2. Bugs

The six front-end bugs found by the review (all in `home.js`, `projects.js`, `main.js` and `dom.js`)
were fixed on 4 October and are no longer listed. The fixes were read through but not tried in a
browser; see "Not tested" in `HANDOVER.md`.

Still open, in the committed code: the `video_minimax_h3_i2v` workflow failed on the real server
with "SaveVideo.execute() missing 1 required positional argument: 'format'". It could not be
reproduced offline on 4 October: with node definitions fetched fresh from ComfyUI, the job graph
gives the save node its `format`. A likely cause, not confirmed, is an out-of-date
`storage/cache/node_definitions.json` on the machine where it failed; deleting that file makes the
app fetch it again. It needs one real run to close.

## 3. Risks in the older code

- **Thirteen endpoints accept any JSON** (`body: dict` or `settings: dict`). A wrong type can give a
  server error instead of a clear message. Only the timeline export has been made to check its clips.
- **Timeline export runs inside the request.** A long cut keeps the request open until ffmpeg
  finishes, and nothing limits how many exports run at once.
- **Database and file work blocks the server.** SQLite calls and file reads run directly inside
  async handlers behind one global lock (`db.py`). Fine for a handful of users, not for many.
- **The login throttle is keyed on email plus client address.** An attacker who changes the email on
  each attempt is never blocked. (Since 5 October the address is the visitor's own, read from
  `CF-Connecting-IP` when the request comes through the tunnel.)
- **No CI and no linter.**

## 4. Unnecessary things and bloat

- **Screenshots.** `design/previews/` is 65 tracked files and 8 MB, about twenty times the size of
  the app's code. Most are from dropped stages (the teal palette, the black background, the first
  hard look). `HANDOVER.md` section 7 says which ones still show the current app.
- **Experimental workflows.** Five of the eight files in `workflows/video/` have no presets file,
  and the agent offers every readable workflow to the model as if it were finished.
  `workflows/archive/` holds three backups; two are used by a test.
- **`legacy/`.** A broken command-line script and its notes, still tracked.
- **The `main` branch.** Only compiled files and local data.
- **Browser pop-ups.** 30 uses of the plain `prompt`, `alert` and `confirm` boxes remain, next to the
  app's own dialogs.

## 5. What could be improved

- **One place for job settings.** The logic that turns a form into a job now exists four times:
  `pages/create.js`, `components/composer.js`, `components/quick.js` and `backend/scene/agent.py` (`settings_for`). A change
  to how a workflow is described has to be made in all three.
- **Shared helpers.** The project picker is built separately on Canvas, Timeline, Library and Create.
  (The thumbnail code that was repeated seven times is now one function, `still()` in `dom.js`.)
- **Paging in the library.** `GET /api/library` returns up to 500 full records with their settings.
  Home fetches all of them to show 60, and Create to show 4. The Canvas creates an element for every one.
- **The stylesheet.** 596 lines with one rule per line, five of them over 300 characters. It works,
  but a change is hard to read in a diff.
- **Front-end tests.** Canvas, Timeline, the agent panel, Quick actions, Home and All projects have none. Every bug
  in section 2 is in that code.

## 6. Suggested order

1. Validate the bodies of the endpoints that take raw JSON.
2. Delete the stale screenshots, the workflows that are not used, and `legacy/` (ask yogesh first:
   they are his files).
3. Pull the shared job-settings code into one place before adding more pages.
4. Review the code written on 4 October after this review.

## Fixed on 4 October

The six front-end bugs; a 200 MB limit on reference and asset uploads, checked before the file is
read into memory; the timeline export's check of its clips; the login throttle forgetting old
entries; pinned versions in `backend/requirements.txt`; the eight unused icons; the repeated
thumbnail code.

Later the same day, in `components/quick.js`: the word "false" printed under Source for a workflow
with three or fewer reference slots, and an error after Generate being wiped by the price refresh a
moment later. And every page of thumbnails loading the start of each video: thumbnails are posters now.

## How this review was done

An automated review of the uncommitted diff (`git diff HEAD`), followed by a manual pass over the
committed backend, front end, tests and repository contents: file sizes and counts, the session and
upload code, SQL building in the admin console, and searches for dead code and repeated code. The
test suite was run (38 pass). The app was not started and no page was rendered for this review.
