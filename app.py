"""BTC Breakout Radar v1.6 — BTC technical dashboard + auditable X watchlist."""
from datetime import datetime, timezone
import math
import re
import requests
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title='BTC Breakout Radar 1.6', page_icon='₿', layout='wide', initial_sidebar_state='collapsed')
st.markdown('''<style>
.block-container {max-width:1250px;padding-top:1.3rem}
h1,h2,h3 {letter-spacing:-.025em}
[data-testid="stMetric"] {background:#151e2d;border:1px solid #2b3b51;border-radius:12px;padding:13px}
[data-testid="stMetricLabel"] {color:#b9c7da}
[data-testid="stTabs"] button {font-weight:650}
</style>''',unsafe_allow_html=True)
st.title('₿ BTC BREAKOUT RADAR')
st.caption('v1.6 • Panel BTC / USDT • analiza techniczna i weryfikowalne scenariusze • bez automatycznych zleceń')
S=requests.Session(); S.headers.update({'User-Agent':'BTC-Radar/1.6','Accept':'application/json'})

def fetch_json(url,params=None):
    r=S.get(url,params=params,timeout=15);r.raise_for_status();j=r.json()
    if isinstance(j,dict) and (j.get('success') is False or str(j.get('code','')) in ('400','500')):
        raise ValueError(str(j.get('message') or j.get('msg') or 'Błąd API'))
    return j

@st.cache_data(ttl=90,show_spinner=False)
def spot_candles(interval,limit=500):
    raw=fetch_json('https://api.mexc.com/api/v3/klines',{'symbol':'BTCUSDT','interval':interval,'limit':limit})
    if not isinstance(raw,list) or len(raw)<80: raise ValueError('Za mało świec SPOT')
    df=pd.DataFrame(raw,columns=['time','open','high','low','close','volume','end','quote_volume','trades','taker_base','taker_quote','ignore'])
    for c in ['open','high','low','close','volume','quote_volume']:df[c]=pd.to_numeric(df[c],errors='coerce')
    df['time']=pd.to_datetime(df.time,unit='ms',utc=True)
    return df[['time','open','high','low','close','volume','quote_volume']].dropna().iloc[:-1].reset_index(drop=True)

@st.cache_data(ttl=90,show_spinner=False)
def futures_candles(interval,limit=500):
    j=fetch_json('https://contract.mexc.com/api/v1/contract/kline/BTC_USDT',{'interval':interval,'limit':limit})
    d=j.get('data',{})
    if not isinstance(d,dict) or len(d.get('time',[]))<80:raise ValueError('Za mało świec FUTURES')
    df=pd.DataFrame({k:d[k] for k in ('time','open','high','low','close','vol')})
    for c in ['open','high','low','close','vol']:df[c]=pd.to_numeric(df[c],errors='coerce')
    df['time']=pd.to_datetime(df.time,unit='s',utc=True)
    df=df.rename(columns={'vol':'volume'});df['quote_volume']=np.nan
    return df.dropna(subset=['open','high','low','close','volume']).iloc[:-1].reset_index(drop=True)

def indicators(df):
    d=df.copy();d['ema20']=d.close.ewm(span=20,adjust=False).mean();d['ema50']=d.close.ewm(span=50,adjust=False).mean()
    prev=d.close.shift();tr=pd.concat([(d.high-d.low).abs(),(d.high-prev).abs(),(d.low-prev).abs()],axis=1).max(axis=1)
    d['atr']=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    delta=d.close.diff();up=delta.clip(lower=0).ewm(alpha=1/14,adjust=False,min_periods=14).mean();down=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    d['rsi']=100-100/(1+up/down.replace(0,np.nan))
    d['vmean20']=d.volume.shift(1).rolling(20).mean();d['vrel']=d.volume/d.vmean20.replace(0,np.nan)
    d['resistance']=d.high.shift(1).rolling(20).max();d['support']=d.low.shift(1).rolling(20).min()
    return d

def fmt(x):return f'{x:,.2f}' if np.isfinite(x) else '—'

def compute(d):
    a=d.iloc[-1];p=float(a.close);atr=float(a.atr);sup=float(a.support);res=float(a.resistance)
    rsi=float(a.rsi);vr=float(a.vrel);up=p>a.ema20>a.ema50;down=p<a.ema20<a.ema50
    long_ok=up and p>res and vr>=1.5 and 48<=rsi<=72
    short_ok=down and p<sup and vr>=1.5 and 28<=rsi<=52
    # Plan is anchored to a level, NOT the current market price. Trigger requires close + retest.
    plans=[]
    for side,level,stop,target,ok,cond in [
        ('LONG',res,res-1.2*atr,res+2.4*atr,long_ok,'Zamknięcie ponad oporem + wolumen ≥1,5× + RSI 48–72 + EMA20 > EMA50; następnie udany retest'),
        ('SHORT',sup,sup+1.2*atr,sup-2.4*atr,short_ok,'Zamknięcie poniżej wsparcia + wolumen ≥1,5× + RSI 28–52 + EMA20 < EMA50; następnie nieudany retest')]:
        valid=all(np.isfinite(x) for x in [level,stop,target,atr]) and atr>0 and stop>0 and target>0
        plans.append({'Kierunek':side,'Status':'POTWIERDZENIE WYBICIA — CZEKAJ NA RETEST' if ok else 'NIEAKTYWNY',
          'Wejście — od':round(level-.15*atr,2) if valid else None,'Wejście — do':round(level+.15*atr,2) if valid else None,
          'Stop-loss':round(stop,2) if valid else None,'Take-profit':round(target,2) if valid else None,
          'R:R (model)':2.0 if valid else None,'Warunki':cond})
    return a,('WZROSTOWY' if up else 'SPADKOWY' if down else 'MIESZANY'),plans

with st.sidebar:
    st.header('Ustawienia')
    market=st.radio('Rynek',['FUTURES','SPOT'],horizontal=True)
    tf=st.selectbox('Interwał',['15m','1h','4h','1d'],index=2)
    if st.button('↻ Odśwież',use_container_width=True):spot_candles.clear();futures_candles.clear();st.rerun()
    st.caption('Dane z publicznego API MEXC. Odświeżanie cache: 90 sekund.')

main,x_tab,macro_tab,risk_tab=st.tabs(['📊 Terminal BTC','𝕏 Analitycy X','🌐 FED i makro','🛡️ Ryzyko'])
with main:
    try:
        mapping={'15m':('15m','Min15'),'1h':('1h','Min60'),'4h':('4h','Hour4'),'1d':('1d','Day1')}
        spot_tf,fut_tf=mapping[tf]
        df=spot_candles(spot_tf) if market=='SPOT' else futures_candles(fut_tf)
        d=indicators(df);a,trend,plans=compute(d)
        price=float(a.close);rsi=float(a.rsi);vr=float(a.vrel)
        c1,c2,c3,c4=st.columns(4)
        c1.metric('BTC / USDT',f'{price:,.2f}')
        c2.metric('Trend',trend)
        c3.metric('RSI (14)',f'{rsi:.1f}' if np.isfinite(rsi) else '—')
        c4.metric('Wolumen / średnia',f'{vr:.2f}×' if np.isfinite(vr) else '—')
        st.caption(f'Rynek: MEXC {market} • interwał {tf} • ostatnia zamknięta świeca: {a.time:%Y-%m-%d %H:%M} UTC • poziomy z 20 poprzednich świec')
        l,r=st.columns(2)
        l.info(f'**WSPARCIE:** {fmt(float(a.support))} USDT')
        r.info(f'**OPÓR:** {fmt(float(a.resistance))} USDT')
        st.subheader('Tabela poziomów LONG / SHORT')
        st.dataframe(pd.DataFrame(plans),use_container_width=True,hide_index=True,column_config={'Warunki':st.column_config.TextColumn(width='large')})
        st.caption('Ceny w USDT. Poziomy wyliczone z ATR i strefy retestu, nie są zleceniami rynkowymi. Status NIEAKTYWNY oznacza brak potwierdzenia. R:R jest modelowe i nie uwzględnia kosztów ani poślizgu.')
        if any(x['Status'].startswith('POTWIERDZENIE') for x in plans):st.warning('Wybicie jest potwierdzone na zamkniętej świecy, ale wejście wymaga jeszcze sprawdzenia retestu i aktualnej płynności.')
        else:st.info('Brak aktywnego scenariusza LONG/SHORT według ustalonych reguł. Nie wymuszamy transakcji.')
        st.subheader('Cena i poziomy techniczne')
        st.line_chart(d.tail(150).set_index('time')[['close','ema20','ema50','support','resistance']])
        st.subheader('Wolumen')
        st.bar_chart(d.tail(80).set_index('time')[['volume']])
        st.caption('Wolumen futures: jednostki kontraktowe API; SPOT: BTC. Porównanie wolumenu jest względne w obrębie tego samego rynku.')
    except Exception as e:
        st.error('Brak zweryfikowanych danych BTC — nie pokazuję wyliczonych poziomów.');st.code(str(e))

with x_tab:
    st.subheader('Publiczne analizy BTC z X — rejestr i weryfikacja')
    st.write('Porównuj **konkretne, datowane prognozy** z danymi BTC. Brak automatycznego dostępu do postów X i historii transakcji kont; nie przedstawiamy cudzych deklaracji jako potwierdzonego PNL.')
    st.markdown('**Konta do obserwacji (nie ranking skuteczności):** [@glassnode](https://x.com/glassnode) · [@CryptoQuant_com](https://x.com/cryptoquant_com) · [@lookonchain](https://x.com/lookonchain) · [@CoinGlass_com](https://x.com/coinglass_com). To źródła analiz/danych, nie zweryfikowani „najlepsi traderzy”.')
    st.caption('Wprowadzaj wyłącznie publiczne posty z bezpośrednim adresem i datą publikacji. Dane zapisywane są w sesji przeglądarki, nie w trwałej bazie.')
    if 'x_posts' not in st.session_state:st.session_state.x_posts=[]
    with st.form('x_form',clear_on_submit=True):
        c1,c2=st.columns(2)
        handle=c1.text_input('Konto X (np. @analityk)')
        url=c2.text_input('Link do konkretnego posta https://x.com/.../status/...')
        c3,c4,c5=st.columns(3)
        published=c3.date_input('Data posta (UTC)',value=datetime.now(timezone.utc).date())
        direction=c4.selectbox('Prognoza',['LONG','SHORT','NEUTRALNA'])
        horizon=c5.selectbox('Horyzont',['15m','1h','4h','1d','7d'])
        thesis=st.text_area('Dokładna teza, poziom wejścia / unieważnienia i cel (jeśli podano)')
        add=st.form_submit_button('Dodaj do rejestru')
    if add:
        if not re.match(r'^https://(?:www\.)?(?:x\.com|twitter\.com)/[^/]+/status/\d+',url.strip(),re.I):st.error('Podaj bezpośredni link do publicznego posta X.')
        elif not handle.strip() or not thesis.strip():st.error('Podaj konto i treść prognozy.')
        else:
            st.session_state.x_posts.append({'Konto':handle.strip(),'Data UTC':str(published),'Kierunek':direction,'Horyzont':horizon,'Teza':thesis.strip(),'Post':url.strip(),'Weryfikacja':'NIEZWERYFIKOWANE'})
            st.success('Dodano do rejestru. Wynik pozostaje niezweryfikowany do czasu porównania z cenami z właściwego okresu.')
    if st.session_state.x_posts:
        posts=pd.DataFrame(st.session_state.x_posts)
        st.dataframe(posts,use_container_width=True,hide_index=True,column_config={'Post':st.column_config.LinkColumn('Źródło')})
        st.download_button('Pobierz rejestr CSV',posts.to_csv(index=False).encode('utf-8-sig'),'analitycy_x_btc.csv','text/csv')
        if st.button('Wyczyść rejestr'):st.session_state.x_posts=[];st.rerun()
    else:st.info('Nie ma jeszcze udokumentowanych prognoz. Nie pokazuję fikcyjnych zagrań ani statystyk skuteczności.')
    st.markdown('**Jak weryfikować:** zapisz datę/godzinę posta, kierunek, poziom unieważnienia i horyzont; porównaj z późniejszymi świecami bez korzystania z informacji przyszłych. Sam trafny kierunek nie dowodzi zyskownej transakcji.')

with macro_tab:
    st.subheader('FED i wydarzenia międzynarodowe')
    st.markdown('**Oficjalne kalendarze:** [FOMC](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) · [komunikaty FED](https://www.federalreserve.gov/newsevents/pressreleases.htm) · [CPI](https://www.bls.gov/schedule/news_release/cpi.htm) · [NFP](https://www.bls.gov/schedule/news_release/empsit.htm)')
    st.info('Kalendarz i wydarzenia X nie są pobierane automatycznie. Nie pokazuję niezweryfikowanych terminów ani rzekomych newsów.')
    if st.checkbox('Ważne wydarzenie w ciągu 2 godzin lub w trakcie'):st.error('Wstrzymaj nowe scenariusze i oceń płynność oraz zmienność po wydarzeniu.')
    else:st.warning('Status wydarzeń: niezweryfikowany — brak zaznaczenia nie oznacza braku wydarzeń.')

with risk_tab:
    st.subheader('Kalkulator ryzyka — symulacja')
    c1,c2,c3=st.columns(3)
    capital=c1.number_input('Kapitał (USDT)',min_value=10.0,value=1000.0,step=100.0)
    risk=c2.number_input('Ryzyko (%)',min_value=.1,max_value=5.0,value=.5,step=.1)
    stop=c3.number_input('Stop (%)',min_value=.1,max_value=30.0,value=1.5,step=.1)
    costs=st.number_input('Koszty + poślizg (%)',min_value=0.0,max_value=5.0,value=.2,step=.05)
    budget=capital*risk/100;notional=budget/((stop+costs)/100)
    st.metric('Budżet straty',f'{budget:.2f} USDT');st.metric('Orientacyjna wartość pozycji',f'{notional:.2f} USDT')
    st.caption('Szacunek bez likwidacji, funding, luk cenowych i skoków spreadu. Nie składamy prawdziwych zleceń.')
