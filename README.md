# CheckoutGuard Monitor

[![CheckoutGuard Monitor](https://github.com/malik-automates/checkoutguard/actions/workflows/monitor.yml/badge.svg)](https://github.com/malik-automates/checkoutguard/actions/workflows/monitor.yml)

**📄 [Read the full case study](docs/case_study.md)** the build story, the design decisions, and a real bug the alerting system caught on its own.

## The problem this solves

A broken checkout page doesn't send an email. It doesn't set off an alarm. It just sits there, quietly costing sales, until a customer complains or someone happens to test it by hand often hours or days later. Manual QA doesn't scale to "check this every hour, forever, and tell me the moment something's wrong."

**CheckoutGuard is an unattended monitor that does exactly that.** It logs in, sorts products, adds items to a cart, completes a full purchase, downloads the receipt, and checks that the footer links actually work every hour, automatically, with zero human involvement and opens a GitHub Issue the instant something breaks.

## What it actually checks

- **Login, classified three ways** a real success, an *expected* failure (a deliberately locked account), or a genuinely unexpected failure. Each is reported differently, because "the site is down" and "this account is supposed to be locked" are not the same problem.

- **Product sort, verified by reading real prices back from the page** not by trusting that a dropdown click "worked."

- **The full purchase funnel** cart contents matched against what was actually clicked, checkout form submission, total price cross-checked against an 8% VAT calculation, confirmation message asserted exactly, and the order receipt PDF downloaded and saved as proof.

- **Footer link health** each social link opened in its own new tab, verified against its real destination domain (not just "a tab opened"), and closed cleanly whether it passed or failed.

## Why this isn't just "a test suite that runs on a schedule"

- **Retries are targeted, not blanket.** Transient issues (a slow page load, a flaky click) get retried with exponential backoff. The actual order submission is **never** retried. Retrying a real purchase risks placing it twice, and that's a worse outcome than a single failed check.

- **One broken account can't take down the whole run.** Every account is isolated. If one login fails, the other three still get fully tested and reported.

- **Evidence is captured only when it's needed.** A full Playwright trace and screenshots are recorded during every run, but only saved if something actually fails, discarded otherwise, so you're not drowning in noise on the 99% of runs that pass.

- **Failures alert themselves.** A failed run automatically opens a GitHub Issue with a direct link to the failing run and its downloadable evidence with deduplication, so a multi-hour outage creates one issue, not twenty.

- **The logic is tested without touching the internet.** A pytest suite runs against static page doubles, full offline coverage of the sorting, cart-matching, and price logic in a fraction of a second, no live site required.

## Tech stack

Python · Playwright (sync API) · pytest · GitHub Actions · dataclass-based structured reporting

## Quick start

```bash
git clone https://github.com/malik-automates/checkoutguard.git
cd checkoutguard
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
playwright install --with-deps chromium
cp .env.example .env   # fill in your own values
python run_monitor.py
```

Run the offline test suite (no network needed):
```bash
pytest tests/ -v
```

## Project structure

```
src/
  auth.py       — login, session reuse, retry-hardened authentication
  checks.py     — the funnel: sort, cart, checkout, receipt, footer links
  command.py    — the CLI for controlling the scripts
  core/         — config, logging, retry policy
  report.py     — structured per-account results
run_monitor.py  — CLI entry point and orchestration
tests/          — offline pytest suite (static page doubles)
.github/workflows/monitor.yml — scheduled + on-demand CI run
```

## The full story

This repo is built as a portfolio demonstration against [SauceDemo](https://www.saucedemo.com), a public e-commerce QA sandbox, the same site QA engineers use industry-wide to practice exactly this kind of testing. Two of its four test accounts are *intentionally* broken (a locked account, and one with deliberately buggy sort/checkout behavior), which made it possible to prove the monitor correctly tells the difference between "this is a real bug" and "this is expected."

Read the full build breakdown, including a real failure the alerting system caught on its own during development, in [`docs/case_study.md`](docs/case_study.md).

## Available for hire

I build monitoring like this for real checkout, signup, and booking flows, tell me what breaks silently in your product, and I'll show you how this gets built for it.

contact me: **<malikings44@gmail.com>** 