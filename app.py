"""
AI Trade Badger — Flask Backend
Railway / Render compatible.
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import os, datetime, traceback

app = Flask(__name__)
# Allow requests from local HTML files (file:// = null origin) and all web origins
CORS(app, origins="*", allow_headers=["Content-Type", "X-Kite-Token"],
     supports_credentials=False)

@app.after_request
def add_cors(response):
    # file:// pages send Origin: null — must explicitly allow it
    origin = request.headers.get("Origin", "")
    response.headers["Access-Control-Allow-Origin"] = origin if origin else "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Kite-Token"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response



# ── Lazy Kite import ──────────────────────────────────────────────────────────
try:
    from kiteconnect import KiteConnect
    KITE_AVAILABLE = True
except ImportError:
    KITE_AVAILABLE = False
    print("WARNING: kiteconnect not installed")

# ── Config read per-request ───────────────────────────────────────────────────
def get_cfg():
    return {
        "api_key":      os.environ.get("KITE_API_KEY", ""),
        "api_secret":   os.environ.get("KITE_API_SECRET", ""),
        "access_token": os.environ.get("KITE_ACCESS_TOKEN", ""),
    }

def get_kite():
    if not KITE_AVAILABLE:
        raise RuntimeError("kiteconnect library not installed")
    cfg = get_cfg()
    token = request.headers.get("X-Kite-Token") or cfg["access_token"]
    api_key = cfg["api_key"]
    if not api_key:
        raise RuntimeError("KITE_API_KEY not set in environment")
    if not token:
        raise RuntimeError("KITE_ACCESS_TOKEN not set — update it in Railway Variables")
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(token)
    return kite

def err(msg, code=500):
    print(f"ERROR: {msg}")
    return jsonify({"error": str(msg)}), code

# ── Health / Index ────────────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def index():
    cfg = get_cfg()
    return jsonify({
        "app": "AI Trade Badger",
        "status": "online",
        "version": "2.0",
        "kite_available": KITE_AVAILABLE,
        "api_key_set": bool(cfg["api_key"]),
        "token_set": bool(cfg["access_token"]),
    })

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "ts": datetime.datetime.utcnow().isoformat()})

# ── Auth ──────────────────────────────────────────────────────────────────────
@app.route("/auth/login_url", methods=["GET"])
def login_url():
    cfg = get_cfg()
    if not cfg["api_key"]:
        return err("KITE_API_KEY not set", 400)
    try:
        kite = KiteConnect(api_key=cfg["api_key"])
        return jsonify({"login_url": kite.login_url()})
    except Exception as e:
        return err(e)

@app.route("/auth/token", methods=["POST"])
def generate_token():
    data = request.get_json() or {}
    request_token = data.get("request_token")
    if not request_token:
        return err("request_token required", 400)
    cfg = get_cfg()
    try:
        kite = KiteConnect(api_key=cfg["api_key"])
        session = kite.generate_session(request_token, api_secret=cfg["api_secret"])
        token = session["access_token"]
        return jsonify({
            "access_token": token,
            "user": session.get("user_name", ""),
            "note": "Paste this token into Railway Variables as KITE_ACCESS_TOKEN"
        })
    except Exception as e:
        return err(e)

@app.route("/session", methods=["GET"])
def session_status():
    try:
        kite = get_kite()
        profile = kite.profile()
        return jsonify({
            "status": "active",
            "user": profile.get("user_name", ""),
            "email": profile.get("email", "")
        })
    except Exception as e:
        return jsonify({"status": "expired", "error": str(e)}), 401

# ── Quotes ────────────────────────────────────────────────────────────────────
@app.route("/quotes", methods=["POST"])
def quotes():
    data = request.get_json() or {}
    instruments = data.get("instruments", [])
    if not instruments:
        return err("instruments list required", 400)
    try:
        kite = get_kite()
        result = {}
        for i in range(0, len(instruments), 500):
            q = kite.quote(instruments[i:i+500])
            result.update(q)
        return jsonify(result)
    except Exception as e:
        return err(e)

# ── Candles ───────────────────────────────────────────────────────────────────
@app.route("/candles", methods=["POST"])
def candles():
    data     = request.get_json() or {}
    token    = data.get("instrument_token")
    interval = data.get("interval", "5minute")
    from_dt  = data.get("from")
    to_dt    = data.get("to")
    if not all([token, from_dt, to_dt]):
        return err("instrument_token, from, to required", 400)
    try:
        kite = get_kite()
        result = kite.historical_data(
            instrument_token=int(token),
            from_date=from_dt,
            to_date=to_dt,
            interval=interval,
            continuous=False
        )
        normalized = []
        for c in result:
            if isinstance(c, dict):
                normalized.append(c)
            else:
                normalized.append({
                    "date": str(c[0]), "open": c[1], "high": c[2],
                    "low": c[3], "close": c[4],
                    "volume": c[5] if len(c) > 5 else 0
                })
        return jsonify({"candles": normalized})
    except Exception as e:
        traceback.print_exc()
        return err(e)

# ── Option Chain NFO ──────────────────────────────────────────────────────────
@app.route("/optionchain", methods=["POST"])
def option_chain():
    data   = request.get_json() or {}
    symbol = data.get("symbol", "NIFTY").upper()
    expiry = data.get("expiry")
    try:
        kite  = get_kite()
        insts = kite.instruments("NFO")
        today = str(datetime.date.today())

        chain = [i for i in insts if i["name"] == symbol]
        if not chain:
            return err(f"No NFO instruments for {symbol}", 404)

        if not expiry:
            expiries = sorted(set(
                str(i["expiry"]) for i in chain if str(i["expiry"]) >= today
            ))
            expiry = expiries[0] if expiries else None

        if expiry:
            chain = [i for i in chain if str(i["expiry"]) == expiry]

        tokens = [f"NFO:{i['tradingsymbol']}" for i in chain[:200]]
        quotes_data = {}
        for i in range(0, len(tokens), 500):
            try:
                quotes_data.update(kite.quote(tokens[i:i+500]))
            except Exception as qe:
                print(f"Quote batch error: {qe}")

        calls, puts = [], []
        for inst in chain:
            ts   = f"NFO:{inst['tradingsymbol']}"
            q    = quotes_data.get(ts, {})
            ohlc = q.get("ohlc", {})
            entry = {
                "tradingsymbol":    inst["tradingsymbol"],
                "strike":           inst["strike"],
                "expiry":           str(inst["expiry"]),
                "instrument_token": inst["instrument_token"],
                "lot_size":         inst["lot_size"],
                "ltp":    q.get("last_price", 0),
                "open":   ohlc.get("open", 0),
                "high":   ohlc.get("high", 0),
                "low":    ohlc.get("low", 0),
                "close":  ohlc.get("close", 0),
                "oi":     q.get("oi", 0),
                "volume": q.get("volume", 0),
            }
            if inst["instrument_type"] == "CE":
                calls.append(entry)
            else:
                puts.append(entry)

        total_call_oi = sum(c["oi"] for c in calls) or 1
        total_put_oi  = sum(p["oi"] for p in puts)
        pcr = round(total_put_oi / total_call_oi, 3)

        SPOT_MAP = {
            "NIFTY":      "NSE:NIFTY 50",
            "BANKNIFTY":  "NSE:NIFTY BANK",
            "FINNIFTY":   "NSE:NIFTY FIN SERVICE",
            "MIDCPNIFTY": "NSE:NIFTY MIDCAP SELECT",
        }
        spot = 0
        spot_sym = SPOT_MAP.get(symbol, f"NSE:{symbol}")
        try:
            sq   = kite.quote([spot_sym])
            spot = sq[spot_sym]["last_price"]
        except Exception as se:
            print(f"Spot price error {symbol}: {se}")

        return jsonify({
            "symbol": symbol, "expiry": expiry, "spot": spot,
            "pcr": pcr, "total_call_oi": total_call_oi, "total_put_oi": total_put_oi,
            "calls": sorted(calls, key=lambda x: x["strike"]),
            "puts":  sorted(puts,  key=lambda x: x["strike"]),
        })
    except Exception as e:
        traceback.print_exc()
        return err(e)

# ── MCX Option Chain ──────────────────────────────────────────────────────────
@app.route("/mcx/optionchain", methods=["POST"])
def mcx_option_chain():
    data   = request.get_json() or {}
    symbol = data.get("symbol", "GOLD").upper()
    try:
        kite  = get_kite()
        insts = kite.instruments("MCX")
        today = str(datetime.date.today())

        options = [i for i in insts
                   if i["name"] == symbol and i["instrument_type"] in ("CE","PE")]
        if not options:
            return err(f"No MCX options for {symbol}", 404)

        expiries = sorted(set(
            str(i["expiry"]) for i in options if str(i["expiry"]) >= today
        ))
        nearest = expiries[0] if expiries else None
        if nearest:
            options = [i for i in options if str(i["expiry"]) == nearest]

        tokens = [f"MCX:{i['tradingsymbol']}" for i in options[:200]]
        quotes_data = {}
        for i in range(0, len(tokens), 500):
            try:
                quotes_data.update(kite.quote(tokens[i:i+500]))
            except Exception as qe:
                print(f"MCX quote error: {qe}")

        # Spot from nearest futures
        fut = sorted(
            [i for i in insts if i["name"] == symbol and i["instrument_type"] == "FUT"],
            key=lambda x: x["expiry"]
        )
        spot = 0
        if fut:
            try:
                sq   = kite.quote([f"MCX:{fut[0]['tradingsymbol']}"])
                spot = sq[f"MCX:{fut[0]['tradingsymbol']}"]["last_price"]
            except Exception as se:
                print(f"MCX spot error: {se}")

        calls, puts = [], []
        for inst in options:
            ts = f"MCX:{inst['tradingsymbol']}"
            q  = quotes_data.get(ts, {})
            entry = {
                "tradingsymbol":    inst["tradingsymbol"],
                "strike":           inst["strike"],
                "expiry":           str(inst["expiry"]),
                "instrument_token": inst["instrument_token"],
                "lot_size":         inst["lot_size"],
                "ltp":    q.get("last_price", 0),
                "oi":     q.get("oi", 0),
                "volume": q.get("volume", 0),
            }
            if inst["instrument_type"] == "CE":
                calls.append(entry)
            else:
                puts.append(entry)

        total_call_oi = sum(c["oi"] for c in calls) or 1
        total_put_oi  = sum(p["oi"] for p in puts)
        pcr = round(total_put_oi / total_call_oi, 3)

        return jsonify({
            "symbol": symbol, "spot": spot, "expiry": nearest,
            "pcr": pcr, "total_call_oi": total_call_oi, "total_put_oi": total_put_oi,
            "calls": sorted(calls, key=lambda x: x["strike"]),
            "puts":  sorted(puts,  key=lambda x: x["strike"]),
        })
    except Exception as e:
        traceback.print_exc()
        return err(e)

# ── Instruments / Expiries ────────────────────────────────────────────────────
@app.route("/instruments", methods=["GET"])
def instruments():
    exchange = request.args.get("exchange", "NSE")
    try:
        kite = get_kite()
        return jsonify(kite.instruments(exchange))
    except Exception as e:
        return err(e)

@app.route("/expiries", methods=["GET"])
def expiries():
    symbol   = request.args.get("symbol", "NIFTY").upper()
    exchange = request.args.get("exchange", "NFO")
    n        = int(request.args.get("n", 4))
    try:
        kite  = get_kite()
        insts = kite.instruments(exchange)
        today = str(datetime.date.today())
        exp_set = sorted(set(
            str(i["expiry"]) for i in insts
            if i["name"] == symbol and str(i["expiry"]) >= today
        ))
        return jsonify({"symbol": symbol, "expiries": exp_set[:n]})
    except Exception as e:
        return err(e)

# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"AI Trade Badger backend starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
port = int(os.environ.get("PORT", 5000))
app.run(host="0.0.0.0", port=port, debug=False)
```

The `app.run()` line only runs when executing directly with `python app.py` — gunicorn ignores it. So the port 8080 must be coming from somewhere else.

**Fastest fix right now** — in Railway → Variables, add:
```
PORT = 8080
