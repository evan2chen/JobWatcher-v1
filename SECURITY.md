# Security

## Collectors run arbitrary code with your privileges

A collector is whatever command you register with `jw source add --command`. `jw` runs it
as a subprocess and trusts its stdout — there is no sandbox. Only register a collector
whose code you've read, the same way you'd only run any other script you download.

A collector's subprocess does not inherit your full environment. It sees a fixed
allowlist (`PATH`, proxy settings, locale, temp directories — see `BASE_ENV` in
`jw/runner.py`) plus whatever you explicitly pass through with `--env NAME` on
`jw source add`. Secrets you haven't listed there stay out of a collector's reach.

## The write API needs a token off loopback

`jw serve` binds to `127.0.0.1` by default, where no token is required — nothing outside
this machine can reach it. Binding to any other address without setting `JW_API_TOKEN`
is refused outright. If you do expose it beyond loopback, set `JW_API_TOKEN` and treat it
as a real secret: anyone with it can write to your store over `jw serve`'s API.

## Reporting a vulnerability

Open an issue, or email the address in the repository's profile if the report shouldn't be
public yet.
