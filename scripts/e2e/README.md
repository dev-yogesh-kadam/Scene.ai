# Browser check

A throwaway copy of the studio, driven in headless Chrome. It never touches the real data or the real app.

1. `cd backend`, then `..\.venv\Scripts\python.exe ..\scripts\e2e\server.py` (port 8099, the admin console on 8098, empty SQLite storage in
   the system temp folder under `scene-e2e`, the real workflows and page, a fake agent model that answers after
   1.6 s, two fake agent models for the price menu, no render server).
2. In another shell: `node scripts/e2e/check.mjs`. It makes an account (the first one, so an admin), uploads a test
   clip and two pictures, seeds a conversation, and checks the agent panel, the canvas focus, live progress,
   approving, the tabs' history, the model menu, the lanes and the library. It prints PASS / FAIL lines and saves
   screenshots to the same temp folder.
3. `node scripts/e2e/import_check.mjs` imports every page module in Chrome and names any that fails to load.
4. `node scripts/e2e/console_check.mjs` checks the admin console on its own port (8098; the studio is on 8099): the
   studio's link to it, its own sign-in, every section, the live count and signing out. Restart server.py first: it
   needs the first account to be the admin.

Restart server.py before each run of check.mjs: a second account is not an admin and has no agent. It needs Google
Chrome at its usual place and `puppeteer-core`, which is in `motion/node_modules`.
