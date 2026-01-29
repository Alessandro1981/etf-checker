# ETF Checker – Home Assistant Add-on

Questo repository ora contiene un add-on per Home Assistant / Hass.io che:

- monitora l'andamento di una lista di ETF fornita dall'utente dopo l'installazione;
- applica **una soglia percentuale unica** a tutti gli ETF;
- invia alert tramite l'app Companion (via `notify.mobile_app_*`) quando la variazione rispetto al baseline supera la soglia.

I prezzi vengono letti tramite l'endpoint pubblico di Yahoo Finance, evitando dipendenze pesanti durante la build dell'add-on.

L'immagine Docker crea un virtual environment (`/opt/venv`) per aggirare le restrizioni PEP 668 delle nuove immagini base Home Assistant.

## Come funziona la soglia

Per ogni ETF viene salvato un **baseline** (prezzo di riferimento):

1. al primo polling disponibile, il baseline viene impostato al prezzo corrente;
2. quando la variazione percentuale rispetto al baseline supera la soglia, viene inviata una notifica;
3. dopo l'alert, il baseline viene aggiornato al nuovo prezzo per evitare spam continuo.

## Configurazione (opzioni add-on)

Le opzioni principali sono in `etf_checker/config.json` (scheda "Configuration" dell'add-on):

- `homeassistant_url`: di default `http://supervisor/core`;
- `homeassistant_token`: **token long-lived** di Home Assistant;
- `notify_service`: ad esempio `notify/mobile_app_mio_telefono`;
- `alpha_vantage_api_key`: API key Alpha Vantage (facoltativa, se impostata viene usata come prima fonte prezzi);
- `finnhub_api_key`: API key Finnhub (facoltativa, usata come fonte secondaria);
- `poll_interval_seconds`: intervallo di polling (min 60s);
- `default_threshold_percent`: soglia di default usata dalla UI;
- `log_level`: verbosità dei log (`DEBUG`, `INFO`, `WARNING`, `ERROR`).

## Configurazione post-installazione (UI add-on)

La UI ingress dell'add-on permette di impostare:

- lista ETF (separati da virgola, es. `SWDA.MI, CSPX.MI`);
- soglia percentuale comune.

Questa configurazione viene salvata in `/data/ui_config.json`.

## Sviluppo locale rapido

Esempio (fuori da HA) per testare velocemente:

```bash
cd etf_checker
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pytest
LOG_LEVEL=DEBUG PORT=8099 python -m app.main
```

Poi apri: <http://localhost:8099>

> Nota: per inviare notifiche reali serve un Home Assistant raggiungibile e un token valido.
