# MPS Shortfall

Lists NSE main-board companies whose latest filed public shareholding is below 25%. For each one it shows the sale, in rupee crore, that would close the gap, and the date by which the current minimum-public-shareholding rules say the company has to get there.

Public % is the Public (B) figure NSE publishes on its shareholding-pattern filings. The sale uses the latest cash close and the share count in that filing. Deadlines follow Rule 19(2)(b) as substituted on 13 March 2026 (G.S.R. 184(E)) and Rule 19A of the Securities Contracts (Regulation) Rules, 1957. The size band uses today's market cap in place of post-issue capital at the offer price.

```
python app.py
```

Open http://127.0.0.1:5050 and choose Fetch from NSE. The run takes a few minutes. Download Excel writes the same rows.

Production: `python serve.py` (uses `PORT`, default 8080). `render.yaml` builds the Docker image.
