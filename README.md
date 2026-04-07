# Megekko daily price tracker

This repo runs a GitHub Actions workflow every day and calculates the live total price of your selected Megekko parts.

## What it does

- fetches each product page from Megekko
- extracts the current price
- sums the prices
- writes:
  - `output/price_report.json`
  - `output/price_report.md`
- uploads the report as a workflow artifact
- commits updated output files back to the repo

## Why it tracks product pages instead of the cart page

A shopping cart is usually session-based and can require cookies, login state, or anti-bot protections. Product pages are much more stable for unattended daily checks in GitHub Actions.

## Files

- `products.json` list of products to track
- `scraper.py` scraper and report generator
- `.github/workflows/daily-price-check.yml` scheduled GitHub Actions workflow

## Change the schedule

The workflow currently runs daily at `06:00 UTC`.

Edit this line in `.github/workflows/daily-price-check.yml`:

```yaml
schedule:
  - cron: '0 6 * * *'
```

GitHub Actions scheduled workflows use POSIX cron syntax and run in UTC by default. Manual runs via `workflow_dispatch` are also supported. citeturn746724search3turn746724search8

## How to use

1. Create a GitHub repo.
2. Upload all files from this package.
3. Push to your default branch, ideally `main`.
4. Go to **Actions** and run **Daily Megekko Price Check** once manually.
5. After the first run, check `output/price_report.md` in the repo.

## Notes

- If a product becomes unavailable, the script will mark it as unavailable and exclude it from the total.
- If Megekko changes its HTML structure, you may need to adjust the selectors in `scraper.py`.
