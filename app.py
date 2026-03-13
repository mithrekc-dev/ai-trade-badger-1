"""
AI Trade Badger — Flask Backend
Deploy on Render.com as a Python web service.
Requirements: flask, flask-cors, requests, kiteconnect
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
from kiteconnect import KiteConnect
import requests as req
import os, json, datetime, traceback

app = Flask(__name__)
CORS(app, origins="*")

# ── Config ────────────────────────────────────────────────────────────────────
KITE_API_KEY    = os.environ.get("KITE_API_KEY", "")
KITE_API_SECRET = os.environ.get("KITE_API_SECRET", "")
ACCESS_TOKEN    = os.environ.get("KITE_ACCESS_TOKEN", "")

def get_kite():
    kite = KiteConnect(api_key=KITE_API_KEY)
    kite.set_access_token(ACCESS_TOKEN)
    return kite

# ── Auth ──────────────────────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def index():
    return jsonify({"app": "AI Trade Badger", "status": "online", "version": "1.0"})

@app.route("/auth/login_url", methods=["GET"])
def login_url():
    """Return Kite login URL for OAuth flow."""
    kite = KiteConnect(api_key=KITE_API_KEY)
    return jsonify({"login_url": kite.login_url()})

@app.route("/auth/token", methods=["POST"])
def generate_token():
    """Exchange request_token for access_token."""
    data = request.get_json()
    request_token = data.get("request_token")
    if not request_token:
        return jsonify({"error": "request_token required"}), 400
    try:
        kite = KiteConnect(api_key=KITE_API_KEY)
        session = kite.generate_session(request_token, api_secret=KITE_API_SECRET)
        token = session["access_token"]
        # In production, store this securely; for now return it
        return jsonify({"access_token": token, "user": session.get("user_name","")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/session", methods=["GET"])
def session_status():
    """Check if current access token is valid."""
    try:
        kite = get_kite()
        profile = kite.profile()
        return jsonify({"status": "active", "user": profile.get("user_name",""), "email": profile.get("email","")})
    except Exception as e:
        return jsonify({"status": "expired", "error": str(e)}), 401

# ── Market Data ───────────────────────────────────────────────────────────────
@app.route("/quotes", methods=["POST"])
def quotes():
    """
    Body: { "instruments": ["NSE:RELIANCE", "NSE:TCS", ...] }
    Returns LTP, OHLC, volume, OI for each instrument.
    """
    data = request.get_json()
    instruments = data.get("instruments", [])
    if not instruments:
        return jsonify({"error": "instruments list required"}), 400
    # Kite accepts max 500 per call
    batches = [instruments[i:i+500] for i in range(0, len(instruments), 500)]
    result = {}
    kite = get_kite()
    for batch in batches:
        try:
            q = kite.quote(batch)
            result.update(q)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify(result)

@app.route("/candles", methods=["POST"])
def candles():
    """
    Body: {
        "instrument_token": 256265,
        "interval": "5minute",
        "from": "2025-01-01 09:15:00",
        "to":   "2025-01-01 15:30:00"
    }
    Returns OHLCV candle array.
    """
    data = request.get_json()
    token    = data.get("instrument_token")
    interval = data.get("interval", "5minute")
    from_dt  = data.get("from")
    to_dt    = data.get("to")
    if not all([token, from_dt, to_dt]):
        return jsonify({"error": "instrument_token, from, to required"}), 400
    try:
        kite = get_kite()
        candles = kite.historical_data(
            instrument_token=int(token),
            from_date=from_dt,
            to_date=to_dt,
            interval=interval,
            continuous=False
        )
        return jsonify({"candles": candles})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/optionchain", methods=["POST"])
def option_chain():
    """
    Body: { "symbol": "NIFTY", "expiry": "2025-01-30" }
    Returns full option chain with OI, IV, PCR.
    """
    data = request.get_json()
    symbol = data.get("symbol", "NIFTY").upper()
    expiry = data.get("expiry")  # YYYY-MM-DD format

    try:
        kite = get_kite()
        # Fetch NSF instruments list for the symbol
        instruments = kite.instruments("NFO")
        # Filter by symbol and expiry
        chain = []
        for inst in instruments:
            if inst["name"] == symbol:
                if expiry and str(inst["expiry"]) != expiry:
                    continue
                chain.append(inst)
        if not chain:
            return jsonify({"error": f"No instruments found for {symbol}"}), 404

        # Get quotes for all strikes
        tokens = [f"NFO:{inst['tradingsymbol']}" for inst in chain[:200]]
        quotes_data = {}
        if tokens:
            for i in range(0, len(tokens), 500):
                batch = tokens[i:i+500]
                q = kite.quote(batch)
                quotes_data.update(q)

        # Build chain response
        calls, puts = [], []
        for inst in chain:
            ts = f"NFO:{inst['tradingsymbol']}"
            q = quotes_data.get(ts, {})
            ohlc = q.get("ohlc", {})
            entry = {
                "tradingsymbol": inst["tradingsymbol"],
                "strike": inst["strike"],
                "expiry": str(inst["expiry"]),
                "instrument_token": inst["instrument_token"],
                "lot_size": inst["lot_size"],
                "ltp": q.get("last_price", 0),
                "open": ohlc.get("open", 0),
                "high": ohlc.get("high", 0),
                "low": ohlc.get("low", 0),
                "close": ohlc.get("close", 0),
                "oi": q.get("oi", 0),
                "oi_day_high": q.get("oi_day_high", 0),
                "volume": q.get("volume", 0),
                "bid": q.get("depth", {}).get("buy", [{}])[0].get("price", 0) if q.get("depth") else 0,
                "ask": q.get("depth", {}).get("sell", [{}])[0].get("price", 0) if q.get("depth") else 0,
            }
            if inst["instrument_type"] == "CE":
                calls.append(entry)
            else:
                puts.append(entry)

        # Compute PCR
        total_call_oi = sum(c["oi"] for c in calls)
        total_put_oi  = sum(p["oi"] for p in puts)
        pcr = round(total_put_oi / total_call_oi, 3) if total_call_oi > 0 else 0

        # Spot price
        spot_map = {"NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK",
                    "FINNIFTY": "NSE:NIFTY FIN SERVICE", "MIDCPNIFTY": "NSE:NIFTY MIDCAP SELECT"}
        spot_symbol = spot_map.get(symbol)
        spot = 0
        if spot_symbol:
            try:
                sq = kite.quote([spot_symbol])
                spot = sq[spot_symbol]["last_price"]
            except:
                pass

        return jsonify({
            "symbol": symbol,
            "expiry": expiry,
            "spot": spot,
            "pcr": pcr,
            "total_call_oi": total_call_oi,
            "total_put_oi": total_put_oi,
            "calls": sorted(calls, key=lambda x: x["strike"]),
            "puts": sorted(puts, key=lambda x: x["strike"])
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/mcx/optionchain", methods=["POST"])
def mcx_option_chain():
    """
    Body: { "symbol": "GOLD" }
    Returns MCX options chain with spot price.
    """
    data = request.get_json()
    symbol = data.get("symbol", "GOLD").upper()
    # MCX spot instrument tokens
    MCX_SPOT_MAP = {
        "GOLD":    {"exchange": "MCX", "search": "GOLD"},
        "SILVER":  {"exchange": "MCX", "search": "SILVER"},
        "CRUDEOIL":{"exchange": "MCX", "search": "CRUDEOIL"},
        "NATURALGAS":{"exchange":"MCX", "search": "NATURALGAS"},
    }
    try:
        kite = get_kite()
        instruments = kite.instruments("MCX")
        options = [i for i in instruments if i["name"] == symbol and i["instrument_type"] in ("CE","PE")]
        if not options:
            return jsonify({"error": f"No MCX options found for {symbol}"}), 404

        # Get nearest expiry options only
        expiries = sorted(set(str(i["expiry"]) for i in options))
        nearest = expiries[0] if expiries else None
        options = [i for i in options if str(i["expiry"]) == nearest]

        tokens = [f"MCX:{i['tradingsymbol']}" for i in options[:200]]
        quotes_data = {}
        for i in range(0, len(tokens), 500):
            q = kite.quote(tokens[i:i+500])
            quotes_data.update(q)

        # Spot price — find continuous/active futures
        fut = [i for i in instruments if i["name"] == symbol and i["instrument_type"] == "FUT"]
        spot = 0
        if fut:
            fut_sorted = sorted(fut, key=lambda x: x["expiry"])
            spot_ts = f"MCX:{fut_sorted[0]['tradingsymbol']}"
            try:
                sq = kite.quote([spot_ts])
                spot = sq[spot_ts]["last_price"]
            except:
                pass

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

        total_call_oi = sum(c["oi"] for c in calls)
        total_put_oi  = sum(p["oi"] for p in puts)
        pcr = round(total_put_oi / total_call_oi, 3) if total_call_oi > 0 else 0

        return jsonify({
            "symbol": symbol, "spot": spot, "expiry": nearest,
            "pcr": pcr, "total_call_oi": total_call_oi, "total_put_oi": total_put_oi,
            "calls": sorted(calls, key=lambda x: x["strike"]),
            "puts": sorted(puts, key=lambda x: x["strike"])
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/instruments", methods=["GET"])
def instruments():
    """Return instrument list. exchange param: NSE, NFO, MCX"""
    exchange = request.args.get("exchange", "NSE")
    try:
        kite = get_kite()
        data = kite.instruments(exchange)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/expiries", methods=["GET"])
def expiries():
    """
    Return next N expiry dates for a symbol.
    ?symbol=NIFTY&exchange=NFO&n=4
    """
    symbol   = request.args.get("symbol", "NIFTY").upper()
    exchange = request.args.get("exchange", "NFO")
    n        = int(request.args.get("n", 4))
    try:
        kite = get_kite()
        instruments = kite.instruments(exchange)
        today = datetime.date.today()
        exp_set = sorted(set(
            str(i["expiry"]) for i in instruments
            if i["name"] == symbol and str(i["expiry"]) >= str(today)
        ))
        return jsonify({"symbol": symbol, "expiries": exp_set[:n]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Health check ──────────────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "ts": datetime.datetime.utcnow().isoformat()})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
