# 🦡 AI Trade Badger

A full-stack live trading scanner combining deterministic signal math with Claude AI evaluation.

---

## Stack

| Layer | Tech |
|---|---|
| Frontend | Single HTML file — no build, no npm |
| Backend | Flask + KiteConnect on Render.com |
| AI | Claude Sonnet via Anthropic API (browser-side) |
| Storage | LocalStorage (learning log) |

---

## Markets Covered

- **NSE Equity** — Nifty 50 stocks, real 5-min candles (ORB + ATR + VWAP + Supertrend)
- **Index F&O** — NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY (PCR + OI + IV signals)
- **MCX Options** — Gold, Silver, CrudeOil, NaturalGas (PCR + OI analysis)
- **Stock F&O** — Top 10 NSE F&O stocks

---

## Backend Deployment (Render.com)

### Step 1: Create a new Web Service on Render

1. Push `app.py`, `requirements.txt`, and `render.yaml` to a GitHub repo
2. Go to https://render.com → New → Web Service
3. Connect your GitHub repo
4. Render will auto-detect `render.yaml`

### Step 2: Set Environment Variables on Render

In your Render service dashboard → Environment:

| Variable | Value |
|---|---|
| `KITE_API_KEY` | Your Zerodha API key |
| `KITE_API_SECRET` | Your Zerodha API secret |
| `KITE_ACCESS_TOKEN` | Daily access token (update each morning) |

> **Note:** The access token expires daily. You'll need to update it each morning via the Render dashboard or automate it with a script.

### Step 3: Get your backend URL

Once deployed, Render gives you a URL like:
`https://ai-trade-badger-backend.onrender.com`

---

## Frontend Setup

1. Open `AITradeBadger.html` in any browser (file://, GitHub Pages, Netlify — anything)
2. Click **⚙ SETTINGS** in the top right
3. Fill in:
   - **Backend URL**: your Render URL
   - **Anthropic API Key**: from console.anthropic.com
   - **Kite Access Token**: from Kite Developer Console (daily)
4. Hit **SAVE**

---

## Daily Workflow

1. **Morning**: Update `KITE_ACCESS_TOKEN` in Render env vars
2. **Open** AITradeBadger.html
3. Click **☀ BRIEF** for the AI pre-market risk assessment
4. Click **▶ SCAN ALL** to run the full scan
5. Review signal cards — AI evaluations auto-load if Anthropic key is set
6. Click **+ LOG TRADE** on signals you take
7. After trade closes: go to **POSITIONS** tab → mark Win / Loss / Scratch
8. Check **LEARNING** tab to see your per-symbol win rates grow over time

---

## Kite API Setup

1. Go to https://developers.kite.trade
2. Create an app → get API Key + API Secret
3. Each morning, log in via `https://kite.zerodha.com/connect/login?api_key=YOUR_KEY`
4. After login, Kite redirects with `?request_token=xxx`
5. POST to your backend `/auth/token` with `{ request_token: "xxx" }` to get the access token
6. Paste the access token into AITradeBadger Settings

---

## Signal Logic

### NSE Equity (Real Candles)
- **ORB Breakout**: Price > Opening Range High (first 6 x 5-min candles)
- **VWAP**: Price relative to session VWAP
- **Supertrend(10,3)**: Direction confirmation
- **EMA Cross**: 9 EMA vs 21 EMA
- **RSI Momentum**: RSI > 55 (bull) or < 45 (bear)
- Signal fires at 2+ factors aligned

### Index/Stock F&O
- **PCR**: Put-Call Ratio > 1.2 = bullish, < 0.8 = bearish
- **OI Analysis**: Call wall position, Put support level
- **IV Gate**: Low IV = take premium sells; High IV = buy premium cautiously
- Signal fires at 2+ factors aligned

### MCX Options
- **PCR**: Similar to F&O
- **IV Gate**: Commodity-adjusted thresholds
- **OI Skew**: Put OI vs Call OI imbalance

---

## AI Evaluation

Each signal card gets evaluated by Claude with:
- Full signal data (symbol, direction, factors, IV, PCR, entry/stop/target)
- Recent trade history for that symbol (from Learning log)
- Current time, day of week, days to expiry
- Claude returns: **TAKE / SKIP / REDUCE_SIZE** + confidence + reasoning + risk flags

---

## File Structure

```
ai-trade-badger/
├── app.py              ← Flask backend (deploy to Render)
├── requirements.txt    ← Python dependencies
├── render.yaml         ← One-click Render deployment config
├── AITradeBadger.html  ← Frontend (open in any browser)
└── README.md
```
