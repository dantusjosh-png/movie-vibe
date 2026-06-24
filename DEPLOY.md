# Deploying vibe to a permanent public URL (free, via Render)

This gets you a link like `https://movie-vibe.onrender.com` that works 24/7,
even when your laptop is off, that anyone can open.

## What's already done (by Claude)
- Code reads API keys from secure environment variables when deployed (your keys
  are NOT in the code that goes public — see `.gitignore`).
- `requirements.txt`, `render.yaml`, and this guide are in place.
- A local git repo is committed, with `credentials copy.py` excluded.

## Step 1 — put the code on GitHub (one time)
1. Make a free account at https://github.com if you don't have one.
2. In your terminal, run:  `gh auth login`
   - Choose **GitHub.com** → **HTTPS** → **Login with a web browser**.
   - Copy the one-time code it shows, hit Enter, paste it in the browser, authorize.
3. Tell Claude "I'm authed" and Claude will create the repo and push the code,
   OR run it yourself:
   `gh repo create movie-vibe --public --source=. --push`

## Step 2 — deploy on Render (one time, ~5 min)
1. Make a free account at https://render.com (sign up **with GitHub** — easiest).
2. Click **New +** → **Web Service**.
3. Pick your **movie-vibe** repo. Render reads `render.yaml` and fills in the
   settings automatically (build + start commands).
4. Before clicking create, add your two secrets under **Environment** →
   **Environment Variables**:
   - `ANTHROPIC_API_KEY` = your Anthropic key
   - `TMDB_API_KEY` = your TMDB key
5. Click **Create Web Service**. Wait a few minutes for it to build.
6. Render gives you your permanent URL at the top of the page. That's the link
   you share with anyone.

## Good to know
- **Free tier sleeps when idle.** First visit after ~15 min of no use takes
  ~30–60s to wake up, then it's fast. The URL is always there.
- **Spend cap:** the app is capped at 50 recommendations/day (~$1/day max).
  Change `DAILY_CAP` at the top of `app.py` to adjust.
- **To update the live site later:** make changes, then
  `git add -A && git commit -m "update" && git push` — Render redeploys automatically.
