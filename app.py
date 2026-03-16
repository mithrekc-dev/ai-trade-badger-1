"""
AI Trade Badger — Flask Backend v2
"""
from flask import Flask, jsonify, request
from flask_cors import CORS
import os, datetime, traceback

app = Flask(__name__)
CORS(app, origins="*")

@app.after_request
def cors_fix(response):
    origin = request.headers.get("Origin", "*")
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Kite-Token"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

# Lazy kite import
KiteConnect = None
KITE_AVAILABLE = False
try:
    from kiteconnect import KiteConnect as _KC
    KiteConnect = _KC
    KITE_AVAILABLE = True
except Exception:
    pass

def get_kite():
    if not KITE_AVAILABLE:
        raise RuntimeError("kiteconnect not installed")
    api_key = os.environ.get("KITE_API_KEY", "")
    token = request.headers.get("X-Kite-Token") or os.environ.get("KITE_ACCESS_TOKEN", "")
    if not api_key:
        raise RuntimeError("KITE_API_KEY not set")
    if not token:
        raise RuntimeError("KITE_ACCESS_TOKEN not set")
    k = KiteConnect(api_key=api_key)
    k.set_access_token(token)
    return k

def err(msg, code=500):
    return jsonify({"error": str(msg)}), code

@app.route("/health")
def health():
    return jsonify({"status": "ok", "ts": datetime.datetime.utcnow().isoformat()})

@app.route("/")
def index():
    return jsonify({
        "app": "AI Trade Badger",
        "status": "online",
        "kite_available": KITE_AVAILABLE,
        "api_key_set": bool(os.environ.get("KITE_API_KEY")),
        "token_set": bool(os.environ.get("KITE_ACCESS_TOKEN")),
    })

@app.route("/session")
def session():
    try:
        k = get_kite()
        p = k.profile()
        return jsonify({"status": "active", "user": p.get("user_name", "")})
    except Exception as e:
        return jsonify({"status": "expired", "error": str(e)}), 401

@app.route("/quotes", methods=["POST"])
def quotes():
    data = request.get_json() or {}
    instruments = data.get("instruments", [])
    if not instruments:
        return err("instruments required", 400)
    try:
        k = get_kite()
        result = {}
        for i in range(0, len(instruments), 500):
            result.update(k.quote(instruments[i:i+500]))
        return jsonify(result)
    except Exception as e:
        return err(e)

@app.route("/candles", methods=["POST"])
def candles():
    data = request.get_json() or {}
    token = data.get("instrument_token")
    interval = data.get("interval", "5minute")
    from_dt = data.get("from")
    to_dt = data.get("to")
    if not all([token, from_dt, to_dt]):
        return err("instrument_token, from, to required", 400)
    try:
        k = get_kite()
        result = k.historical_data(
            instrument_token=int(token),
            from_date=from_dt, to_date=to_dt,
            interval=interval, continuous=False
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

@app.route("/optionchain", methods=["POST"])
def option_chain():
    data = request.get_json() or {}
    symbol = data.get("symbol", "NIFTY").upper()
    expiry = data.get("expiry")
    try:
        k = get_kite()
        insts = k.instruments("NFO")
        today = str(datetime.date.today())
        chain = [i for i in insts if i["name"] == symbol]
        if not chain:
            return err(f"No NFO instruments for {symbol}", 404)
        if not expiry:
            expiries = sorted(set(str(i["expiry"]) for i in chain if str(i["expiry"]) >= today))
            expiry = expiries[0] if expiries else None
        if expiry:
            chain = [i for i in chain if str(i["expiry"]) == expiry]
        tokens = [f"NFO:{i['tradingsymbol']}" for i in chain[:200]]
        quotes_data = {}
        for i in range(0, len(tokens), 500):
            try:
                quotes_data.update(k.quote(tokens[i:i+500]))
            except Exception as qe:
                print(f"Quote batch error: {qe}")
        calls, puts = [], []
        for inst in chain:
            ts = f"NFO:{inst['tradingsymbol']}"
            q = quotes_data.get(ts, {})
            entry = {
                "tradingsymbol": inst["tradingsymbol"],
                "strike": inst["strike"],
                "expiry": str(inst["expiry"]),
                "instrument_token": inst["instrument_token"],
                "lot_size": inst["lot_size"],
                "ltp": q.get("last_price", 0),
                "oi": q.get("oi", 0),
                "volume": q.get("volume", 0),
            }
            if inst["instrument_type"] == "CE":
                calls.append(entry)
            else:
                puts.append(entry)
        total_call_oi = sum(c["oi"] for c in calls) or 1
        total_put_oi = sum(p["oi"] for p in puts)
        pcr = round(total_put_oi / total_call_oi, 3)
        SPOT_MAP = {
            "NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK",
            "FINNIFTY": "NSE:NIFTY FIN SERVICE", "MIDCPNIFTY": "NSE:NIFTY MIDCAP SELECT",
        }
        spot = 0
        try:
            spot_sym = SPOT_MAP.get(symbol, f"NSE:{symbol}")
            sq = k.quote([spot_sym])
            spot = sq[spot_sym]["last_price"]
        except Exception as se:
            print(f"Spot error {symbol}: {se}")
        return jsonify({
            "symbol": symbol, "expiry": expiry, "spot": spot,
            "pcr": pcr, "calls": sorted(calls, key=lambda x: x["strike"]),
            "puts": sorted(puts, key=lambda x: x["strike"]),
        })
    except Exception as e:
        traceback.print_exc()
        return err(e)

@app.route("/mcx/optionchain", methods=["POST"])
def mcx_option_chain():
    data = request.get_json() or {}
    symbol = data.get("symbol", "GOLD").upper()
    try:
        k = get_kite()
        insts = k.instruments("MCX")
        today = str(datetime.date.today())
        options = [i for i in insts if i["name"] == symbol and i["instrument_type"] in ("CE", "PE")]
        if not options:
            return err(f"No MCX options for {symbol}", 404)
        expiries = sorted(set(str(i["expiry"]) for i in options if str(i["expiry"]) >= today))
        nearest = expiries[0] if expiries else None
        if nearest:
            options = [i for i in options if str(i["expiry"]) == nearest]
        tokens = [f"MCX:{i['tradingsymbol']}" for i in options[:200]]
        quotes_data = {}
        for i in range(0, len(tokens), 500):
            try:
                quotes_data.update(k.quote(tokens[i:i+500]))
            except Exception as qe:
                print(f"MCX quote error: {qe}")
        fut = sorted([i for i in insts if i["name"] == symbol and i["instrument_type"] == "FUT"], key=lambda x: x["expiry"])
        spot = 0
        if fut:
            try:
                sq = k.quote([f"MCX:{fut[0]['tradingsymbol']}"])
                spot = sq[f"MCX:{fut[0]['tradingsymbol']}"]["last_price"]
            except Exception as se:
                print(f"MCX spot error: {se}")
        calls, puts = [], []
        for inst in options:
            ts = f"MCX:{inst['tradingsymbol']}"
            q = quotes_data.get(ts, {})
            entry = {
                "tradingsymbol": inst["tradingsymbol"],
                "strike": inst["strike"],
                "expiry": str(inst["expiry"]),
                "instrument_token": inst["instrument_token"],
                "lot_size": inst["lot_size"],
                "ltp": q.get("last_price", 0),
                "oi": q.get("oi", 0),
                "volume": q.get("volume", 0),
            }
            if inst["instrument_type"] == "CE":
                calls.append(entry)
            else:
                puts.append(entry)
        total_call_oi = sum(c["oi"] for c in calls) or 1
        total_put_oi = sum(p["oi"] for p in puts)
        pcr = round(total_put_oi / total_call_oi, 3)
        return jsonify({
            "symbol": symbol, "spot": spot, "expiry": nearest,
            "pcr": pcr, "calls": sorted(calls, key=lambda x: x["strike"]),
            "puts": sorted(puts, key=lambda x: x["strike"]),
        })
    except Exception as e:
        traceback.print_exc()
        return err(e)

@app.route("/auth/login_url")
def login_url():
    api_key = os.environ.get("KITE_API_KEY", "")
    if not api_key:
        return err("KITE_API_KEY not set", 400)
    try:
        k = KiteConnect(api_key=api_key)
        return jsonify({"login_url": k.login_url()})
    except Exception as e:
        return err(e)

@app.route("/auth/token", methods=["POST"])
def generate_token():
    data = request.get_json() or {}
    request_token = data.get("request_token")
    if not request_token:
        return err("request_token required", 400)
    try:
        k = KiteConnect(api_key=os.environ.get("KITE_API_KEY", ""))
        session = k.generate_session(request_token, api_secret=os.environ.get("KITE_API_SECRET", ""))
        return jsonify({"access_token": session["access_token"], "user": session.get("user_name", "")})
    except Exception as e:
        return err(e)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
