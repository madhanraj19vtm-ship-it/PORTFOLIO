"""
Madhanraj Portfolio - Backend Server & API
Handles:
- Static file serving (HTML, CSS, JS, Images)
- Contact form submission API (POST /api/contact)
- SQLite persistent message storage (messages.db)
- JSON backup logging (messages.json)
- Admin messages viewer (GET /admin)
- Health check API (GET /api/health)
"""

import os
import sys
import json
import sqlite3
import argparse
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "messages.db")
JSON_LOG_PATH = os.path.join(BASE_DIR, "messages.json")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        message TEXT NOT NULL,
        ip_address TEXT,
        user_agent TEXT,
        status TEXT DEFAULT 'unread'
    )
    """)
    conn.commit()
    conn.close()


def save_message(name, email, message, ip="", user_agent=""):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO contacts (timestamp, name, email, message, ip_address, user_agent, status)
        VALUES (?, ?, ?, ?, ?, ?, 'unread')
    """, (timestamp, name, email, message, ip, user_agent))
    msg_id = cur.lastrowid
    conn.commit()
    conn.close()

    # Append to messages.json backup
    try:
        data = []
        if os.path.exists(JSON_LOG_PATH):
            with open(JSON_LOG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        data.insert(0, {
            "id": msg_id,
            "timestamp": timestamp,
            "name": name,
            "email": email,
            "message": message,
            "ip": ip,
            "user_agent": user_agent,
            "status": "unread"
        })
        with open(JSON_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[WARN] Failed to write JSON backup: {e}")

    return msg_id, timestamp


def get_all_messages():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM contacts ORDER BY id DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def delete_message_by_id(msg_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM contacts WHERE id = ?", (msg_id,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()

    # Sync deletion with messages.json backup
    if deleted and os.path.exists(JSON_LOG_PATH):
        try:
            with open(JSON_LOG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            data = [m for m in data if m.get("id") != msg_id]
            with open(JSON_LOG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[WARN] Failed to sync deletion in JSON backup: {e}")

    return deleted


class PortfolioRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def end_headers(self):
        # Enable CORS for local testing/dev
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def send_json(self, status_code, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url_path = self.path.split("?")[0].rstrip("/")

        # API: messages list
        if url_path == "/api/messages":
            msgs = get_all_messages()
            self.send_json(200, {"success": True, "count": len(msgs), "messages": msgs})
            return

        # API: health check
        if url_path == "/api/health":
            msgs = get_all_messages()
            self.send_json(200, {
                "status": "online",
                "portfolio_owner": "Madhanraj V",
                "database": "SQLite (messages.db)",
                "total_messages": len(msgs),
                "timestamp": datetime.now().isoformat()
            })
            return

        # Admin messages viewer
        if url_path in ("/admin", "/messages"):
            self.render_admin_dashboard()
            return

        # Otherwise serve static files
        super().do_GET()

    def do_POST(self):
        url_path = self.path.split("?")[0].rstrip("/")

        if url_path == "/api/contact":
            try:
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len).decode("utf-8")
                data = json.loads(body) if body else {}

                name = str(data.get("name", "")).strip()
                email = str(data.get("email", "")).strip()
                message = str(data.get("message", "")).strip()

                if not name or not message:
                    self.send_json(400, {
                        "success": False,
                        "error": "Both 'name' and 'message' are required fields."
                    })
                    return

                # If no email provided, default placeholder
                if not email:
                    email = "Not provided"

                client_ip = self.client_address[0]
                user_agent = self.headers.get("User-Agent", "Unknown")

                msg_id, timestamp = save_message(name, email, message, client_ip, user_agent)
                print(f"[CONTACT SUBMISSION] #{msg_id} from {name} ({email}) at {timestamp}")

                self.send_json(200, {
                    "success": True,
                    "message": f"Thank you, {name}! Your message has been received.",
                    "id": msg_id,
                    "timestamp": timestamp
                })
            except Exception as e:
                print(f"[ERROR] Contact form processing: {e}")
                self.send_json(500, {"success": False, "error": str(e)})
            return

        if url_path == "/api/messages/delete":
            try:
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len).decode("utf-8")
                data = json.loads(body) if body else {}
                msg_id = data.get("id")

                if not msg_id:
                    self.send_json(400, {"success": False, "error": "Message ID is required."})
                    return

                deleted = delete_message_by_id(int(msg_id))
                self.send_json(200, {"success": True, "deleted": deleted})
            except Exception as e:
                self.send_json(500, {"success": False, "error": str(e)})
            return

        self.send_json(404, {"success": False, "error": "Not Found"})

    def render_admin_dashboard(self):
        msgs = get_all_messages()
        total_count = len(msgs)

        cards_html = ""
        if not msgs:
            cards_html = """
            <div class="p-12 text-center text-zinc-500 border border-zinc-800/80 rounded-2xl bg-zinc-900/30">
              <i class="fa-regular fa-folder-open text-4xl mb-3 text-zinc-600 block"></i>
              <p class="font-mono text-sm">No contact messages stored yet.</p>
              <p class="text-xs text-zinc-600 mt-1">When someone submits your portfolio contact form, their message will appear here.</p>
            </div>
            """
        else:
            for m in msgs:
                esc_name = html_escape(m['name'])
                esc_email = html_escape(m['email'])
                esc_msg = html_escape(m['message']).replace("\n", "<br>")
                esc_time = html_escape(m['timestamp'])
                m_id = m['id']

                mail_link = f"mailto:{esc_email}?subject=Reply%20to%20your%20inquiry%20via%20Madhanraj%20Portfolio"
                cards_html += f"""
                <div id="msg-{m_id}" class="p-6 rounded-2xl bg-zinc-900/60 border border-zinc-800 hover:border-zinc-700 transition-all shadow-xl">
                  <div class="flex flex-wrap items-center justify-between gap-3 mb-4 border-b border-zinc-800/60 pb-3">
                    <div class="flex items-center gap-3">
                      <div class="w-10 h-10 rounded-full bg-blue-600/20 text-blue-400 font-bold flex items-center justify-center font-syne text-lg">
                        {esc_name[0].upper() if esc_name else 'V'}
                      </div>
                      <div>
                        <h4 class="font-syne font-bold text-white text-base leading-snug">{esc_name}</h4>
                        <div class="flex items-center gap-2 text-xs font-mono text-zinc-400">
                          <i class="fa-regular fa-envelope text-blue-400 text-[10px]"></i>
                          <a href="{mail_link}" class="hover:text-blue-300 underline">{esc_email}</a>
                        </div>
                      </div>
                    </div>
                    <div class="flex items-center gap-3">
                      <span class="text-xs font-mono text-zinc-500">{esc_time}</span>
                      <button onclick="deleteMessage({m_id})" class="px-3 py-1 text-xs font-mono rounded bg-red-950/60 text-red-400 border border-red-800/60 hover:bg-red-900 hover:text-white transition-all">
                        <i class="fa-solid fa-trash-can text-[10px] mr-1"></i>Delete
                      </button>
                    </div>
                  </div>
                  <div class="text-sm text-zinc-300 font-sans whitespace-pre-wrap leading-relaxed bg-zinc-950/60 p-4 rounded-xl border border-zinc-900">
                    {esc_msg}
                  </div>
                </div>
                """

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Madhanraj V // Contact Messages Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Syne:wght@700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    body {{ background-color: #070709; font-family: 'Inter', sans-serif; }}
    .font-syne {{ font-family: 'Syne', sans-serif; }}
    .font-mono {{ font-family: 'JetBrains Mono', monospace; }}
  </style>
</head>
<body class="text-zinc-100 min-h-screen py-10 px-4 sm:px-8">
  <div class="max-w-4xl mx-auto">
    <!-- Top Header -->
    <div class="flex flex-wrap items-center justify-between gap-4 mb-8 border-b border-zinc-800 pb-6">
      <div>
        <div class="flex items-center gap-2 mb-1">
          <span class="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse"></span>
          <span class="font-mono text-xs text-zinc-400 tracking-wider">BACKEND RUNNING // PORT 8080</span>
        </div>
        <h1 class="font-syne font-extrabold text-2xl sm:text-3xl text-white tracking-tight">
          CONTACT MESSAGES INBOX
        </h1>
        <p class="text-xs text-zinc-400 mt-1">SQLite database: <code class="text-blue-400">d:\\Portfolio\\messages.db</code></p>
      </div>

      <div class="flex items-center gap-3">
        <a href="/" class="px-4 py-2 rounded-xl bg-zinc-900 border border-zinc-800 text-xs font-mono text-zinc-300 hover:text-white hover:border-zinc-600 transition-all">
          <i class="fa-solid fa-arrow-left mr-1.5"></i> Back to Portfolio
        </a>
        <button id="lockBtn" onclick="logoutAdmin()" class="hidden px-4 py-2 rounded-xl bg-red-950/40 border border-red-800/60 text-xs font-mono text-red-300 hover:text-white transition-all">
          <i class="fa-solid fa-lock mr-1.5"></i> Lock Console
        </button>
      </div>
    </div>

    <!-- Login Gate -->
    <div id="loginGate" class="max-w-md mx-auto my-12 p-8 rounded-3xl bg-zinc-950 border border-zinc-800 shadow-2xl text-center">
      <div class="w-14 h-14 rounded-2xl bg-blue-600/20 border border-blue-500/30 text-blue-400 flex items-center justify-center text-xl mx-auto mb-4">
        <i class="fa-solid fa-shield-halved"></i>
      </div>
      <h2 class="font-syne font-bold text-xl text-white mb-1">Admin Verification</h2>
      <p class="text-xs text-zinc-400 mb-6">Enter demo credentials to unlock the messages inbox.</p>

      <div class="mb-5 p-3.5 rounded-2xl bg-blue-950/30 border border-blue-800/50 text-left">
        <div class="flex items-center justify-between mb-2">
          <span class="text-[10px] font-mono font-bold uppercase text-blue-400">DEMO CREDENTIALS</span>
          <button type="button" onclick="fillDemo()" class="px-2 py-0.5 rounded bg-blue-600 text-white text-[10px] font-mono font-bold uppercase">AUTO FILL</button>
        </div>
        <div class="grid grid-cols-2 gap-2 text-xs font-mono text-zinc-300">
          <div class="bg-zinc-900 px-2.5 py-1 rounded-lg">User: <span class="text-emerald-400 font-bold">admin</span></div>
          <div class="bg-zinc-900 px-2.5 py-1 rounded-lg">Pass: <span class="text-emerald-400 font-bold">admin123</span></div>
        </div>
      </div>

      <form onsubmit="handleLogin(event)" class="space-y-3.5 text-left">
        <div>
          <label class="block text-[11px] font-mono text-zinc-400 mb-1">Username</label>
          <input type="text" id="userInput" required placeholder="admin" class="w-full px-4 py-2.5 rounded-xl bg-zinc-900 border border-zinc-800 text-sm text-white focus:outline-none focus:border-blue-500">
        </div>
        <div>
          <label class="block text-[11px] font-mono text-zinc-400 mb-1">Password</label>
          <input type="password" id="passInput" required placeholder="admin123" class="w-full px-4 py-2.5 rounded-xl bg-zinc-900 border border-zinc-800 text-sm text-white focus:outline-none focus:border-blue-500">
        </div>
        <div id="loginErr" class="hidden text-xs font-mono text-red-400 bg-red-950/40 p-2.5 rounded-xl border border-red-800/60 text-center">Invalid credentials.</div>
        <button type="submit" class="w-full py-3 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold font-syne uppercase tracking-wider transition-all">Unlock Messages</button>
      </form>
    </div>

    <!-- Authenticated Messages View -->
    <div id="authView" class="hidden">
      <!-- Stats Bar -->
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
        <div class="p-4 rounded-xl bg-zinc-900/50 border border-zinc-800">
          <span class="text-xs font-mono text-zinc-500 uppercase tracking-wider block mb-1">Total Submissions</span>
          <span class="text-2xl font-bold font-syne text-white">{total_count}</span>
        </div>
        <div class="p-4 rounded-xl bg-zinc-900/50 border border-zinc-800">
          <span class="text-xs font-mono text-zinc-500 uppercase tracking-wider block mb-1">Database Engine</span>
          <span class="text-lg font-bold font-mono text-emerald-400">SQLite3</span>
        </div>
        <div class="p-4 rounded-xl bg-zinc-900/50 border border-zinc-800">
          <span class="text-xs font-mono text-zinc-500 uppercase tracking-wider block mb-1">Receiver</span>
          <span class="text-sm font-bold font-mono text-blue-400 truncate block">madhanraj19vtm@gmail.com</span>
        </div>
      </div>

      <!-- Messages List -->
      <div class="space-y-4">
        {cards_html}
      </div>
    </div>
  </div>

  <script>
    function fillDemo() {{
      document.getElementById('userInput').value = 'admin';
      document.getElementById('passInput').value = 'admin123';
      document.getElementById('loginErr').classList.add('hidden');
    }}

    function handleLogin(e) {{
      e.preventDefault();
      const u = document.getElementById('userInput').value.trim().toLowerCase();
      const p = document.getElementById('passInput').value.trim();
      if (u === 'admin' && (p === 'admin123' || p === 'madhanraj@2026')) {{
        sessionStorage.setItem('admin_auth', 'true');
        applyAuth(true);
      }} else {{
        document.getElementById('loginErr').classList.remove('hidden');
      }}
    }}

    function logoutAdmin() {{
      sessionStorage.removeItem('admin_auth');
      applyAuth(false);
    }}

    function applyAuth(isAuthed) {{
      const gate = document.getElementById('loginGate');
      const view = document.getElementById('authView');
      const lockBtn = document.getElementById('lockBtn');
      if (isAuthed) {{
        gate.classList.add('hidden');
        view.classList.remove('hidden');
        lockBtn.classList.remove('hidden');
      }} else {{
        gate.classList.remove('hidden');
        view.classList.add('hidden');
        lockBtn.classList.add('hidden');
      }}
    }}

    document.addEventListener('DOMContentLoaded', () => {{
      applyAuth(sessionStorage.getItem('admin_auth') === 'true');
    }});

    async function deleteMessage(id) {{
      if (!confirm('Are you sure you want to delete message #' + id + '?')) return;
      try {{
        const res = await fetch('/api/messages/delete', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ id: id }})
        }});
        const data = await res.json();
        if (data.success) {{
          const el = document.getElementById('msg-' + id);
          if (el) {{
            el.style.opacity = '0';
            setTimeout(() => el.remove(), 300);
          }}
        }} else {{
          alert('Failed to delete: ' + (data.error || 'Unknown error'));
        }}
      }} catch (err) {{
        alert('Error: ' + err.message);
      }}
    }}
  </script>
</body>
</html>
"""
        encoded = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
def html_escape(text):
    if text is None:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def run():
    parser = argparse.ArgumentParser(description="Madhanraj Portfolio HTTP Server with Backend API")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default 8080)")
    args = parser.parse_args()

    init_db()
    server_address = ("", args.port)
    httpd = ThreadingHTTPServer(server_address, PortfolioRequestHandler)
    print(f"=====================================================")
    print(f" MADHANRAJ PORTFOLIO BACKEND SERVER RUNNING")
    print(f" Web Root:      http://localhost:{args.port}/")
    print(f" Contact API:   http://localhost:{args.port}/api/contact (POST)")
    print(f" Messages API:  http://localhost:{args.port}/api/messages (GET)")
    print(f" Admin Inbox:   http://localhost:{args.port}/admin")
    print(f" SQLite DB:     {DB_PATH}")
    print(f"=====================================================")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        httpd.server_close()


if __name__ == "__main__":
    run()
