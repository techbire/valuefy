#!/usr/bin/env python3
"""
Minimal HTTP server for Portfolio Rebalancer
No external dependencies — stdlib only (http.server + sqlite3 + json)
"""

import sqlite3, json, re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import os
import shutil
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get('DB_PATH', str(BASE_DIR / 'model_portfolio.db'))
INDEX_PATH = str(BASE_DIR / 'index.html')
DEFAULT_DB_PATH = BASE_DIR / 'model_portfolio.db'

def ensure_database_file():
    db_file = Path(DB_PATH)
    if db_file.exists():
        return

    if db_file.parent and not db_file.parent.exists():
        db_file.parent.mkdir(parents=True, exist_ok=True)

    if DEFAULT_DB_PATH.exists() and db_file.resolve() != DEFAULT_DB_PATH.resolve():
        shutil.copy2(DEFAULT_DB_PATH, db_file)

def get_db():
    ensure_database_file()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def rows_to_list(rows):
    return [dict(r) for r in rows]

# ─────────── API HANDLERS ───────────

def api_clients():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM clients ORDER BY client_name").fetchall()
    return rows_to_list(rows)

def api_model_funds():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM model_funds ORDER BY fund_id").fetchall()
    return rows_to_list(rows)

def api_holdings(client_id):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM client_holdings WHERE client_id = ? ORDER BY fund_id",
            (client_id,)
        ).fetchall()
    return rows_to_list(rows)

def api_rebalance(client_id):
    """Calculate rebalancing for a given client."""
    with get_db() as conn:
        holdings = rows_to_list(conn.execute(
            "SELECT * FROM client_holdings WHERE client_id = ?", (client_id,)
        ).fetchall())
        model_funds = rows_to_list(conn.execute(
            "SELECT * FROM model_funds ORDER BY fund_id"
        ).fetchall())

    model_map = {f['fund_id']: f for f in model_funds}
    model_ids = set(model_map.keys())
    total_value = sum(h['current_value'] for h in holdings)

    rows = []

    # Plan funds first
    for mf in model_funds:
        holding = next((h for h in holdings if h['fund_id'] == mf['fund_id']), None)
        current_val = holding['current_value'] if holding else 0.0
        current_pct = (current_val / total_value * 100) if total_value > 0 else 0.0
        target_pct = mf['allocation_pct']
        drift = target_pct - current_pct
        amount = abs(drift / 100 * total_value)

        if abs(drift) < 0.01:
            action = 'HOLD'
        elif drift > 0:
            action = 'BUY'
        else:
            action = 'SELL'

        rows.append({
            'fund_id': mf['fund_id'],
            'fund_name': mf['fund_name'],
            'asset_class': mf['asset_class'],
            'is_model_fund': True,
            'current_value': current_val,
            'current_pct': round(current_pct, 4),
            'target_pct': target_pct,
            'drift': round(drift, 4),
            'action': action,
            'amount': round(amount),
            'post_rebalance_pct': target_pct
        })

    # Non-plan funds
    for h in holdings:
        if h['fund_id'] not in model_ids:
            current_pct = (h['current_value'] / total_value * 100) if total_value > 0 else 0.0
            rows.append({
                'fund_id': h['fund_id'],
                'fund_name': h['fund_name'],
                'asset_class': 'EXTERNAL',
                'is_model_fund': False,
                'current_value': h['current_value'],
                'current_pct': round(current_pct, 4),
                'target_pct': None,
                'drift': None,
                'action': 'REVIEW',
                'amount': round(h['current_value']),
                'post_rebalance_pct': None
            })

    total_buy  = sum(r['amount'] for r in rows if r['action'] == 'BUY')
    total_sell = sum(r['amount'] for r in rows if r['action'] == 'SELL')

    return {
        'client_id': client_id,
        'total_value': total_value,
        'total_buy': total_buy,
        'total_sell': total_sell,
        'cash_needed': total_buy - total_sell,
        'rows': rows
    }

def api_save_rebalance(body):
    client_id = body['client_id']
    calc = api_rebalance(client_id)
    now = datetime.now().isoformat(sep=' ', timespec='seconds')

    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO rebalance_sessions
               (client_id, created_at, portfolio_value, total_to_buy, total_to_sell, net_cash_needed, status)
               VALUES (?, ?, ?, ?, ?, ?, 'PENDING')""",
            (client_id, now, calc['total_value'], calc['total_buy'],
             calc['total_sell'], calc['cash_needed'])
        )
        session_id = cur.lastrowid

        for r in calc['rows']:
            if r['action'] == 'HOLD':
                continue  # don't log hold items
            conn.execute(
                """INSERT INTO rebalance_items
                   (session_id, fund_id, fund_name, action, amount,
                    current_pct, target_pct, post_rebalance_pct, is_model_fund)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, r['fund_id'], r['fund_name'], r['action'],
                 r['amount'], r['current_pct'], r['target_pct'],
                 r['post_rebalance_pct'], 1 if r['is_model_fund'] else 0)
            )
        conn.commit()

    return {'session_id': session_id, 'status': 'PENDING'}

def api_sessions(client_id):
    with get_db() as conn:
        sessions = rows_to_list(conn.execute(
            "SELECT * FROM rebalance_sessions WHERE client_id = ? ORDER BY created_at DESC",
            (client_id,)
        ).fetchall())
        for s in sessions:
            s['items'] = rows_to_list(conn.execute(
                "SELECT * FROM rebalance_items WHERE session_id = ? ORDER BY item_id",
                (s['session_id'],)
            ).fetchall())
    return sessions

def api_update_session(body):
    session_id = body['session_id']
    status = body['status']
    if status not in ('PENDING', 'APPLIED', 'DISMISSED'):
        return {'error': 'Invalid status'}
    with get_db() as conn:
        conn.execute("UPDATE rebalance_sessions SET status=? WHERE session_id=?",
                     (status, session_id))
        conn.commit()
    return {'ok': True}

def api_update_plan(body):
    funds = body['funds']  # [{fund_id, allocation_pct}, ...]
    total = sum(f['allocation_pct'] for f in funds)
    if abs(total - 100) > 0.01:
        return {'error': f'Allocations must sum to 100 (got {total:.2f})'}
    with get_db() as conn:
        for f in funds:
            conn.execute("UPDATE model_funds SET allocation_pct=? WHERE fund_id=?",
                         (f['allocation_pct'], f['fund_id']))
        conn.commit()
    return {'ok': True}

# ─────────── HTTP HANDLER ───────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress default logging

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, ctype='text/html'):
        with open(path, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        try:
            if path == '/' or path == '/index.html':
                self.send_file(INDEX_PATH)
            elif path == '/api/clients':
                self.send_json(api_clients())
            elif path == '/api/model_funds':
                self.send_json(api_model_funds())
            elif path == '/api/holdings':
                client_id = qs.get('client_id', ['C001'])[0]
                self.send_json(api_holdings(client_id))
            elif path == '/api/rebalance':
                client_id = qs.get('client_id', ['C001'])[0]
                self.send_json(api_rebalance(client_id))
            elif path == '/api/sessions':
                client_id = qs.get('client_id', ['C001'])[0]
                self.send_json(api_sessions(client_id))
            else:
                self.send_json({'error': 'Not found'}, 404)
        except Exception as e:
            self.send_json({'error': str(e)}, 500)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        path = urlparse(self.path).path

        try:
            if path == '/api/save_rebalance':
                self.send_json(api_save_rebalance(body))
            elif path == '/api/update_session':
                self.send_json(api_update_session(body))
            elif path == '/api/update_plan':
                self.send_json(api_update_plan(body))
            else:
                self.send_json({'error': 'Not found'}, 404)
        except Exception as e:
            self.send_json({'error': str(e)}, 500)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8765'))
    server = HTTPServer(('0.0.0.0', port), Handler)
    print(f'Server running on http://localhost:{port}')
    server.serve_forever()
