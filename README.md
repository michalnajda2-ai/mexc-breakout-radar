# MEXC Breakout Radar v1.4

Nowy moduł „Futures LONG — lista obserwacyjna na 24h” ma dwa oddzielne rankingi: pary spot z historią 3–49 dni i starsze. Ranking filtruje kontrakty futures po obrocie, spreadzie, funding rate i strukturze spot. Nie jest prawdopodobieństwem ani gwarancją wzrostu. Nie składa zleceń, nie używa API key.

Wiek młodych par jest szacowany z pierwszej dostępnej świecy spot, a nie oficjalnej daty listingu. Starsze pary mogą mieć historię sprzed 100 dni (oznaczenie 50+). Ranking oparty jest na danych dziennych i migawce futures, dlatego **nie jest zweryfikowanym modelem prognozy 24h**. Przed użyciem na realnym kapitale wymagany backtest bez look-ahead, test out-of-sample i symulacja kosztów/fundingu.

## Aktualizacja Streamlit Cloud
Zastąp `app.py`, `requirements.txt` w repozytorium GitHub. Streamlit automatycznie zrestartuje aplikację. Uruchom skaner LONG na dole strony. Bez automatycznego tradingu.
