# CheckoutGuard: An Unattended E-Commerce Health Monitor

**By Abdulmalik Abdulsamad** 

## The problem

Every e-commerce site eventually breaks in a small way that no one notices right away: a checkout button stops responding after a deploy, a sort filter quietly stops sorting, a social link starts 404. None of these send an alert on their own. They just sit there costing sales, sometimes for hours, until a customer complains, or someone happens to click through the flow by hand and notices.

Manual QA doesn't scale to "check this every hour, forever." That's a job for automation, and it's the exact job I set out to build.

## The brief I set for myself

Rather than wait for a paying client to hand me this exact problem, I built it against [SauceDemo](https://www.saucedemo.com); a public e-commerce QA sandbox used industry-wide for exactly this kind of practice. It's designed with real, intentional bugs baked into two of its four test accounts, which meant I could prove something a demo with only "happy path" accounts never could: **that the monitor correctly tells the difference between a genuine failure and an expected one**, instead of just reporting green across the board.

The brief I held myself to: build something I'd actually be comfortable handing to a paying client and letting run unattended, not something that only works when I'm watching it.

## The approach

I built this in four stages, each one only starting once the previous one was proven with real evidence not just "the code looks right," but actual logs from actual runs.

1. **Authentication and evidence capture.** Classify every login outcome three ways; genuine success, an expected failure (a deliberately locked account), or a truly unexpected one and prove it with a timestamped, full-page screenshot every time.

2. **The purchase funnel.** Sort verification by reading real prices back from the page, a full add-to-cart → checkout → confirmation flow, a total price cross-checked against an 8% VAT calculation, and the order receipt downloaded as proof of purchase.

3. **Reliability.** Session reuse to avoid re-logging in on every run, retry-with-backoff for genuinely transient failures and a hard rule that the actual checkout submission is *never* retried, because retrying a real purchase risks placing it twice. Failure-only trace capture, so evidence only piles up when something's actually wrong.

4. **Unattended operation.** A GitHub Actions workflow running the whole thing on an hourly schedule, with automatic GitHub Issue alerts on failure deduplicated, so an outage that lasts six hours creates one issue, not six.

## The result

A monitor that runs on a fixed hourly schedule with no server to maintain and no human watching it, and correctly distinguishes three outcomes across four accounts every time it runs: real success, expected failure, and genuine defect.

**The most honest proof point isn't a screenshot I staged, it's a bug the system caught on its own.** Partway through building the CI pipeline, a missing dependency (`python-dotenv` wasn't pinned in `requirements.txt`) caused a real, unplanned failure in a scheduled run. The alerting system did exactly what it was built to do: it opened a GitHub Issue automatically, linked directly to the failing run, and attached the downloadable evidence without me touching anything. That's not a demo I rehearsed. That's the system doing its job the first time it actually mattered.

Along the way, the monitor also correctly flagged two real, intentional defects built into SauceDemo's own test accounts, a broken price sort and a checkout flow that hangs on step two every single run, with no false positives on the accounts that work correctly.
s
## Tools

Python, Playwright (sync API), pytest (fully offline test suite using static page doubles), GitHub Actions, dataclass-based structured reporting.

## What I can build for you

If your checkout, signup, or booking flow could break silently and you wouldn't know until a customer told you — that's the exact gap this closes. I can build the same kind of unattended monitoring against your real flow: scheduled checks, evidence on failure, and an alert wherever your team already looks (GitHub, Slack, email).

contact me: **<malikings44@gmail.com>** 