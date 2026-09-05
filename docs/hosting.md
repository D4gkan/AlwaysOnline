# Hosting research and recommendation (checked August 2026)

This system needs a host that can run a **persistent, visible-mode
Chromium process per browser window** (10 windows at 5 accounts, 40+ at
20 accounts) continuously, 24/7, without sleeping or being torn down for
inactivity. That workload profile — long-lived processes, meaningful RAM,
no idle timeout — rules out most "serverless" and PaaS free tiers outright.

## What was ruled out and why

- **Vercel / Netlify free tiers** — function-based, short execution
  timeouts (seconds, not days), no persistent background processes, no
  way to keep a Chromium instance alive between requests. Fine for
  static sites/APIs, wrong shape for this workload entirely.
- **Railway free tier** — real persistent containers, but the free
  allowance is a small monthly credit ($1/mo after the first month) that
  is exhausted quickly by a 24/7 multi-browser workload; services pause
  once credit runs out.
- **Azure App Service (F1 free tier)** — explicitly sleeps after ~20
  minutes idle and has a hard 60 min/day compute cap; incompatible with
  "always online."
- **Google Cloud e2-micro (Compute Engine always-free)** — genuinely
  always-on and free, but only ~1 GB RAM. A single visible Chromium
  window commonly uses 300–500 MB; this tier fits perhaps one account's
  worth of browsers at most and leaves no headroom for growth toward 20
  accounts.
- **Oracle Cloud "free" x86 micro VMs** — technically always-free, but
  only 1 GB RAM each (same problem as GCP e2-micro), and community
  reports describe aggressive idle-based reclamation on low-traffic
  instances.

## Recommended: Oracle Cloud "Always Free" Ampere A1 (ARM) VM

Oracle's Always Free tier includes ARM-based Ampere A1 compute — up to 4
OCPUs and 24 GB RAM, usable as one VM or split across several, with no
time limit on the free allocation and generous outbound transfer.

Why it fits this workload specifically:

- **24 GB RAM** comfortably covers 5 accounts × 2 windows now, and has
  real headroom toward 20 accounts × 2 windows later (budget roughly
  300–500 MB per Chromium window plus OS/Python overhead — see the sizing
  note below).
- **Always-free, no expiry** — unlike 12-month trial credits (Azure,
  AWS), this allocation doesn't convert to paid billing on a timer.
- **It's a real Linux VM** — systemd, Xvfb, and Playwright all work
  exactly as documented; no PaaS-specific rewiring needed.
- **The workload itself helps avoid idle reclamation.** Oracle has been
  reported to reclaim VMs that sit at near-zero CPU/network utilization
  for extended periods. A monitor that's actively polling multiple pages
  every few minutes is not an idle VM in the way a dormant hobby VM is,
  which reduces (though doesn't eliminate) this risk. Document this
  explicitly rather than assume it away.

Tradeoffs to flag honestly:

- **ARM architecture.** Playwright's Chromium build supports Linux ARM64,
  but confirm compatibility during setup (`playwright install --with-deps
  chromium` on Ubuntu ARM64) since ARM support has historically lagged
  slightly behind x86 in some tooling. Budget time for this in the
  install step rather than assuming it's identical to x86.
- **Idle reclamation is a real, reported risk** on Oracle's free tier in
  general, even if less likely for an active workload. Don't treat this
  as a guaranteed-forever host without monitoring it.
- **Account creation friction.** Oracle's signup/verification process has
  a reputation for being stricter than other providers'; this is a
  one-time cost, not an ongoing one.

## Realistic fallback options (in priority order)

1. **A spare Linux machine or mini-PC you already own, left running.**
   Zero cost, zero platform risk, full control. This is the most reliable
   option if you have the hardware, and is what the architecture assumes
   by default (systemd unit + Xvfb).
2. **Oracle Cloud Always Free Ampere A1** (recommended above) if you want
   a cloud VM at no ongoing cost.
3. **A small paid VPS (~$4–6/month)** from any mainstream provider once
   you scale toward 20 accounts and need guaranteed, non-reclaimable
   resources. At that point the reliability of a paid box outweighs the
   free-tier savings — say this plainly to the operator rather than
   over-selling the free options.

## Sizing guidance as you scale

| Accounts | Browser windows | Rough RAM budget |
|---|---|---|
| 5  | 10 | ~4–6 GB  |
| 10 | 20 | ~8–12 GB |
| 20 | 40 | ~16–24 GB |

These are rough planning numbers (Chromium RAM usage varies with page
content); measure actual usage on your target host with `top`/`htop`
once a few accounts are running, and treat the free-tier ceiling as a
signal to move to a paid VPS rather than something to fight past with
aggressive tuning.

## Bottom line

Default the architecture to **any systemd-managed Linux host** (own
hardware first, Oracle Ampere A1 Always Free second, small paid VPS once
you outgrow either). Avoid hard-coding a specific provider's free tier as
a permanent assumption — free-tier terms change, and this document should
be revisited periodically rather than trusted indefinitely.
