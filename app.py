
import math
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests
import streamlit as st

MEXC_BASE = "https://api.mexc.com"
TIMEOUT = 15

st.set_page_config(
    page_title="MEXC Breakout Radar v1.2",
    page_icon="🚀",
    layout="wide",
)

st.title("🚀 MEXC Breakout Radar")
st.caption(
    "Skaner kandydatów do przyszłych dużych wybić. "
    "Warstwa techniczna + market proxy + ręczna ocena tokenomii, produktu, zespołu i narracji. To filtr badawczy, nie rekomendacja."
)

# -----------------------------
# API helpers
# -----------------------------
@st.cache_data(ttl=300, show_spinner=False)
def mexc_exchange_info():
    r = requests.get(f"{MEXC_BASE}/api/v3/exchangeInfo", timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    symbols = data.get("symbols", data if isinstance(data, list) else [])
    return pd.DataFrame(symbols)

@st.cache_data(ttl=120, show_spinner=False)
def mexc_tickers():
    r = requests.get(f"{MEXC_BASE}/api/v3/ticker/24hr", timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return pd.DataFrame(data)

@st.cache_data(ttl=300, show_spinner=False)
def mexc_klines(symbol, start_ms, end_ms, interval="1d"):
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": int(start_ms),
        "endTime": int(end_ms),
        "limit": 1000,
    }
    r = requests.get(f"{MEXC_BASE}/api/v3/klines", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if not data:
        return pd.DataFrame(columns=["time","open","high","low","close","volume","quote_volume"])
    df = pd.DataFrame(
        data,
        columns=[
            "time","open","high","low","close","volume",
            "close_time","quote_volume","trades","taker_base",
            "taker_quote","ignore"
        ],
    )
    for c in ["open","high","low","close","volume","quote_volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    return df[["time","open","high","low","close","volume","quote_volume"]].dropna()


@st.cache_data(ttl=600, show_spinner=False)
def coingecko_markets_page(page=1, per_page=250):
    """Public CoinGecko endpoint. Useful for market cap/FDV enrichment."""
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": per_page,
        "page": page,
        "sparkline": "false",
    }
    r = requests.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return pd.DataFrame(r.json())

@st.cache_data(ttl=600, show_spinner=False)
def coingecko_search(query):
    url = "https://api.coingecko.com/api/v3/search"
    r = requests.get(url, params={"query": query}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=900, show_spinner=False)
def defillama_protocol(slug):
    """Fetch public DefiLlama protocol TVL/history metadata for a manually matched slug."""
    slug = str(slug or "").strip().lower()
    if not slug:
        return None
    r = requests.get(f"https://api.llama.fi/protocol/{slug}", timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict) or not data.get("name"):
        return None
    tvl = data.get("tvl") or []
    vals = [x.get("totalLiquidityUSD") for x in tvl if isinstance(x, dict) and x.get("totalLiquidityUSD") is not None]
    change_30d = np.nan
    if len(vals) >= 2:
        # Approximate 30-day comparison using latest available point and closest point 30d earlier.
        latest = float(vals[-1])
        target = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
        points = [x for x in tvl if isinstance(x, dict) and x.get("date") is not None and x.get("totalLiquidityUSD") is not None]
        if points:
            old = min(points, key=lambda x: abs(float(x["date"]) - target))
            old_v = float(old["totalLiquidityUSD"] or 0)
            if old_v > 0:
                change_30d = (latest / old_v - 1) * 100
    return {
        "name": data.get("name"),
        "category": data.get("category"),
        "chains": ", ".join(data.get("chains") or []),
        "url": data.get("url"),
        "tvl": float(vals[-1]) if vals else np.nan,
        "tvl_change_30d": change_30d,
        "listed_at": data.get("listedAt"),
        "description": data.get("description"),
    }

def cg_enrich_symbols(symbols):
    """
    Best-effort mapping of MEXC BASE symbols to CoinGecko.
    Returns market cap, FDV, circulating/max supply and CoinGecko rank.
    Symbol collisions are handled by preferring an exact symbol/name match.
    """
    try:
        pages = []
        for page in range(1, 5):
            d = coingecko_markets_page(page)
            if len(d):
                pages.append(d)
        if not pages:
            return pd.DataFrame()
        cg = pd.concat(pages, ignore_index=True)
        cg["symbol_upper"] = cg["symbol"].astype(str).str.upper()
        wanted = set(symbols)

        rows = []
        for sym in wanted:
            base = sym.replace("USDT", "").replace("USDC", "").upper()
            cand = cg[cg["symbol_upper"] == base].copy()
            if cand.empty:
                continue
            # Prefer exact token name/symbol; otherwise highest market cap.
            cand = cand.sort_values("market_cap", ascending=False)
            x = cand.iloc[0]
            rows.append({
                "symbol": sym,
                "cg_id": x.get("id"),
                "market_cap": x.get("market_cap"),
                "fdv": x.get("fully_diluted_valuation"),
                "circulating_supply": x.get("circulating_supply"),
                "max_supply": x.get("max_supply"),
                "cg_rank": x.get("market_cap_rank"),
                "cg_volume_24h": x.get("total_volume"),
            })
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()

def fundamental_score(row):
    """
    Market/fundamental proxy, not a claim about team quality.
    Score 0-25:
      - market cap opportunity
      - FDV dilution risk
      - liquidity/market maturity
      - CoinGecko coverage/rank
    """
    score = 0.0
    cap = row.get("market_cap", np.nan)
    fdv = row.get("fdv", np.nan)
    vol = row.get("cg_volume_24h", np.nan)

    # Sweet spot for asymmetric upside is usually small/mid cap,
    # but extremely tiny caps are penalized for fragility.
    if np.isfinite(cap):
        if 10e6 <= cap <= 100e6: score += 8
        elif 100e6 < cap <= 300e6: score += 6
        elif 300e6 < cap <= 1e9: score += 3
        elif cap < 10e6: score += 4
    # FDV / market cap: lower is better; huge dilution is penalized.
    if np.isfinite(cap) and cap > 0 and np.isfinite(fdv):
        ratio = fdv / cap
        if ratio <= 1.5: score += 6
        elif ratio <= 2.5: score += 4
        elif ratio <= 5: score += 2
        else: score -= 2
    # Liquidity relative to market cap.
    if np.isfinite(cap) and cap > 0 and np.isfinite(vol):
        vr = vol / cap
        if 0.05 <= vr <= 1.0: score += 5
        elif vr > 1.0: score += 3
        elif vr >= 0.01: score += 2
    # Ranking is only a small stabilizer.
    rank = row.get("cg_rank", np.nan)
    if np.isfinite(rank):
        if rank <= 500: score += 3
        elif rank <= 1500: score += 2
        else: score += 1
    return float(max(0, min(25, score)))

def fmt_money(x):
    if x is None or not np.isfinite(x):
        return "—"
    x = float(x)
    if abs(x) >= 1e9: return f"${x/1e9:.2f}B"
    if abs(x) >= 1e6: return f"${x/1e6:.2f}M"
    if abs(x) >= 1e3: return f"${x/1e3:.1f}K"
    return f"${x:.2f}"

def pct(x):
    if x is None or not np.isfinite(x):
        return "—"
    return f"{x:.1f}%"

# -----------------------------
# Analysis engine
# -----------------------------
def linear_slope(values):
    y = np.asarray(values, dtype=float)
    if len(y) < 3:
        return np.nan
    x = np.arange(len(y), dtype=float)
    return np.polyfit(x, y, 1)[0]

def analyze_symbol(symbol, days=49):
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days + 2)
    df = mexc_klines(
        symbol,
        int(start.timestamp()*1000),
        int(now.timestamp()*1000),
        "1d",
    )
    if len(df) < 30:
        return None, df

    # Remove today's incomplete candle for fair historical comparisons.
    today = pd.Timestamp.now(tz="UTC").normalize()
    closed = df[df["time"] < today].copy()
    if len(closed) < 30:
        closed = df.copy()

    last = closed.iloc[-1]
    price = float(last.close)

    # 7-week window = 49 closed daily candles.
    w = closed.tail(days).copy()
    if len(w) < 30:
        return None, closed

    prior7 = w.iloc[:-7] if len(w) > 14 else w
    recent7 = w.tail(7)

    avg_prior7_vol = prior7["quote_volume"].mean()
    recent7_vol = recent7["quote_volume"].mean()
    vol_ratio = recent7_vol / avg_prior7_vol if avg_prior7_vol > 0 else np.nan

    # Latest 24h quote volume from the last closed daily candle.
    vol_24h_closed = float(last.quote_volume)
    prev7_avg = closed.iloc[-8:-1]["quote_volume"].mean()
    latest_vs_7d = vol_24h_closed / prev7_avg if prev7_avg > 0 else np.nan

    # Volume trend: compare last 3 days with previous 3 days.
    a = closed.iloc[-3:]["quote_volume"].mean()
    b = closed.iloc[-6:-3]["quote_volume"].mean()
    vol_3d_ratio = a / b if b > 0 else np.nan

    start_price = float(w.iloc[0].close)
    change_7w = (price / start_price - 1) * 100

    high_7w = float(w.high.max())
    low_7w = float(w.low.min())
    range_pct = (high_7w / low_7w - 1) * 100 if low_7w > 0 else np.nan
    dist_high = (price / high_7w - 1) * 100
    dist_low = (price / low_7w - 1) * 100

    # How much of the 7-week high has already been traveled?
    # Avoid rewarding coins that already made a huge vertical move.
    max_close = float(w.close.max())
    max_close_change = (max_close / start_price - 1) * 100

    # Recent volatility / ATR-ish measure.
    tr = pd.concat([
        w["high"] - w["low"],
        (w["high"] - w["close"].shift()).abs(),
        (w["low"] - w["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr_pct = (tr.tail(14).mean() / price) * 100

    # Higher-low proxy: slope of normalized recent lows.
    low_slope = linear_slope(w.tail(21)["low"].values)
    low_slope_pct = (low_slope / price) * 100 * 21

    # Consolidation near highs is preferred, but not if already too extended.
    near_high = max(-30.0, min(0.0, dist_high))
    consolidation_score = max(0, 15 - abs(near_high) * 0.45)

    # Volume score, capped.
    volume_score = 0
    if np.isfinite(vol_ratio):
        volume_score = min(25, max(0, (vol_ratio - 1) * 12.5))
    if np.isfinite(latest_vs_7d) and latest_vs_7d >= 2:
        volume_score += min(10, (latest_vs_7d - 2) * 5 + 5)
    volume_score = min(35, volume_score)

    # Price extension penalty.
    extension_penalty = 0
    if change_7w > 30: extension_penalty += min(20, (change_7w - 30) * 0.35)
    if max_close_change > 60: extension_penalty += min(15, (max_close_change - 60) * 0.25)

    # Momentum/structure.
    structure_score = 0
    if np.isfinite(low_slope_pct):
        structure_score += 10 if low_slope_pct > 0.5 else 5 if low_slope_pct > 0 else 0
    if -18 <= dist_high <= -2:
        structure_score += 8
    elif -30 <= dist_high < -18:
        structure_score += 4
    if 0 <= change_7w <= 30:
        structure_score += 7

    # Stability: reward volume rising over multiple days rather than a single spike.
    stability_score = 0
    if np.isfinite(vol_3d_ratio):
        stability_score = 10 if 1.25 <= vol_3d_ratio <= 3.5 else 5 if vol_3d_ratio > 1 else 0

    score = volume_score + structure_score + stability_score + consolidation_score - extension_penalty
    score = max(0, min(100, score))

    # Qualitative label.
    if score >= 75:
        label = "A — bardzo ciekawy setup"
    elif score >= 60:
        label = "B — ciekawy, wymaga potwierdzenia"
    elif score >= 45:
        label = "C — obserwacja"
    else:
        label = "D — słaby setup"

    return {
        "symbol": symbol,
        "price": price,
        "quote_volume_24h": vol_24h_closed,
        "avg_7d_volume": recent7_vol,
        "avg_prior_7d_volume": avg_prior7_vol,
        "volume_ratio_7d": vol_ratio,
        "latest_vs_prev7": latest_vs_7d,
        "volume_3d_ratio": vol_3d_ratio,
        "change_7w": change_7w,
        "high_7w": high_7w,
        "low_7w": low_7w,
        "distance_high": dist_high,
        "range_7w": range_pct,
        "max_close_change": max_close_change,
        "atr_pct": atr_pct,
        "low_slope_pct": low_slope_pct,
        "score": score,
        "label": label,
        "data": closed,
    }, closed

# -----------------------------
# Sidebar
# -----------------------------
with st.sidebar:
    st.header("⚙️ Ustawienia")
    top_n = st.slider(
        "Liczba par do szczegółowego skanu",
        min_value=30, max_value=250, value=100, step=10,
        help="Najpierw pobierane są tickery wszystkich par, a świece 7-tygodniowe dla najwyżej obrotowych par."
    )
    min_quote = st.number_input(
        "Min. wolumen 24h (USDT)",
        min_value=0.0, value=100_000.0, step=50_000.0,
    )
    min_vol_ratio = st.slider(
        "Min. wzrost średniego wolumenu 7D vs wcześniejsze 7D",
        1.0, 5.0, 1.5, 0.1
    )
    max_7w_change = st.slider(
        "Maksymalny wzrost ceny w 7 tygodniach (%)",
        10, 300, 40, 5
    )
    run_scan = st.button("🔎 Uruchom skan MEXC", type="primary", use_container_width=True)

# -----------------------------
# Manual analysis
# -----------------------------
st.subheader("🧪 Oceń dowolną kryptowalutę z MEXC")
manual = st.text_input(
    "Wpisz symbol pary",
    placeholder="np. GRVTUSDT, HOMEUSDT, XDPUSDT",
).strip().upper()

if manual:
    with st.spinner(f"Analizuję {manual}..."):
        try:
            result, df = analyze_symbol(manual, 49)
            if result is None:
                st.warning("Za mało danych historycznych dla tej pary.")
            else:
                c1,c2,c3,c4,c5 = st.columns(5)
                c1.metric("Score", f"{result['score']:.0f}/100")
                c2.metric("Wolumen 24h", fmt_money(result["quote_volume_24h"]))
                c3.metric("Wolumen 7D / poprzednie 7D", f"{result['volume_ratio_7d']:.2f}×")
                c4.metric("Zmiana 7 tyg.", pct(result["change_7w"]))
                c5.metric("Od szczytu 7W", pct(result["distance_high"]))

                st.info(
                    f"**{result['label']}**. "
                    "To ranking setupu pod potencjalne przyszłe wybicie, a nie prognoza ceny."
                )

                base = manual.replace("USDT","").replace("USDC","")
                cg_manual = cg_enrich_symbols([manual])
                if len(cg_manual):
                    fr = cg_manual.iloc[0]
                    fs = fundamental_score(fr)
                    m1,m2,m3,m4 = st.columns(4)
                    m1.metric("Market cap", fmt_money(fr.get("market_cap")))
                    m2.metric("FDV", fmt_money(fr.get("fdv")))
                    m3.metric("FDV / MC", f"{(fr.get('fdv')/fr.get('market_cap')):.2f}×" if pd.notna(fr.get('fdv')) and pd.notna(fr.get('market_cap')) and fr.get('market_cap') else "—")
                    m4.metric("Fundamental proxy", f"{fs:.0f}/25")
                    st.caption(
                        "Fundamental proxy obejmuje market cap, relację FDV/MC, płynność i podstawową jakość/kompletność danych. "
                        "Nie ocenia automatycznie zespołu, produktu ani unlocków."
                    )

                left, right = st.columns(2)
                with left:
                    st.write("**Kluczowe dane**")
                    st.write(f"- Ostatnia cena: `{result['price']:.10g}`")
                    st.write(f"- 24h wolumen: `{fmt_money(result['quote_volume_24h'])}`")
                    st.write(f"- Średni wolumen ostatnich 7D: `{fmt_money(result['avg_7d_volume'])}`")
                    st.write(f"- 24h vs średnia poprzednich 7D: `{result['latest_vs_prev7']:.2f}×`")
                    st.write(f"- Średni wolumen 7D vs wcześniejsze 7D: `{result['volume_ratio_7d']:.2f}×`")
                    st.write(f"- Ostatnie 3D vs poprzednie 3D: `{result['volume_3d_ratio']:.2f}×`")
                with right:
                    st.write("**Struktura 7 tygodni**")
                    st.write(f"- Min: `{result['low_7w']:.10g}`")
                    st.write(f"- Max: `{result['high_7w']:.10g}`")
                    st.write(f"- Odległość od 7W high: `{result['distance_high']:.1f}%`")
                    st.write(f"- Zmiana od początku okna: `{result['change_7w']:.1f}%`")
                    st.write(f"- Maks. wzrost close w oknie: `{result['max_close_change']:.1f}%`")
                    st.write(f"- Zmienność/ATR proxy: `{result['atr_pct']:.1f}%`")
                    st.write(f"- Trend dołków: `{result['low_slope_pct']:.2f}% / 21D`")

                chart = result["data"].tail(49).set_index("time")[["close"]]
                st.line_chart(chart)

                st.subheader("🎯 Poziomy do obserwacji")
                p = result["price"]
                h = result["high_7w"]
                support = result["low_7w"] + 0.35*(h-result["low_7w"])
                breakout = h
                st.write(
                    f"- **Strefa obserwacji wsparcia:** ~`{support:.10g}`\n"
                    f"- **7W high / potencjalny trigger:** ~`{breakout:.10g}`\n"
                    f"- **+100% od obecnej ceny:** `{p*2:.10g}`\n"
                    f"- **+200%:** `{p*3:.10g}`\n"
                    f"- **+300%:** `{p*4:.10g}`"
                )
        except Exception as e:
            st.error(f"Nie udało się pobrać danych: {e}")

# -----------------------------
# Fundamental and tokenomics workbench
# -----------------------------
st.divider()
st.subheader("🧩 Fundamenty, tokenomia i ryzyka — ocena ręczna")
st.caption(
    "Te elementy wymagają weryfikacji źródeł projektu. Aplikacja nie zgaduje jakości zespołu, produktu, unlocków ani sentymentu. "
    "Wpisz dane z dokumentacji tokena, oficjalnych komunikatów i wiarygodnych dashboardów."
)
with st.expander("Otwórz checklistę fundamentalną dla wybranej monety", expanded=False):
    fcol1, fcol2, fcol3 = st.columns(3)
    with fcol1:
        team_rating = st.slider("Zespół / inwestorzy (0–5)", 0, 5, 3, help="Sprawdź doświadczenie, publiczne profile, wcześniejsze projekty i wiarygodność finansowania.")
        product_rating = st.slider("Produkt i realne zastosowanie (0–5)", 0, 5, 3, help="Oceniaj działający produkt i użycie, nie tylko roadmapę.")
    with fcol2:
        traction_rating = st.slider("Trakcja: TVL, przychody, użytkownicy (0–5)", 0, 5, 2)
        community_rating = st.slider("Społeczność / narracja / newsy (0–5)", 0, 5, 2, help="Sprawdź czy wzrost zainteresowania jest organiczny i potwierdzony źródłami.")
    with fcol3:
        tokenomics_rating = st.slider("Tokenomia i użyteczność tokena (0–5)", 0, 5, 3)
        transparency_rating = st.slider("Transparentność i bezpieczeństwo (0–5)", 0, 5, 3)

    u1, u2, u3 = st.columns(3)
    with u1:
        unlock_pct_30d = st.number_input("Unlock w 30 dni (% obecnego obiegu)", min_value=0.0, max_value=500.0, value=0.0, step=0.5, help="Wpisz 0 tylko jeśli zweryfikowano, że nie ma unlocku; inaczej pozostaw jako nieznane poza oceną.")
    with u2:
        unlock_pct_90d = st.number_input("Unlock w 90 dni (% obecnego obiegu)", min_value=0.0, max_value=1000.0, value=0.0, step=1.0)
    with u3:
        protocol_slug = st.text_input("Slug protokołu DefiLlama (opcjonalnie)", placeholder="np. aave, hyperliquid")

    manual_notes = st.text_area("Notatki / linki do źródeł", placeholder="Dokumentacja tokenomii, harmonogram unlocków, dashboard przychodów, audyt, komunikat zespołu…", height=80)
    fundamental_manual = (team_rating + product_rating + traction_rating + community_rating + tokenomics_rating + transparency_rating) / 30 * 100
    unlock_penalty = min(25, unlock_pct_30d * 1.5) + min(15, unlock_pct_90d * 0.35)
    manual_fundamental_score = max(0, min(100, fundamental_manual - unlock_penalty))
    st.metric("Ręczny wynik fundamentalny po karze za unlocki", f"{manual_fundamental_score:.0f}/100")
    if unlock_pct_30d >= 10:
        st.warning("Duże rozwodnienie w 30 dni: sprawdź datę, odbiorców i wartość unlocku przed oceną setupu.")
    if unlock_pct_30d == 0 and unlock_pct_90d == 0:
        st.caption("Wartości unlocków 0% nie potwierdzają braku unlocków — oznaczają tylko wpisane wartości. Zweryfikuj harmonogram ręcznie.")

    if protocol_slug.strip():
        try:
            with st.spinner("Pobieram publiczne dane DefiLlama…"):
                dl = defillama_protocol(protocol_slug)
            if dl:
                d1, d2, d3 = st.columns(3)
                d1.metric(f"TVL — {dl['name']}", fmt_money(dl.get("tvl")))
                d2.metric("Zmiana TVL ~30D", pct(dl.get("tvl_change_30d")))
                d3.metric("Kategoria", str(dl.get("category") or "—"))
                if dl.get("url"):
                    st.markdown(f"Źródło/protokół: [{dl['name']}]({dl['url']})")
                st.caption("TVL jest metryką protokołu, a nie dowodem wartości tokena. Sprawdź, czy slug rzeczywiście odpowiada analizowanemu projektowi.")
            else:
                st.info("Nie znaleziono protokołu pod tym slugiem. Sprawdź nazwę w DefiLlama.")
        except Exception as e:
            st.warning(f"DefiLlama nie zwrócił danych: {e}. Możesz kontynuować ocenę ręczną.")

    st.download_button(
        "⬇️ Pobierz checklistę fundamentalną jako TXT",
        data=(
            f"MEXC Breakout Radar v1.2 — checklista\nOcena fundamentalna: {manual_fundamental_score:.1f}/100\n"
            f"Zespół: {team_rating}/5\nProdukt: {product_rating}/5\nTrakcja: {traction_rating}/5\n"
            f"Społeczność/narracja: {community_rating}/5\nTokenomia: {tokenomics_rating}/5\n"
            f"Transparentność/bezpieczeństwo: {transparency_rating}/5\nUnlock 30D (% obiegu): {unlock_pct_30d}\n"
            f"Unlock 90D (% obiegu): {unlock_pct_90d}\nSlug DefiLlama: {protocol_slug}\nNotatki: {manual_notes}\n"
        ).encode("utf-8"),
        file_name="mexc_fundamental_checklist.txt",
        mime="text/plain",
    )

# -----------------------------
# Full scan
# -----------------------------
st.divider()
st.subheader("📡 Automatyczny skan kandydatów")

if run_scan:
    try:
        with st.spinner("Pobieram aktualne tickery MEXC..."):
            ex = mexc_exchange_info()
            tick = mexc_tickers()

        if "symbol" not in tick.columns:
            st.error("Nieprawidłowa odpowiedź MEXC ticker API.")
            st.stop()

        # Spot USDT pairs only, enabled where status exists.
        symbols = tick[tick["symbol"].str.endswith("USDT", na=False)].copy()
        symbols["quoteVolume"] = pd.to_numeric(symbols.get("quoteVolume"), errors="coerce")
        symbols["lastPrice"] = pd.to_numeric(symbols.get("lastPrice"), errors="coerce")
        symbols["priceChangePercent"] = pd.to_numeric(symbols.get("priceChangePercent"), errors="coerce")
        symbols = symbols[symbols["quoteVolume"] >= min_quote]
        symbols = symbols.sort_values("quoteVolume", ascending=False).head(top_n)

        results = []
        progress = st.progress(0)
        total = len(symbols)

        for i, sym in enumerate(symbols["symbol"], 1):
            try:
                r, _ = analyze_symbol(sym, 49)
                if r:
                    results.append(r)
            except Exception:
                pass
            progress.progress(i/total)

        progress.empty()

        if not results:
            st.warning("Brak wyników. Zmniejsz minimalny wolumen lub zwiększ liczbę skanowanych par.")
        else:
            out = pd.DataFrame([{k:v for k,v in r.items() if k != "data"} for r in results])

            # Enrich with CoinGecko market/FDV/liquidity data.
            cg = cg_enrich_symbols(out["symbol"].tolist())
            if len(cg):
                out = out.merge(cg, on="symbol", how="left")
                out["fundamental_score"] = out.apply(fundamental_score, axis=1)
            else:
                out["fundamental_score"] = 0.0

            # Rebalance: technical setup 75%, market/fundamental proxy 25%.
            out["total_score"] = (
                out["score"] * 0.75 + out["fundamental_score"] * 1.0
            ).clip(0, 100)

            out["potential_200"] = np.where(
                out["total_score"] >= 75, "HIGH",
                np.where(out["total_score"] >= 60, "MED-HIGH",
                         np.where(out["total_score"] >= 45, "MEDIUM", "LOW"))
            )
            out["potential_300"] = np.where(
                out["total_score"] >= 82, "MED-HIGH",
                np.where(out["total_score"] >= 68, "MEDIUM",
                         np.where(out["total_score"] >= 50, "SPECULATIVE", "LOW"))
            )

            # Explainable risk flags; unknown values are not treated as zero risk.
            def risk_flags(row):
                flags = []
                cap, fdv = row.get("market_cap", np.nan), row.get("fdv", np.nan)
                if pd.notna(cap) and cap < 5_000_000:
                    flags.append("mikrokap / kruchość")
                if pd.notna(cap) and cap > 0 and pd.notna(fdv) and fdv / cap >= 3:
                    flags.append("wysokie FDV/MC")
                if pd.notna(row.get("change_7w")) and row.get("change_7w") > 50:
                    flags.append("cena już mocno urosła")
                if pd.notna(row.get("latest_vs_prev7")) and row.get("latest_vs_prev7") >= 8:
                    flags.append("możliwy jednorazowy spike wolumenu")
                if pd.notna(row.get("distance_high")) and row.get("distance_high") < -35:
                    flags.append("daleko od szczytu 7W")
                return "; ".join(flags) if flags else "brak oczywistej flagi z dostępnych danych"
            out["risk_flags"] = out.apply(risk_flags, axis=1)
            out["reason"] = out.apply(
                lambda r: f"wolumen {r['volume_ratio_7d']:.1f}×; cena {r['change_7w']:+.1f}% / 7W; od szczytu {r['distance_high']:.1f}%",
                axis=1,
            )

            out = out[
                (out["volume_ratio_7d"] >= min_vol_ratio) &
                (out["change_7w"] <= max_7w_change)
            ].sort_values(
                ["total_score","volume_ratio_7d"], ascending=[False,False]
            )

            st.success(
                f"Okno analizy: ostatnie **49 zamkniętych dni**. "
                f"Po filtrach pozostało **{len(out)}** kandydatów."
            )

            if len(out):
                show = out.copy()
                show["symbol"] = show["symbol"].str.replace("USDT","/USDT", regex=False)
                show["24h volume"] = show["quote_volume_24h"].map(fmt_money)
                show["volume 7D / prev 7D"] = show["volume_ratio_7d"].map(lambda x: f"{x:.2f}×")
                show["24h / prev7 avg"] = show["latest_vs_prev7"].map(lambda x: f"{x:.2f}×")
                show["7W change"] = show["change_7w"].map(lambda x: f"{x:.1f}%")
                show["from 7W high"] = show["distance_high"].map(lambda x: f"{x:.1f}%")
                show["technical"] = show["score"].map(lambda x: round(x))
                show["total_score"] = show["total_score"].map(lambda x: round(x))
                show["fundamental"] = show["fundamental_score"].map(lambda x: f"{x:.0f}/25")
                show["market cap"] = show["market_cap"].map(fmt_money)
                show["FDV"] = show["fdv"].map(fmt_money)
                show["setup"] = show["label"]
                show["+200%"] = show["potential_200"]
                show["+300%"] = show["potential_300"]

                st.dataframe(
                    show[
                        ["symbol","total_score","technical","fundamental","setup",
                         "market cap","FDV","24h volume",
                         "volume 7D / prev 7D","24h / prev7 avg",
                         "7W change","from 7W high","+200%","+300%","reason","risk_flags"]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

                st.download_button(
                    "⬇️ Pobierz wyniki CSV",
                    out.to_csv(index=False).encode("utf-8"),
                    file_name=f"mexc_breakout_scan_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                )

                st.markdown(
                    "**Jak czytać ranking:** 75% wyniku pochodzi z setupu technicznego, "
                    "a 25% z proxy rynkowo-fundamentalnego (market cap, FDV/MC, płynność i ranking CoinGecko). "
                    "Dodatkowa checklista zespołu, produktu, TVL/trakcji, społeczności i unlocków jest osobnym modułem ręcznym. "
                    "Flagi ryzyka są widoczne w tabeli. Oceny +200%/+300% nie są prawdopodobieństwem statystycznym."
                )
            else:
                st.warning("Nie znaleziono par spełniających aktualne kryteria.")
    except Exception as e:
        st.error(f"Skan nie powiódł się: {e}")

st.caption(
    "Źródło danych: publiczne API spot MEXC. Aplikacja korzysta z tickerów 24h i dziennych świec OHLCV. "
    "Dane rynkowe mogą być opóźnione lub niepełne; CoinGecko symbol mapping bywa niejednoznaczny. "
    "DefiLlama TVL działa po ręcznym dopasowaniu slugiem; unlocki, team, newsy i social nie są automatycznie zweryfikowane. "
    "Przed transakcją sprawdź źródła projektu i dane bezpośrednio na giełdzie."
)
