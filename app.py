"""BTC Breakout Radar v1.5 — public market data, educational scenario planner."""
from datetime import datetime, timezone, timedelta
import math
import requests
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title='BTC Breakout Radar v1.5', page_icon='₿', layout='wide')
st.title('₿ BTC Breakout Radar v1.5')
st.caption('Tylko Bitcoin • MEXC SPOT i FUTURES • scenariusze warunkowe, nie gwarantowane sygnały')
st.warning('Nie istnieją sygnały LONG/SHORT ze 100% pewnością. Futures mogą doprowadzić do utraty całego depozytu. Aplikacja nie składa zleceń.')
S = requests.Session()
S.headers.update({'User-Agent': 'BTC-Radar/1.5', 'Accept': 'application/json'})

def fetch_json(url, params=None):
    r=S.get(url,params=params,timeout=15)
    r.raise_for_status()
    j=r.json()
    if isinstance(j,dict) and (j.get('success') is False or str(j.get('code','')) in ('400','500')):
        raise ValueError(str(j.get('message') or j.get('msg') or 'Błąd API'))
    return j

@st.cache_data(ttl=120,show_spinner=False)
def spot_candles(interval, limit=500):
    raw=fetch_json('https://api.mexc.com/api/v3/klines',{'symbol':'BTCUSDT','interval':interval,'limit':limit})
    if not isinstance(raw,list) or len(raw)<80: raise ValueError('Za mało świec SPOT')
    df=pd.DataFrame(raw,columns=['time','open','high','low','close','volume','end','quote_volume','trades','taker_base','taker_quote','ignore'])
    for c in ['open','high','low','close','volume','quote_volume']: df[c]=pd.to_numeric(df[c],errors='coerce')
    df['time']=pd.to_datetime(df['time'],unit='ms',utc=True)
    return df[['time','open','high','low','close','volume','quote_volume']].dropna().iloc[:-1].reset_index(drop=True)

@st.cache_data(ttl=120,show_spinner=False)
def futures_candles(interval, limit=500):
    j=fetch_json('https://contract.mexc.com/api/v1/contract/kline/BTC_USDT',{'interval':interval,'limit':limit})
    d=j.get('data',{})
    if not isinstance(d,dict) or len(d.get('time',[]))<80: raise ValueError('Za mało świec FUTURES')
    df=pd.DataFrame({k:d[k] for k in ('time','open','high','low','close','vol')})
    for c in ['open','high','low','close','vol']: df[c]=pd.to_numeric(df[c],errors='coerce')
    df['time']=pd.to_datetime(df['time'],unit='s',utc=True)
    df=df.rename(columns={'vol':'volume'})
    df['quote_volume']=np.nan  # nie zgadujemy jednostek wolumenu futures
    return df.dropna(subset=['open','high','low','close']).iloc[:-1].reset_index(drop=True)

def indicators(df):
    d=df.copy()
    d['ema20']=d.close.ewm(span=20,adjust=False).mean()
    d['ema50']=d.close.ewm(span=50,adjust=False).mean()
    prev=d.close.shift()
    tr=pd.concat([(d.high-d.low).abs(),(d.high-prev).abs(),(d.low-prev).abs()],axis=1).max(axis=1)
    d['atr']=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    delta=d.close.diff()
    up=delta.clip(lower=0).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    down=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    d['rsi']=100-100/(1+up/down.replace(0,np.nan))
    d['vmean20']=d.volume.shift(1).rolling(20).mean()
    d['vrel']=d.volume/d.vmean20.replace(0,np.nan)
    d['resistance']=d.high.shift(1).rolling(20).max()
    d['support']=d.low.shift(1).rolling(20).min()
    return d

def money(x):
    return f'{x:,.2f} USDT' if pd.notna(x) else 'brak danych'

def analyze(df, label):
    d=indicators(df)
    a=d.iloc[-1]
    price=float(a.close); atr=float(a.atr)
    sup=float(a.support); res=float(a.resistance)
    trend='WZROSTOWY' if price>a.ema20>a.ema50 else 'SPADKOWY' if price<a.ema20<a.ema50 else 'MIESZANY'
    rsi=float(a.rsi) if pd.notna(a.rsi) else np.nan
    vrel=float(a.vrel) if pd.notna(a.vrel) else np.nan
    close_time=a.time
    st.subheader(label)
    st.caption(f'Ostatnia zamknięta świeca: {close_time:%Y-%m-%d %H:%M} UTC. Poziomy liczone z poprzednich 20 świec.')
    c1,c2,c3,c4=st.columns(4)
    c1.metric('Cena zamknięcia',money(price))
    c2.metric('Trend',trend)
    c3.metric('RSI(14)',f'{rsi:.1f}' if np.isfinite(rsi) else '—')
    c4.metric('Wolumen / średnia 20',f'{vrel:.2f}×' if np.isfinite(vrel) else '—')
    st.write(f'**Wsparcie:** {money(sup)} | **Opór:** {money(res)} | **EMA20:** {money(a.ema20)} | **EMA50:** {money(a.ema50)} | **ATR14:** {money(atr)}')
    # Breakouts based strictly on last CLOSED candle, resistance/support excluding current candle
    long_break=price>res and trend=='WZROSTOWY' and np.isfinite(vrel) and vrel>=1.5 and np.isfinite(rsi) and 48<=rsi<=72
    short_break=price<sup and trend=='SPADKOWY' and np.isfinite(vrel) and vrel>=1.5 and np.isfinite(rsi) and 28<=rsi<=52
    if long_break: verdict='POTWIERDZONE WYBICIE W GÓRĘ — obserwuj retest, nie goń świecy'
    elif short_break: verdict='POTWIERDZONE WYBICIE W DÓŁ — obserwuj retest, nie goń świecy'
    else: verdict='BRAK POTWIERDZONEGO WEJŚCIA — CZEKAJ'
    st.info('**Ocena:** '+verdict)
    st.write('**Uzasadnienie:** '+ '; '.join([
        f'trend {trend.lower()}',f'RSI {rsi:.1f}' if np.isfinite(rsi) else 'RSI niedostępne',
        f'ostatni wolumen {vrel:.2f}× średniej' if np.isfinite(vrel) else 'wolumen niedostępny',
        'zamknięcie ponad oporem' if price>res else 'zamknięcie pod wsparciem' if price<sup else 'cena między wsparciem i oporem']))
    # conditional retest plans, NOT market orders
    pad=0.15*atr
    scenarios=[]
    for side,level,stop,target,condition in [
        ('LONG',res,res-1.2*atr,res+2.4*atr,'Zamknięcie świecy nad oporem z wolumenem ≥1,5× średniej, następnie utrzymany retest oporu od góry; RSI 48–72; EMA20 > EMA50'),
        ('SHORT',sup,sup+1.2*atr,sup-2.4*atr,'Zamknięcie świecy pod wsparciem z wolumenem ≥1,5× średniej, następnie nieudany retest wsparcia od dołu; RSI 28–52; EMA20 < EMA50')]:
        valid=(target>0 and stop>0 and np.isfinite(atr) and atr>0)
        scenarios.append({'Scenariusz':side,'Strefa obserwacji':f'{level-pad:,.2f}–{level+pad:,.2f}' if valid else '—',
            'Stop (modelowy)':money(stop) if valid else '—','Cel 1 (modelowy)':money(target) if valid else '—',
            'R:R (modelowe)':'2,0:1' if valid else '—','Warunek aktywacji':condition})
    st.dataframe(pd.DataFrame(scenarios),use_container_width=True,hide_index=True)
    st.caption('Strefy są hipotetycznymi planami retestu, a nie aktualnymi zleceniami. Stop/cele liczone z ATR, mogą nie odpowiadać realnej płynności; R:R nie obejmuje prowizji, poślizgu ani funding.')
    chart=d.tail(150).set_index('time')[['close','ema20','ema50','support','resistance']]
    st.line_chart(chart)
    st.bar_chart(d.tail(80).set_index('time')[['volume']])
    return verdict

with st.sidebar:
    st.header('Ustawienia')
    market=st.selectbox('Rynek', ['MEXC FUTURES BTC_USDT','MEXC SPOT BTCUSDT'])
    tf=st.selectbox('Interwał',['1h','4h','1d'],index=1)
    if st.button('Odśwież dane teraz'):
        spot_candles.clear(); futures_candles.clear(); st.rerun()
    st.caption('Odświeżanie automatyczne przez cache co ok. 2 minuty po ponownym otwarciu/uruchomieniu. Bez alertów w tle.')

try:
    if market.startswith('MEXC FUTURES'):
        interval={'1h':'Min60','4h':'Hour4','1d':'Day1'}[tf]
        df=futures_candles(interval)
        st.caption('Wolumen futures w jednostkach kontraktowych API MEXC. Współczynnik wolumenu porównuje tę samą jednostkę między świecami.')
    else:
        interval={'1h':'1h','4h':'4h','1d':'1d'}[tf]
        df=spot_candles(interval)
        st.caption('Wolumen spot w BTC; porównanie względne między świecami.')
    analyze(df, f'BTC — {market} — {tf}')
except Exception as exc:
    st.error('Nie udało się pobrać/zweryfikować danych rynku. Nie pokazuję sygnału ani nie zgaduję cen.')
    st.code(str(exc))

st.divider()
st.header('🌍 FED i wydarzenia makro')
st.write('Decyzje FOMC, konferencje Jerome’a Powella, CPI, NFP i nieoczekiwane wydarzenia geopolityczne mogą gwałtownie zmienić kurs BTC. Nie zakładamy z góry ich wpływu.')
st.markdown('**Źródła oficjalne:** [kalendarz posiedzeń FOMC](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) · [komunikaty Fed](https://www.federalreserve.gov/newsevents/pressreleases.htm) · [publikacje CPI (BLS)](https://www.bls.gov/schedule/news_release/cpi.htm) · [publikacje zatrudnienia (BLS)](https://www.bls.gov/schedule/news_release/empsit.htm)')
st.caption('Aplikacja nie pobiera automatycznie kalendarza ani wiadomości. Bez potwierdzonego harmonogramu nie wyświetla fikcyjnych dat, newsów ani „oceny wpływu AI”.')
st.subheader('Blokada handlu przed wydarzeniem — kontrola ręczna')
now=datetime.now(timezone.utc)
macro=st.checkbox('Wiem o ważnym wydarzeniu makro w ciągu najbliższych 2 godzin lub właśnie trwa',value=False)
if macro: st.error('RYZYKO WYDARZENIA — wstrzymaj nowe scenariusze do czasu ustabilizowania spreadu i zmienności.')
else: st.warning('Status wydarzeń: NIEZWERYFIKOWANY. Brak zaznaczenia nie oznacza, że w kalendarzu nie ma wydarzeń.')

st.divider()
st.header('🛡️ Kalkulator ryzyka — symulacja')
a,b,c=st.columns(3)
capital=a.number_input('Kapitał testowy (USDT)',min_value=10.0,value=1000.0,step=100.0)
risk_pct=b.number_input('Ryzyko na transakcję (%)',min_value=0.1,max_value=5.0,value=0.5,step=0.1)
stop_pct=c.number_input('Odległość stopa (%)',min_value=0.1,max_value=30.0,value=1.5,step=0.1)
fee=st.number_input('Szacowane koszty wejścia + wyjścia i poślizg (%)',min_value=0.0,max_value=5.0,value=0.2,step=0.05)
loss_budget=capital*risk_pct/100
notional=loss_budget/((stop_pct+fee)/100)
st.write(f'**Budżet straty:** {loss_budget:.2f} USDT | **Orientacyjna wartość pozycji:** {notional:.2f} USDT')
st.caption('Przybliżenie bez likwidacji, funding i skoków ceny. Dźwignia nie poprawia prawdopodobieństwa trafnego kierunku.')
st.caption('Dane i obliczenia mają charakter edukacyjny. Nie są spersonalizowaną rekomendacją inwestycyjną.')
