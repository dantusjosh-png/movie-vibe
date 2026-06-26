"""
app.py — local web UI for the movie vibe recommender.

Run:
    python3 app.py
then open http://localhost:8000 in your browser.

Type any vibe ("a movie for when I have a fever") and it runs the live recommender
from recommend.py and shows a card. No extra dependencies — stdlib http.server only.
"""

import os
import json
import datetime
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import recommend  # reuses the whole live-search pipeline

PORT = int(os.environ.get("PORT", 8000))  # cloud hosts assign the port via $PORT

# ── spend safeguard ───────────────────────────────────────────────────────────
# Each recommendation costs ~2¢ in API calls. This caps how many run per day
# across ALL visitors, so a public link can't run up your bill. ~$2/day ceiling.
DAILY_CAP = 50
_usage = {"date": None, "count": 0}
_usage_lock = threading.Lock()


def _allow_query() -> bool:
    today = datetime.date.today().isoformat()
    with _usage_lock:
        if _usage["date"] != today:
            _usage["date"], _usage["count"] = today, 0
        if _usage["count"] >= DAILY_CAP:
            return False
        _usage["count"] += 1
        return True

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>vibe — movie recommendations from real people</title>
<style>
  :root { --bg:#0e0e12; --card:#181820; --line:#26262f; --accent:#e8b75c; --text:#ece9e3; --muted:#9a98a3; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         min-height:100vh; display:flex; flex-direction:column; align-items:center; }
  .wrap { width:100%; max-width:680px; padding:48px 20px 80px; }
  h1 { font-size:30px; font-weight:700; letter-spacing:-0.02em; margin:0 0 6px; }
  h1 .dot { color:var(--accent); }
  .sub { color:var(--muted); margin:0 0 28px; font-size:15px; line-height:1.5; }
  form { display:flex; gap:10px; }
  input { flex:1; background:var(--card); border:1px solid var(--line); color:var(--text);
          padding:14px 16px; border-radius:12px; font-size:16px; outline:none; }
  input:focus { border-color:var(--accent); }
  button { background:var(--accent); color:#1a1206; border:none; padding:0 22px;
           border-radius:12px; font-size:16px; font-weight:600; cursor:pointer; }
  button:disabled { opacity:.5; cursor:default; }
  .chips { margin:14px 0 0; display:flex; flex-wrap:wrap; gap:8px; }
  .chip { background:transparent; border:1px solid var(--line); color:var(--muted);
          padding:7px 12px; border-radius:999px; font-size:13px; cursor:pointer; }
  .chip:hover { border-color:var(--accent); color:var(--text); }
  .status { margin-top:30px; color:var(--muted); font-size:15px; }
  .spinner { display:inline-block; width:15px; height:15px; border:2px solid var(--line);
             border-top-color:var(--accent); border-radius:50%; animation:spin .8s linear infinite;
             vertical-align:-2px; margin-right:8px; }
  @keyframes spin { to { transform:rotate(360deg); } }
  .card { margin-top:30px; background:var(--card); border:1px solid var(--line);
          border-radius:16px; padding:26px; display:none; }
  .pick-label { color:var(--accent); font-size:12px; font-weight:700; letter-spacing:.08em;
                text-transform:uppercase; }
  .pick-title { font-size:24px; font-weight:700; margin:6px 0 10px; }
  .pick-title .yr { color:var(--muted); font-weight:400; font-size:18px; }
  .why { color:var(--text); line-height:1.55; font-size:16px; }
  .pick { display:flex; gap:18px; }
  .pick-poster { width:104px; border-radius:10px; flex-shrink:0; background:#000; }
  .pick-body { flex:1; min-width:0; }
  .rating, .rt, .imdb { display:inline-block; font-size:12px; font-weight:600;
            padding:2px 8px; border-radius:6px; margin-left:8px; vertical-align:2px; }
  .rating { background:rgba(232,183,92,.14); color:var(--accent); }
  .rt { background:rgba(250,100,80,.16); color:#fa6450; }
  .imdb { background:rgba(245,197,24,.16); color:#f5c518; }
  .overview { color:var(--muted); font-size:13.5px; line-height:1.5; margin:8px 0 12px; }
  .runners { margin-top:24px; border-top:1px solid var(--line); padding-top:20px; }
  .runners h3 { font-size:13px; text-transform:uppercase; letter-spacing:.06em;
                color:var(--muted); margin:0 0 14px; font-weight:600; }
  .ru { margin-bottom:18px; }
  .ru-title { font-weight:600; font-size:16px; }
  .ru-title .yr { color:var(--muted); font-weight:400; }
  .badge { display:inline-block; background:rgba(232,183,92,.14); color:var(--accent);
           font-size:11px; padding:2px 8px; border-radius:999px; margin-left:8px; vertical-align:1px; }
  .ru-why { color:var(--muted); font-size:14px; line-height:1.5; margin-top:3px; }
  .where { margin-top:10px; font-size:13.5px; color:var(--accent); }
  .where a { color:var(--accent); text-decoration:none; border-bottom:1px solid rgba(232,183,92,.4); }
  .ru-where { margin-top:4px; font-size:12.5px; color:var(--accent); opacity:.9; }
  .err { color:#e89a9a; }
  .seen-btn { margin-top:14px; background:transparent; border:1px solid var(--line); color:var(--muted);
              font-size:12px; padding:5px 12px; border-radius:999px; cursor:pointer; }
  .seen-btn:hover { border-color:var(--accent); color:var(--text); }
  .watched-bar { margin-top:18px; color:var(--muted); font-size:12.5px; }
  .watched-bar a { color:var(--accent); }
  .foot { margin-top:40px; color:var(--muted); font-size:12px; line-height:1.6; }
</style>
</head>
<body>
<div class="wrap">
  <h1>vibe<span class="dot">.</span></h1>
  <p class="sub">Tell me the exact mood you're after. I'll dig through real Reddit
     threads where people asked for the same thing and bring back what they swear by.</p>
  <form id="f">
    <input id="q" autocomplete="off" placeholder="a movie for when I have a fever…" />
    <button id="go" type="submit">Find</button>
  </form>
  <div class="chips" id="chips"></div>
  <div class="status" id="status"></div>
  <div class="card" id="card"></div>
  <div class="watched-bar" id="watchedBar"></div>
  <div class="foot">Recommendations are paraphrased from real Reddit discussions. Live search &amp; AI synthesis &mdash; gives a fresh answer for whatever you type.</div>
</div>
<script>
const EXAMPLES = ["movies to watch while having a fever","something that makes you feel uplifted and fulfilled","a slow burn that creeps you out","feel like a warm hug","mind-bending sci-fi that respects your intelligence"];
const chips = document.getElementById('chips');
EXAMPLES.forEach(e => { const b=document.createElement('button'); b.className='chip'; b.type='button'; b.textContent=e;
  b.onclick=()=>{ document.getElementById('q').value=e; document.getElementById('f').requestSubmit(); }; chips.appendChild(b); });

const f=document.getElementById('f'), q=document.getElementById('q'), go=document.getElementById('go'),
      status=document.getElementById('status'), card=document.getElementById('card'),
      watchedBar=document.getElementById('watchedBar');
let lastResult=null;

// watched list — saved in THIS browser only (localStorage)
function getWatched(){ try { return JSON.parse(localStorage.getItem('watchedMovies')||'[]'); } catch(e){ return []; } }
function isWatched(t){ return getWatched().includes((t||'').toLowerCase()); }
function addWatched(t){ const w=getWatched(), k=(t||'').toLowerCase(); if(k && !w.includes(k)){ w.push(k); localStorage.setItem('watchedMovies', JSON.stringify(w)); } }
function clearWatched(){ localStorage.removeItem('watchedMovies'); updateWatchedBar(); if(lastResult) render(lastResult); }
function updateWatchedBar(){ const n=getWatched().length;
  watchedBar.innerHTML = n ? ('✓ '+n+' marked as seen · <a href="#" id="clearWatched">clear list</a>') : ''; }

f.onsubmit = async (ev) => {
  ev.preventDefault();
  const request = q.value.trim(); if(!request) return;
  go.disabled=true; card.style.display='none';
  status.innerHTML = '<span class="spinner"></span>Searching Reddit and reading threads…';
  try {
    const r = await fetch('/api/recommend', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({request})});
    const data = await r.json();
    status.innerHTML='';
    if (data.error){ lastResult=null; card.style.display='block'; card.innerHTML='<div class="why err">'+data.error+'</div>'; }
    else render(data);
  } catch(e){ status.innerHTML='<span class="err">Something went wrong. Is the server still running?</span>'; }
  go.disabled=false;
};

function esc(s){ const d=document.createElement('div'); d.textContent=s==null?'':s; return d.innerHTML; }
function escAttr(s){ return esc(s).replace(/"/g,'&quot;'); }
function seenBtn(t,label){ return '<button class="seen-btn" data-title="'+escAttr(t)+'">'+label+'</button>'; }
function whereText(s){
  if(!s) return '';
  const parts=[];
  if(s.flatrate&&s.flatrate.length) parts.push('Stream on '+s.flatrate.slice(0,3).map(esc).join(', '));
  if(s.rent&&s.rent.length) parts.push('rent on '+s.rent.slice(0,2).map(esc).join(', '));
  else if(s.buy&&s.buy.length) parts.push('buy on '+s.buy.slice(0,2).map(esc).join(', '));
  return parts.join(' · ');
}
function ratingsHtml(m){
  let h='';
  if(m.rt) h+='<span class="rt">🍅 '+esc(m.rt)+'</span>';
  if(m.imdb) h+='<span class="imdb">IMDb '+esc(m.imdb)+'</span>';
  if(!m.rt && !m.imdb && m.tmdb_rating) h+='<span class="rating">★ '+esc(m.tmdb_rating)+'</span>';
  return h;
}
function render(d){
  lastResult=d;
  const all=[d.top_pick||{}].concat(d.runners_up||[]).filter(m=>m.title && !isWatched(m.title));
  if(!all.length){
    card.innerHTML='<div class="why">All of these are marked as seen — try another vibe!</div>';
    card.style.display='block'; updateWatchedBar(); return;
  }
  const tp=all[0], ru=all.slice(1);
  let body='<div class="pick-title">'+esc(tp.title)+' <span class="yr">'+esc(tp.year||'')+'</span>'+ratingsHtml(tp)+'</div>';
  if(tp.overview) body+='<div class="overview">'+esc(tp.overview)+'</div>';
  body+='<div class="why">'+esc(tp.why)+'</div>';
  const tw=whereText(tp.streaming);
  if(tw){ const link=tp.streaming&&tp.streaming.link;
    body+='<div class="where">▸ '+tw+(link?' &nbsp;<a href="'+esc(link)+'" target="_blank">where to watch ↗</a>':'')+'</div>'; }
  body+=seenBtn(tp.title,'✓ Seen it — hide from future');
  let html='<div class="pick-label">Top pick</div>'+body;
  if(ru.length){
    html+='<div class="runners"><h3>also worth a look</h3>';
    ru.forEach(m=>{
      const badge=(m.mentions&&m.mentions>1)?'<span class="badge">'+m.mentions+' threads</span>':'';
      let rb='<div class="ru-title">'+esc(m.title)+' <span class="yr">'+esc(m.year||'')+'</span>'+badge+ratingsHtml(m)+'</div>'
            +'<div class="ru-why">'+esc(m.why)+'</div>';
      const mw=whereText(m.streaming); if(mw) rb+='<div class="ru-where">▸ '+mw+'</div>';
      rb+=seenBtn(m.title,'✓ Seen it');
      html+='<div class="ru">'+rb+'</div>';
    });
    html+='</div>';
  }
  card.innerHTML=html; card.style.display='block';
  updateWatchedBar();
}

card.addEventListener('click', e=>{
  const b=e.target.closest('.seen-btn'); if(!b) return;
  addWatched(b.dataset.title); updateWatchedBar(); if(lastResult) render(lastResult);
});
watchedBar.addEventListener('click', e=>{
  if(e.target.id==='clearWatched'){ e.preventDefault(); clearWatched(); }
});
updateWatchedBar();
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE)
        else:
            self._send(404, "not found")

    def do_POST(self):
        if self.path != "/api/recommend":
            self._send(404, "not found"); return
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length) or "{}").get("request", "").strip()
        except Exception:
            req = ""
        if not req:
            self._send(200, json.dumps({"error": "Type what you're in the mood for."}),
                       "application/json"); return
        if not _allow_query():
            self._send(200, json.dumps({"error": "This demo has hit its daily limit — check back tomorrow!"}),
                       "application/json"); return
        try:
            result = recommend.recommend(req)
            if result is None:
                result = {"error": "Couldn't find Reddit threads for that one — try rephrasing or making it a bit less specific."}
        except Exception as e:
            result = {"error": f"Hit a snag: {e}"}
        self._send(200, json.dumps(result), "application/json")

    def log_message(self, *args):
        pass  # quiet; recommend.py prints its own progress


if __name__ == "__main__":
    print(f"\n  vibe is running →  http://localhost:{PORT}\n  (Ctrl+C to stop)\n")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
