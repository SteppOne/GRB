# GRB — feed news di AleBot

Repository pubblico di servizio. Il progetto principale è privato.

| File | Cos'è |
|---|---|
| `news.json` | Il calendario economico, aggiornato da solo ogni 15 minuti da GitHub Actions. Non va modificato a mano: viene riscritto dal job. |
| `news_fetcher.py` | Lo script che scarica il calendario e scrive `news.json`. Le chiavi API stanno nei Secrets del repository, non nei file. |
| `.github/workflows/news.yml` | Il job pianificato che esegue `news_fetcher.py`. |
| `alebot_v*.zip` | Il pacchetto di aggiornamento che le installazioni scaricano con `/aggiorna`, verificato con SHA-256. |
