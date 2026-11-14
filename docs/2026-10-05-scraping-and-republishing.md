# USJ Ticket Prices: Scraping & Republishing Research

Research notes from 2026-10-05 on whether the per-day Universal Studios Japan
(USJ) ticket prices (adult / child / senior) shown on https://www.usjticketing.com/
can be scraped and republished elsewhere online.

> Not legal advice. This is a summary of what the sites say and how the relevant
> laws generally work. Talk to a Japanese or Hong Kong IP lawyer before
> monetizing or publishing at scale.

## TL;DR

- **Probably fine** to republish the prices themselves (date, ticket type, price)
  in your own format. Prices are facts, and facts aren't protected by copyright.
- **No terms restrict it.** Neither the site's Terms of Use, its Privacy Policy
  nor its API contains anything about scraping, automated access or republishing.
- **Don't copy anything beyond the numbers:** text, photos, logos, page design or
  screenshots.
- **usjticketing.com is USJ's official English web ticket store** (USJ's own site
  links to it), so these are effectively USJ's official prices.

## Who runs the site

- Operator: **JTRweb Limited** (Hong Kong, Registered No. 1978412), described as
  an "authorized ticket reseller of Universal Studios Japan".
- Registered office: Room 2A, 14/F, Chun Wo Comm Ctr, 23-29 Wing Wo Street,
  Central, Hong Kong.
- The Terms of Use are governed by Hong Kong law.
- USJ's official English tickets page (https://www.usj.co.jp/web/en/us/tickets)
  labels its link to usjticketing.com **"Official Web Ticket Store"**.

## Terms and policies checked

| Source | Location | Restricts scraping/republishing? |
| --- | --- | --- |
| Terms of Use | https://www.usjticketing.com/articleContent/terms_service | No. Covers ticket purchases only (prices, payment, refunds, liability). |
| Privacy Policy | `/articleContent/privacy_policy` | No. Covers personal data and cookies only. |
| Legal notice (Act on Specified Commercial Transactions) | `/articleContent/notation` | No. Seller details, payment and cancellation rules. |
| Copyrights and trademarks (footer link) | https://www.usj.co.jp/web/en/us/copyright-notice | No. Just a list of credits for characters and brands (Harry Potter, Nintendo, Minions, etc.). |
| robots.txt | `/robots.txt` | None exists. The URL returns the app's home page. |
| API docs or terms | `/api/docs`, `/api/terms`, `swagger.json`, `openapi.json`, `security.txt`, etc. | None exist. Each returns a blank page or the home page. |
| API responses and headers | `/api/product/search`, `/api/common/config` | No license, copyright or terms fields. |

A separate business-partner login exists (`/partner`, `/bLogin`). Partners
probably sign their own agreement with JTRweb, but that only matters if you sign
up as one.

**No terms isn't the same as permission.** It only means no contract limits you.
To be certain, email JTRweb and ask.

## Legal reasoning (why the prices are likely fine)

- **US:** Facts aren't copyrightable (*Feist v. Rural*, 1991).
- **Japan:** Copyright protects creative expression (Copyright Act Art. 2(1)(i)).
  A database is protected only if how its contents are chosen or organized is
  creative (Art. 12-2). A price-per-date calendar isn't.
- **Hong Kong:** The bar for copyright is lower ("skill and labour"), but a claim
  over a machine-generated price list would still be weak.
- **Japan's Unfair Competition Prevention Act** (限定提供データ): only protects
  data behind access controls, not public prices.
- **EU database right:** shouldn't apply, because the site's operator isn't based
  in the EU.

## Risks and how to avoid them

1. **Copying more than the numbers.** Descriptions, photos, character images,
   logos, page design and screenshots are copyrighted (many by Universal,
   Nintendo, Warner Bros., etc.). Show the data in your own table or chart.
2. **Trademarks.** Using "Universal Studios Japan" or "1 Day Studio Pass" to
   describe what the prices are for is fine. Don't use their logos or suggest
   you're official or affiliated. Add a line saying you're not affiliated.
3. **How you scrape.** Use only public pages and the API, never log in, keep
   your request rate low and cache results. Cautionary case: Librahack (2010,
   Okazaki City Library), where a man was arrested (though not prosecuted)
   after his scraper overloaded a server. The site also runs bot-detection
   code (`travel.fraudprevention.jp`).
4. **Accuracy.** The Terms say prices change without notice. Show when you
   collected the data, name the source and say you're not affiliated. This
   matters more if the page earns money, because Japan has rules against
   misleading price claims.
5. **Terms can change.** Check the Terms of Use again before launch and every so
   often after.

## Technical notes

- The site is a single-page Vue app. The HTML is just a shell, so plain
  `curl`/WebFetch of a page returns no content.
- API base URL: `https://www.usjticketing.com/api` (send header `lang: en-US`).
- Rate limit headers: `X-Rate-Limit-Limit: 100`, with a reset of a few seconds.
  Stay well under this.
- `Access-Control-Allow-Origin: *` (a technical setting, not permission to reuse
  the data).
- Endpoints:
  - `GET /site/article?id=<terms_service|privacy_policy|notation>`: legal
    pages as HTML (called)
  - `GET /product/search`: product listing (called; returns JSON with
    `status`, `msg`, `data`)
  - `GET /product/sku`, `POST /product/sku-price`, `GET /product/detail`:
    likely where the per-day and per-category prices come from (found in the
    JS bundle, **not called yet**)

## Where USJ's official prices are

| Source | URL | What it shows |
| --- | --- | --- |
| English tickets page | https://www.usj.co.jp/web/en/us/tickets | No prices. Links to usjticketing.com as the "Official Web Ticket Store". |
| Japanese ticket lineup | https://www.usj.co.jp/web/ja/jp/tickets/lineup | Starting prices only. 1 Day Studio Pass: adult ¥8,400~, child ¥5,500~, senior ¥7,600~ (matches usjticketing.com). |
| Japanese web ticket store | https://store.usj.co.jp/ja/jp/c/ticket | Day-by-day prices. Behind a waiting-room queue that screens for bots, so harder to scrape. Its terms were **not checked**. |
| English web ticket store | https://www.usjticketing.com/ | Day-by-day prices (the site being researched). |
