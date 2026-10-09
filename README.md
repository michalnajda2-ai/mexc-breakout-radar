# MEXC Breakout Radar v1.2

Polskojęzyczna aplikacja Streamlit do przesiewania par spot USDT na MEXC pod kątem wczesnych setupów wybiciowych. Nie jest botem tradingowym i nie składa zleceń.

## Co zawiera v1.2

- Skanowanie płynnych par MEXC USDT na podstawie publicznego API.
- Analiza 49 zamkniętych świec dziennych (około 7 tygodni): wolumen, momentum, trend dołków, odległość od szczytu i zmienność.
- Porównanie średniego wolumenu ostatnich 7 dni z wcześniejszymi 7 dniami oraz ostatniej zamkniętej sesji z poprzednią średnią 7D.
- Wzbogacenie przez CoinGecko: kapitalizacja, FDV, podaż obiegowa/maksymalna, ranking i wolumen.
- Ranking techniczny oraz proxy rynkowo-fundamentalne; flagi ryzyka i krótkie wyjaśnienie rankingu.
- Pole do ręcznej analizy dowolnej pary, wykres ceny i matematyczne poziomy +100%, +200%, +300%.
- Checklista fundamentalna do samodzielnej oceny zespołu, produktu, trakcji, społeczności/narracji, tokenomii i transparentności.
- Ręczne pola na unlocki w 30/90 dni z karą punktową oraz eksport checklisty.
- Opcjonalne pobranie TVL i przybliżonej zmiany TVL w 30 dni z publicznego API DefiLlama po podaniu prawidłowego sluga protokołu.
- Eksport wyników skanu do CSV.

## Uruchomienie

Wymagany Python 3.10+.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

Aplikacja nie wymaga klucza API dla podstawowych danych MEXC, CoinGecko public API ani publicznego endpointu TVL DefiLlama. Zewnętrzne API mogą ograniczać liczbę zapytań lub zmieniać dostępność.

## Jak czytać wyniki

- **Wynik techniczny** mierzy podobieństwo do wybranego setupu, a nie szansę sukcesu.
- **Proxy fundamentalne CoinGecko** jest uproszczonym wskaźnikiem market cap, FDV/MC, płynności i rankingu; nie ocenia automatycznie jakości projektu.
- **Checklista fundamentalna** jest osobnym, ręcznym modułem. Zbadaj oficjalną dokumentację, audyty, działający produkt, realne użycie, przychody, zespół i wiarygodność komunikatów.
- **Unlocki** trzeba weryfikować w dokumentacji tokenomii oraz wiarygodnym kalendarzu. Publiczne API DefiLlama nie udostępnia wszystkich danych unlocków bezpłatnie; dlatego pola unlocków są ręczne, nie zmyślamy brakujących wartości.
- TVL jest miarą środków w protokole, nie dowodem wartości tokena. Slug DefiLlama trzeba dopasować do właściwego projektu.
- Mapowanie tokenów po symbolu CoinGecko może być niejednoznaczne, zwłaszcza przy symbolach współdzielonych. Sprawdź ID i dane przed decyzją.
- Poziomy +200% i +300% to odpowiednio 3× i 4× obecnej ceny, wyłącznie matematyczne scenariusze.

## Proponowany workflow

1. Uruchom skan i sortuj po wyniku końcowym.
2. Preferuj wzrost wolumenu potwierdzony przez kilka sesji, umiarkowaną zmianę ceny i cenę blisko szczytu zakresu — unikaj gonienia świecy po pionowym ruchu.
3. Otwórz parę ręcznie, sprawdź wykres i płynność na MEXC.
4. Uzupełnij checklistę: zespół, produkt, trakcja, tokenomia, unlocki, audyty i newsy.
5. Zapisz CSV/checklistę. Nie traktuj wysokiego score jako sygnału kupna bez dalszej weryfikacji.

## Zastrzeżenie

Kryptowaluty o małej kapitalizacji są skrajnie zmienne i mogą stracić większość wartości lub mieć niewystarczającą płynność. Aplikacja nie jest poradą inwestycyjną, nie prognozuje wiarygodnie przyszłego zwrotu i nie gwarantuje +200%/+300%.
