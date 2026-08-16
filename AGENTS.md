# AGENTS.md

Instructions for any AI agent working in this repository.

## What this project is

A watcher for the Argentine metal gig listing at https://metaldazeweb.com/agenda/.

It runs hourly from cron, parses every show on the page, and fires a desktop notification for shows that were not there last time.

Shows on a watchlist get two extra notifications: when their tickets go on sale, and when their date, time or venue changes.

## The one rule that matters

**Guido does not run this from the terminal. He asks you to run it for him.**

When he says he is interested in a show, or wants to be told when its tickets come out, run the watch command yourself and report the result.

Always pass `--pick` so the command never stops to ask a question:

```bash
cd /home/guido/Desktop/Otros/MetalNotifications
python3 monitor.py watch alcest --pick all
```

If several shows match and you cannot tell which one he means, run the search first, show him the numbered list, and ask which one before picking.

## Commands

All of these are run from the project directory.

| Intent | Command |
|---|---|
| Watch a show | `python3 monitor.py watch <band, venue or city> --pick <numbers\|all>` |
| Stop watching | `python3 monitor.py unwatch <band, venue or city> --pick <numbers\|all>` |
| What is he waiting on | `python3 monitor.py list` |
| Check the site now | `python3 monitor.py` |
| Rebuild the dashboard only | `python3 monitor.py dashboard` |

`watch` and `unwatch` search band name, venue and city together, ignoring case and accents.

`--pick` takes `1`, `1,3` or `all`, numbered as the command prints the matches.

Watching a show whose tickets are already on sale does not add it to the watchlist. The command prints the ticket link instead, which is usually what he actually wanted.

## Things not to do

Never delete or hand-edit `known_shows.json`. Deleting it makes the next run treat the whole agenda as already seen, so genuinely new shows are swallowed silently. If you need a clean slate for testing, copy `monitor.py` to a scratch directory and run it there, since every path is resolved relative to the script.

Never fire test notifications at his screen without telling him first. Any command that notifies pops a window over whatever he is doing.

Do not commit the state files. `.gitignore` already covers them. The single exception is `genres.json`, which is tracked on purpose, for the reason given under "Where genres come from".

## How it works, in the order it matters

Each show gets a key of band, date, time, venue and city. A show whose key was not in `known_shows.json` last run is new.

Because that key holds the date and venue, a correction on the site would look like one show vanished and another appeared. Shows are therefore paired by permalink first, and only counted as new when no pairing exists. See `detect_moves()`.

The agenda repeats its nearest few shows in a second block, so `parse_shows()` returns more blocks than there are shows: 145 blocks for 140 real shows at the time of writing. Everything downstream is keyed by show identity so the duplicates collapse on their own, but do not report the raw block count as a show count.

The agenda page states ticket availability directly. A show either carries a ticket link, or carries a status label instead: "Entradas próximamente", "Sold out", "Ver flyer", "Gratis", "Comunicate con la banda". Tickets going on sale means a watched show gained a link.

Notifications carry the show flyer, taken from the thumbnail already embedded in the listing and cached in `images/`.

Notifications with a button need a helper process, because `notify-send --action` blocks until the notification is closed. The script re-executes itself as `_await_click` in a detached process, which reads a payload from `.pending/` and acts on the click. On a click `notify-send` prints the action name, on a plain dismiss it prints only the notification id. That difference is the whole mechanism.

Helpers older than 14 days are killed on the next run, and no more than 20 wait at once. Beyond that, notifications are sent without a button.

## The dashboard

Every run regenerates `dashboard.html`: one card per show with the flyer, the
band's genre and country, and the price. Open it in a browser at
`file:///home/guido/Desktop/Otros/MetalNotifications/dashboard.html`.

The card carries exactly two links: the band name points at Metal Archives, the
flyer at the ticket page. That is why a single-band card prints the name only
once, in the heading, and shows just genre and country below it. Cards billing
several bands keep a name per act, since each needs its own link.

Favourites are a star per **band**, so starring NEPAL marks all of its shows and
any future one. They live in the browser's `localStorage`, which means they are
per browser and survive every rebuild, since the cron only rewrites the HTML.
They are deliberately **not** connected to `watchlist.json`: ticket alerts still
come only from `monitor.py watch`.

Shows that already happened are never deleted. They fall off the agenda, but
`dashboard_archive.json` keeps them and they render greyed out behind the "Ver
pasados" filter.

### Hiding a place

`EXCLUIR_CIUDADES` in `dashboard.py` lists places Guido will not travel to,
matched against the show's city ignoring case and accents. It currently holds
`chubut` and `santa cruz`, which between them cover Comodoro Rivadavia, Puerto
Madryn and Pico Truncado.

The list does two things: those shows are left out of the dashboard, and they
never fire a new-show notification. `monitor.py` reads it through
`dashboard.excluido()` and falls back to notifying if that import ever breaks,
because a broken filter must never silently mute alerts.

Watchlist alerts are deliberately not filtered. Asking to be told when a show's
tickets drop is an explicit choice, so distance is Guido's problem there.

Filtering happens at render time and the shows stay in the archive, so removing
an entry brings them straight back. Do not "delete" unwanted shows from the
archive instead: they are still on the agenda, so the next run re-adds them.

### Testing the dashboard

Nothing about the filters can be verified by reading the HTML: they are CSS and
JavaScript behaviour. The Chrome extension is not connected on this machine, so
drive the page with Playwright against the local file instead. It cannot get
past Cloudflare, but a `file://` URL is no problem.

```python
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    p = b.new_page(viewport={"width": 1400, "height": 1100})
    p.goto("file:///home/guido/Desktop/Otros/MetalNotifications/dashboard.html")
    p.wait_for_selector(".card")
    vis = lambda: p.eval_on_selector_all(
        ".card", "e => e.filter(x => x.offsetParent !== null).length")
    p.click('.card[data-band="AMORPHIS"] .fav')
    p.click("#soloFav")
    print(vis())          # must be 1, not 132
```

Count with `offsetParent !== null`, not by counting `[hidden]` attributes: the
bug that broke the filters set the attribute correctly and the cards stayed on
screen anyway.

When checking that flyers load, force `loading="eager"` on every `img` and wait
first. Otherwise the images below the fold report as broken when they are merely
lazy, which looks alarming and means nothing.

### Two traps that already bit once

**Do not give `.card` a `display` rule without keeping `.card[hidden]`.** The
filters hide cards by setting the `hidden` property, which relies on the
browser's `[hidden]{display:none}`. Any author rule setting `display` on `.card`
beats it, so the cards stay visible and every filter silently does nothing. The
CSS carries `.card[hidden]{display:none}` for exactly this reason.

**Never call `dashboard.rebuild()` with a stub `cache_image`.** Passing
something that returns `None` rewrites the page with every flyer missing, and it
looks like an image bug rather than a caller mistake. Go through
`monitor.py dashboard`. `rebuild()` now logs a WARNING when it writes zero
flyers for shows that have one.

### Where genres come from

`genres.json` maps an agenda title to its bands, each with genre, country,
source and a note. It is keyed by the title exactly as the agenda writes it.

Two sources, and the card shows which one with an `MA` or `SoM` badge:

* **Metal Archives** (`MA`), far better data, including the historical split
  `Thrash Metal (early); Groove Metal (later)`. The site sits behind a
  Cloudflare challenge that **no HTTP client gets past** — plain urllib, curl,
  curl_cffi with 15 impersonation profiles, WebFetch, and Playwright headless
  and headful were all tried and all got 403. The only way in is a real browser
  session, so this data was harvested by hand: paste `ma_snippet.js` into the
  Firefox console on metal-archives.com, then run `seed_genres.py` on the
  `ma-genres.json` it downloads. Do not promise Guido automated MA lookups.
* **Spirit of Metal** (`SoM`), reachable over plain HTTP, so this is what runs
  from cron for bands that appear later. Coarser (`Thrash Black`, `Death Grind`)
  and it has no historical field.

`ma_snippet.js` has the band list of the day it was generated baked into it. A
fresh harvest needs the list rebuilt from the current agenda first, otherwise it
queries yesterday's bands.

Spirit of Metal's search lives at `/find.php?l=en&nom=<name>`; there is no
endpoint under `/en/search/…`, and guessing `/en/band/<Name>` resolves to
whichever homonym owns the slug, which is how you get the German Natas instead
of the Argentine one. Each result reads `<style>-<country>`, and the split is at
the **first** dash: styles are written with spaces and never contain a dash,
countries write their spaces as dashes. Splitting at the last dash turns
`Death Grind-United-Kingdom` into style `Death Grind-United`, country `Kingdom`.

A title is looked up **once** and then stored. Never make the rebuild re-query
every band: that would be 140 requests to a small site every hour.

`genres.json` is the one state file that **is** tracked in git, because the
Metal Archives half of it cannot be regenerated without Guido doing the manual
Firefox step again.

### Disambiguating homonyms

Both sites are full of bands sharing a name, and both will happily hand back the
wrong country's band with total confidence. That silent wrong answer is worse
than no answer, so `som_resolve()` uses the only signal the agenda gives: ticket
price. Under 50.000 means a local band, over it means a touring act. When that
still leaves several candidates the note starts with `SIN RESOLVER` and the card
shows a ⚠, rather than pretending to be sure.

## Environment

`monitor.py`, `dashboard.py` and `seed_genres.py` are **stdlib only**, so any
`python3` works. Cron uses `/home/guido/default/bin/python3`. Both it and
`/usr/bin/python3` are 3.12.3, which matters because the card templates use
nested f-strings and those need 3.12 or newer.

Keep it that way. `curl_cffi`, `playwright` and `patchright` are installed in
`/home/guido/default`, but they were installed while trying to get past Metal
Archives' Cloudflare and **no project code imports them**. Playwright is worth
keeping around only as the test browser, see below.

The desktop is XFCE with `xfce4-notifyd`, which renders both the flyer and the action button. `notify()` sets `DISPLAY`, `XDG_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS` by hand, because cron gives the script no desktop session.

The cron entry is:

```
17 * * * * cd /home/guido/Desktop/Otros/MetalNotifications && /home/guido/default/bin/python3 /home/guido/Desktop/Otros/MetalNotifications/monitor.py >> /home/guido/Desktop/Otros/MetalNotifications/cron.log 2>&1
```

## Files

| File | Tracked | What it is |
|---|---|---|
| `monitor.py` | yes | The watcher |
| `dashboard.py` | yes | Genre lookup and dashboard rendering |
| `seed_genres.py` | yes | One-off: builds `genres.json` from a Metal Archives harvest |
| `ma_snippet.js` | yes | Paste into the Firefox console to harvest Metal Archives |
| `genres.json` | **yes** | Genre per agenda title; the MA half is not reproducible |
| `dashboard.html` | no | Generated every run |
| `dashboard_archive.json` | no | Every show ever seen, so past ones survive |
| `known_shows.json` | no | Every show seen on the last run |
| `watchlist.json` | no | Shows waiting for tickets |
| `images/` | no | Cached flyers |
| `.pending/` | no | Payloads for notifications still on screen |
| `monitor.log`, `cron.log` | no | Run history |
