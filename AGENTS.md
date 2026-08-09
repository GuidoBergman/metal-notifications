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

`watch` and `unwatch` search band name, venue and city together, ignoring case and accents.

`--pick` takes `1`, `1,3` or `all`, numbered as the command prints the matches.

Watching a show whose tickets are already on sale does not add it to the watchlist. The command prints the ticket link instead, which is usually what he actually wanted.

## Things not to do

Never delete or hand-edit `known_shows.json`. Deleting it makes the next run treat the whole agenda as already seen, so genuinely new shows are swallowed silently. If you need a clean slate for testing, copy `monitor.py` to a scratch directory and run it there, since every path is resolved relative to the script.

Never fire test notifications at his screen without telling him first. Any command that notifies pops a window over whatever he is doing.

Do not commit the state files. `.gitignore` already covers them.

## How it works, in the order it matters

Each show gets a key of band, date, time, venue and city. A show whose key was not in `known_shows.json` last run is new.

Because that key holds the date and venue, a correction on the site would look like one show vanished and another appeared. Shows are therefore paired by permalink first, and only counted as new when no pairing exists. See `detect_moves()`.

The agenda page states ticket availability directly. A show either carries a ticket link, or carries a status label instead: "Entradas próximamente", "Sold out", "Ver flyer", "Gratis", "Comunicate con la banda". Tickets going on sale means a watched show gained a link.

Notifications carry the show flyer, taken from the thumbnail already embedded in the listing and cached in `images/`.

Notifications with a button need a helper process, because `notify-send --action` blocks until the notification is closed. The script re-executes itself as `_await_click` in a detached process, which reads a payload from `.pending/` and acts on the click. On a click `notify-send` prints the action name, on a plain dismiss it prints only the notification id. That difference is the whole mechanism.

Helpers older than 14 days are killed on the next run, and no more than 20 wait at once. Beyond that, notifications are sent without a button.

## Environment

Stdlib Python only, so any `python3` works. Cron uses `/home/guido/default/bin/python3`.

The desktop is XFCE with `xfce4-notifyd`, which renders both the flyer and the action button. `notify()` sets `DISPLAY`, `XDG_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS` by hand, because cron gives the script no desktop session.

The cron entry is:

```
17 * * * * cd /home/guido/Desktop/Otros/MetalNotifications && /home/guido/default/bin/python3 /home/guido/Desktop/Otros/MetalNotifications/monitor.py >> /home/guido/Desktop/Otros/MetalNotifications/cron.log 2>&1
```

## Files

| File | Tracked | What it is |
|---|---|---|
| `monitor.py` | yes | The whole program |
| `known_shows.json` | no | Every show seen on the last run |
| `watchlist.json` | no | Shows waiting for tickets |
| `images/` | no | Cached flyers |
| `.pending/` | no | Payloads for notifications still on screen |
| `monitor.log`, `cron.log` | no | Run history |
