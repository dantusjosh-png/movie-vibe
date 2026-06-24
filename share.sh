#!/bin/bash
# Share the vibe app with anyone, anywhere — one command.
#   ./share.sh
# It starts the app and opens a public link. Look for the
# https://something.trycloudflare.com URL it prints — that's what you send people.
# Keep this window open while they use it. Press Ctrl+C to stop everything.

cd "$(dirname "$0")"

echo "Starting the app..."
python3 app.py > server.log 2>&1 &
APP_PID=$!
sleep 3

# stop the app too when you Ctrl+C the tunnel
trap "kill $APP_PID 2>/dev/null; echo; echo 'Stopped.'; exit 0" INT TERM

echo "Opening your public link below (look for the trycloudflare.com URL)..."
echo "------------------------------------------------------------------"
cloudflared tunnel --url http://localhost:8000

kill $APP_PID 2>/dev/null
