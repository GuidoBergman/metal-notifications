#!/usr/bin/env python3
"""
Metal-Daze agenda watcher.

Fetches https://metaldazeweb.com/agenda/, parses every show, and fires a
persistent desktop notification (one that stays on screen until you click it)
for any show that wasn't there last time. Each notification carries the show's
flyer as its icon.

Shows you are interested in can be put on a watchlist, either by clicking the
"Avisame de entradas" button on the notification itself or from the terminal:

    ./monitor.py watch <text>     put matching shows on the watchlist
    ./monitor.py unwatch <text>   take them off
    ./monitor.py list             show the watchlist
    ./monitor.py dashboard        rebuild dashboard.html without notifying

Watched shows get two extra notifications, and only watched shows do:
  * their tickets go on sale (the show gains a ticket link);
  * their date, time or venue changes on the site.

Stdlib only -- no pip installs needed.

Every run also regenerates dashboard.html, a browsable grid of every show with
its genre, country and flyer. See dashboard.py.

State lives in known_shows.json next to this file, the watchlist in
watchlist.json, cached flyers in images/. The first run seeds the baseline
silently (so you don't get 100+ notifications for shows already listed); only
shows added *after* that first run trigger notifications.
"""

import fcntl
import hashlib
import html as htmllib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

URL = "https://metaldazeweb.com/agenda/"
HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "known_shows.json"
WATCH_FILE = HERE / "watchlist.json"
LOCK_FILE = HERE / "watchlist.lock"
LOG_FILE = HERE / "monitor.log"
IMG_DIR = HERE / "images"

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 MetalDazeWatcher/1.0"

# A notification with a button keeps a small helper process alive until you
# click or dismiss it. These bound the damage if notifications pile up unread.
MAX_LIVE_WAITERS = 20
WAITER_MAX_AGE_DAYS = 14
# A watched show that vanishes from the agenda is dropped after this long.
WATCH_DROP_AFTER_DAYS = 30

FALLBACK_ICON = "audio-x-generic"


def log(msg):
    line = f"{datetime.now().isoformat(timespec='seconds')}  {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def clean(s):
    if s is None:
        return ""
    s = re.sub(r"<[^>]+>", "", s)            # strip tags
    s = htmllib.unescape(s)
    s = s.replace("\xa0", " ")               # &nbsp;
    return re.sub(r"\s+", " ", s).strip()


def first(pattern, text):
    m = re.search(pattern, text, re.S)
    return m.group(1) if m else ""


def norm(s):
    """Lowercase and strip accents, so 'Nepal' matches 'NEPÁL'."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower().strip()


def show_date(show):
    """Sort key: the show's date, far future if unparseable."""
    try:
        return datetime.strptime(show.get("date", ""), "%d/%m/%Y")
    except ValueError:
        return datetime.max


def parse_shows(page):
    """Return a list of dicts, one per show, with every available field."""
    # Each show is a <div class="wp_theatre_event"> ... </div> block.
    blocks = re.split(r'<div class="wp_theatre_event">', page)[1:]
    shows = []
    for block in blocks:
        # Cut the block at the start of the next group header if present.
        block = re.split(r'<h3 class="wpt_listing_group', block)[0]

        title = clean(first(r'wp_theatre_event_title">(.*?)</div>', block))
        if not title:
            continue
        page_url = first(r'wp_theatre_event_title"><a href="([^"]+)"', block)
        remark = clean(first(r'wp_theatre_event_remark">(.*?)</div>', block))
        date = clean(first(r'wp_theatre_event_startdate">(.*?)</div>', block))
        etime = clean(first(r'wp_theatre_event_starttime">(.*?)</div>', block))
        venue = clean(first(r'wp_theatre_event_venue">(.*?)</div>', block))
        city = clean(first(r'wp_theatre_event_city">(.*?)</div>', block))
        ticket_url = first(r'wp_theatre_event_tickets_url[^>]*href="([^"]+)"', block)
        # href is captured before; redo robustly:
        ticket_url = first(r'wp_theatre_event_tickets">\s*<a href="([^"]+)"', block) or ticket_url
        price = clean(first(r'wp_theatre_event_prices">(.*?)</div>', block))
        # When there is no ticket link the site says why: "Entradas proximamente",
        # "Sold out", "Ver flyer", "Gratis", "Comunicate con la banda", ...
        tickets_status = clean(
            first(r'wp_theatre_event_tickets_status[^>]*>(.*?)</span>', block)
        )
        # The listing already carries the flyer thumbnail, lazy-loaded via data-src.
        image_url = first(r'<figure>.*?<img[^>]*?data-src="([^"]+)"', block)
        if not image_url:
            image_url = first(r'<figure>.*?<img[^>]*?\ssrc="(https?://[^"]+)"', block)

        show = {
            "title": title,
            "remark": remark,
            "date": date,
            "time": etime,
            "venue": venue,
            "city": city,
            "price": price,
            "ticket_url": ticket_url,
            "tickets_status": tickets_status,
            "image_url": image_url,
            "page_url": page_url,
        }
        # Stable identity: band + date + venue + city + time.
        show["key"] = "|".join([title, date, etime, venue, city]).lower()
        shows.append(show)
    return shows


# --------------------------------------------------------------------------
# Flyer images
# --------------------------------------------------------------------------

def cache_image(image_url):
    """Download the flyer once and return its absolute path, or None."""
    if not image_url:
        return None
    name = hashlib.sha1(image_url.encode("utf-8")).hexdigest()
    ext = os.path.splitext(image_url.split("?")[0])[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        ext = ".jpg"
    path = IMG_DIR / f"{name}{ext}"
    if path.exists() and path.stat().st_size > 0:
        return str(path)
    try:
        IMG_DIR.mkdir(exist_ok=True)
        req = urllib.request.Request(image_url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read(4 * 1024 * 1024)   # flyers are ~10 KB; cap anyway
        if not data:
            return None
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        # The dashboard fetches every flyer on its first build; stay polite.
        time.sleep(0.25)
        return str(path)
    except Exception as e:  # noqa: BLE001
        log(f"image download failed ({image_url}): {e}")
        return None


# --------------------------------------------------------------------------
# Notifications
# --------------------------------------------------------------------------

def notify_env():
    """cron gives us no desktop session, so point at the running one."""
    uid = os.getuid()
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
    return env


def live_waiters():
    """PIDs of our button-waiting helper processes, with their start times."""
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().split(b"\0")
            if len(cmdline) >= 2 and cmdline[1].decode(errors="replace") == "_await_click":
                found.append((int(entry.name), entry.stat().st_ctime))
        except (OSError, ValueError):
            continue
    return found


def reap_waiters():
    """Kill helpers left over from notifications nobody ever touched."""
    cutoff = time.time() - WAITER_MAX_AGE_DAYS * 86400
    for pid, started in live_waiters():
        if started < cutoff:
            try:
                os.kill(pid, 15)
                log(f"reaped stale notification helper pid={pid}")
            except OSError:
                pass
    # Payloads whose helper died with the session (a reboot, say) never get
    # cleaned up by the helper itself.
    pending = HERE / ".pending"
    if pending.is_dir():
        for leftover in pending.glob("*.json"):
            try:
                if leftover.stat().st_mtime < cutoff:
                    leftover.unlink()
            except OSError:
                pass


def send_notification(summary, body, icon=None, action=None, payload=None):
    """
    Fire a persistent notification (stays until clicked).

    action: (name, label) to render a button. Clicking it re-runs this script
    as `_await_click`, which does whatever `payload` says. notify-send blocks
    while a button is on screen, so that part runs in a detached helper.
    """
    env = notify_env()
    cmd = [
        "notify-send",
        "--urgency=critical",   # high priority
        "--expire-time=0",      # 0 = never auto-dismiss; stays until you click it
        "--app-name=Metal-Daze",
        f"--icon={icon or FALLBACK_ICON}",
    ]

    if action and len(live_waiters()) >= MAX_LIVE_WAITERS:
        log(f"{MAX_LIVE_WAITERS} unread notifications already waiting; sending '{summary}' without a button")
        action = None

    if not action:
        try:
            subprocess.run(cmd + [summary, body], env=env, check=False, timeout=15)
        except Exception as e:  # noqa: BLE001
            log(f"notify-send failed for {summary}: {e}")
        return

    name, label = action
    payload = dict(payload or {})
    payload["action_name"] = name
    payload["cmd"] = cmd + [f"--action={name}={label}", summary, body]

    pending = HERE / ".pending"
    pending.mkdir(exist_ok=True)
    token = hashlib.sha1(f"{summary}{time.time()}".encode("utf-8")).hexdigest()[:16]
    path = pending / f"{token}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    try:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "_await_click", str(path)],
            env=env,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:  # noqa: BLE001
        log(f"could not spawn notification helper for {summary}: {e}")
        path.unlink(missing_ok=True)
        try:
            subprocess.run(cmd + [summary, body], env=env, check=False, timeout=15)
        except Exception:  # noqa: BLE001
            pass


def await_click(payload_path):
    """
    Detached helper: show one notification with a button and act on the click.

    notify-send --action blocks until the notification is closed. On a click it
    prints the action name; on a plain dismiss it prints only the notification
    id. That difference is how we tell the two apart.
    """
    path = Path(payload_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log(f"notification helper could not read {path}: {e}")
        return 1

    try:
        proc = subprocess.run(
            payload["cmd"], env=notify_env(), capture_output=True, text=True
        )
        clicked = payload["action_name"] in [l.strip() for l in proc.stdout.splitlines()]
    except Exception as e:  # noqa: BLE001
        log(f"notification helper failed: {e}")
        path.unlink(missing_ok=True)
        return 1

    path.unlink(missing_ok=True)
    if not clicked:
        return 0

    show = payload.get("show") or {}
    if payload["action_name"] == "watch":
        result = add_watch(show)
        if result == "added":
            log(f"WATCHING (from notification): {show.get('title')} ({show.get('date')})")
            send_notification(
                f"\U0001F514 En la lista: {show.get('title', '')}",
                "Te aviso apenas salgan las entradas.",
                icon=cache_image(show.get("image_url")),
            )
        elif result == "already_on_sale":
            send_notification(
                f"\U0001F39F️ Ya hay entradas: {show.get('title', '')}",
                show.get("ticket_url", ""),
                icon=cache_image(show.get("image_url")),
            )
    elif payload["action_name"] == "open":
        url = payload.get("url") or show.get("ticket_url") or show.get("page_url")
        if url:
            subprocess.run(["xdg-open", url], env=notify_env(), check=False)
    return 0


def notify_new_show(show):
    """A show appeared on the agenda."""
    lines = []
    if show["date"]:
        lines.append(f"\U0001F4C5 {show['date']}" + (f"  {show['time']}" if show["time"] else ""))
    loc = " ".join(p for p in [show["venue"], show["city"]] if p)
    if loc:
        lines.append(f"\U0001F4CD {loc}")
    if show["price"]:
        lines.append(f"\U0001F39F️  {show['price']}")
    if show["remark"]:
        lines.append(show["remark"])
    if show["ticket_url"]:
        lines.append(f"\U0001F39F️ Entradas: {show['ticket_url']}")
    elif show.get("tickets_status"):
        lines.append(f"\U0001F39F️ Entradas: {show['tickets_status']}")
    if show["page_url"]:
        lines.append(f"\U0001F517 {show['page_url']}")

    if show["ticket_url"]:
        action = ("open", "Abrir entradas")
    else:
        action = ("watch", "Avisame de entradas")

    send_notification(
        f"\U0001F918 New metal show: {show['title']}",
        "\n".join(lines),
        icon=cache_image(show.get("image_url")),
        action=action,
        payload={"show": show},
    )
    log(f"NOTIFIED: {show['title']} ({show['date']} @ {show['venue']})")


def notify_tickets_on_sale(show):
    """A watched show just gained a ticket link."""
    lines = []
    if show["date"]:
        lines.append(f"\U0001F4C5 {show['date']}" + (f"  {show['time']}" if show["time"] else ""))
    loc = " ".join(p for p in [show["venue"], show["city"]] if p)
    if loc:
        lines.append(f"\U0001F4CD {loc}")
    if show["price"]:
        lines.append(f"\U0001F39F️  {show['price']}")
    lines.append(f"\U0001F39F️ {show['ticket_url']}")

    send_notification(
        f"\U0001F39F️ ¡Entradas a la venta! {show['title']}",
        "\n".join(lines),
        icon=cache_image(show.get("image_url")),
        action=("open", "Abrir entradas"),
        payload={"show": show, "url": show["ticket_url"]},
    )
    log(f"TICKETS ON SALE: {show['title']} ({show['date']}) -> {show['ticket_url']}")


def notify_show_changed(show, changes):
    """A watched show moved: date, time or venue."""
    lines = [f"{label}: {old} → {new}" for label, old, new in changes]
    if show["page_url"]:
        lines.append(f"\U0001F517 {show['page_url']}")

    send_notification(
        f"\U0001F4C5 Cambió el show: {show['title']}",
        "\n".join(lines),
        icon=cache_image(show.get("image_url")),
    )
    log(f"CHANGED: {show['title']} -- " + "; ".join(f"{l} {o} -> {n}" for l, o, n in changes))


# --------------------------------------------------------------------------
# Watchlist
# --------------------------------------------------------------------------

@contextmanager
def watchlist_locked():
    """
    Yield the watchlist for read-modify-write, then save it.

    The hourly run and any number of notification helpers can all touch this
    file at once, so the whole cycle is held under one exclusive lock.
    """
    LOCK_FILE.touch(exist_ok=True)
    with open(LOCK_FILE, "r+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            entries = []
            if WATCH_FILE.exists():
                try:
                    entries = json.loads(WATCH_FILE.read_text(encoding="utf-8")).get("watching", [])
                except (OSError, json.JSONDecodeError):
                    log("WARNING: watchlist unreadable; starting a new one.")
            box = {"entries": entries, "dirty": False}
            yield box
            if box["dirty"]:
                tmp = WATCH_FILE.with_suffix(".json.tmp")
                tmp.write_text(
                    json.dumps({"watching": box["entries"]}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                tmp.replace(WATCH_FILE)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def read_watchlist():
    if not WATCH_FILE.exists():
        return []
    try:
        return json.loads(WATCH_FILE.read_text(encoding="utf-8")).get("watching", [])
    except (OSError, json.JSONDecodeError):
        return []


def watch_entry(show):
    return {
        "key": show.get("key", ""),
        "title": show.get("title", ""),
        "date": show.get("date", ""),
        "time": show.get("time", ""),
        "venue": show.get("venue", ""),
        "city": show.get("city", ""),
        "page_url": show.get("page_url", ""),
        "image_url": show.get("image_url", ""),
        "added_at": datetime.now().isoformat(timespec="seconds"),
        "missing_since": "",
    }


def add_watch(show):
    """Returns 'added', 'already_watching' or 'already_on_sale'."""
    if show.get("ticket_url"):
        return "already_on_sale"
    with watchlist_locked() as box:
        if any(e["key"] == show.get("key") for e in box["entries"]):
            return "already_watching"
        box["entries"].append(watch_entry(show))
        box["dirty"] = True
    return "added"


def match_watched(entry, current):
    """
    Find a watched show in the current agenda.

    The key contains the date and venue, so a correction on the site would
    otherwise look like the show vanished. Fall back to title plus venue, then
    title plus date, but only when that lands on exactly one show.
    """
    if entry["key"] in current:
        return current[entry["key"]]

    title = norm(entry["title"])
    for fields in (("venue", "city"), ("date",)):
        hits = [
            s for s in current.values()
            if norm(s["title"]) == title
            and all(norm(s.get(f, "")) == norm(entry.get(f, "")) for f in fields)
        ]
        if len(hits) == 1:
            return hits[0]
    return None


def detect_moves(known, current):
    """
    Map new keys to the show they actually are: one that moved, not a new one.

    The key holds the date and venue, so the site fixing either makes a show
    look like it vanished and a different one appeared. The permalink is the
    real identity, so pair on that -- but only when it is unambiguous on both
    sides, since a band playing two dates can share one page.
    """
    gone = [s for k, s in known.items() if k not in current]
    fresh = {k: s for k, s in current.items() if k not in known}

    moved = {}
    for new_key, new_show in fresh.items():
        url = new_show.get("page_url")
        if not url:
            continue
        if sum(1 for s in fresh.values() if s.get("page_url") == url) != 1:
            continue
        hits = [s for s in gone if s.get("page_url") == url]
        if len(hits) == 1:
            moved[new_key] = hits[0]
    return moved


def check_watchlist(current):
    """Notify about tickets and changes for watched shows. Returns a count."""
    events = 0
    with watchlist_locked() as box:
        kept = []
        for entry in box["entries"]:
            show = match_watched(entry, current)

            if show is None:
                # Gone from the agenda. You asked not to be alerted about that,
                # so just age it out quietly.
                since = entry.get("missing_since") or datetime.now().isoformat(timespec="seconds")
                if datetime.fromisoformat(since) < datetime.now() - timedelta(days=WATCH_DROP_AFTER_DAYS):
                    log(f"Dropped from watchlist (off the agenda {WATCH_DROP_AFTER_DAYS}+ days): {entry['title']} ({entry['date']})")
                    box["dirty"] = True
                    continue
                if not entry.get("missing_since"):
                    entry["missing_since"] = since
                    box["dirty"] = True
                kept.append(entry)
                continue

            if entry.get("missing_since"):
                entry["missing_since"] = ""
                box["dirty"] = True

            if show.get("ticket_url"):
                notify_tickets_on_sale(show)
                events += 1
                box["dirty"] = True
                time.sleep(0.4)
                continue    # nothing left to wait for; drop it

            changes = []
            for field, label in (("date", "Fecha"), ("time", "Hora"),
                                 ("venue", "Lugar"), ("city", "Ciudad")):
                old, new = entry.get(field, ""), show.get(field, "")
                if old != new:
                    changes.append((label, old or "-", new or "-"))
            if changes:
                notify_show_changed(show, changes)
                events += 1
                time.sleep(0.4)

            # Re-anchor to whatever the site says now.
            for field in ("key", "date", "time", "venue", "city", "image_url", "page_url"):
                if entry.get(field) != show.get(field, ""):
                    entry[field] = show.get(field, "")
                    box["dirty"] = True
            kept.append(entry)

        box["entries"] = kept
    return events


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log("WARNING: state file unreadable; treating as empty (will reseed).")
    return None


def save_state(state):
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


# --------------------------------------------------------------------------
# Terminal commands
# --------------------------------------------------------------------------

def known_shows():
    state = load_state() or {}
    return sorted(state.get("shows", {}).values(), key=show_date)


def describe(show):
    bits = [show.get("date", ""), show.get("time", ""), show.get("venue", ""), show.get("city", "")]
    return f"{show.get('title', '')} - " + " ".join(b for b in bits if b)


def ticket_note(show):
    if show.get("ticket_url"):
        return "entradas a la venta"
    return show.get("tickets_status") or "sin entradas"


def select(shows, answer):
    """Turn '1,3' or 'all' into the shows it names."""
    if answer.strip().lower() in ("all", "todos", "todas"):
        return shows
    chosen = []
    for part in answer.replace(" ", "").split(","):
        if part.isdigit() and 1 <= int(part) <= len(shows):
            chosen.append(shows[int(part) - 1])
    return chosen


def pick(shows, prompt, preset=None):
    """
    Choose from a list of shows.

    `preset` is the --pick argument, so this can run unattended. With one match
    and no preset the choice is obvious. With several and no preset it asks,
    unless nobody is at the keyboard, in which case it prints the list and
    gives up rather than hanging on input.
    """
    if preset:
        return select(shows, preset)
    if len(shows) == 1:
        return shows

    for i, s in enumerate(shows, 1):
        print(f"  {i:2}) {describe(s)}   [{ticket_note(s)}]")

    if not sys.stdin.isatty():
        print(f"Several shows match. Re-run with --pick <numbers|all>, for example: --pick 1")
        return []
    try:
        answer = input(f"{prompt} (numbers separated by commas, or 'all'): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return []
    return select(shows, answer)


def cmd_watch(query, preset=None):
    if not query:
        print("Usage: ./monitor.py watch <band, venue or city> [--pick <numbers|all>]")
        return 2
    q = norm(query)
    matches = [
        s for s in known_shows()
        if q in norm(f"{s.get('title', '')} {s.get('venue', '')} {s.get('city', '')}")
    ]
    if not matches:
        print(f"No show on the agenda matches '{query}'.")
        return 1

    print(f"{len(matches)} show(s) match '{query}':")
    if len(matches) == 1:
        print(f"  {describe(matches[0])}   [{ticket_note(matches[0])}]")
    for show in pick(matches, "Which one(s) do you want to be told about", preset):
        result = add_watch(show)
        if result == "added":
            print(f"  Watching: {describe(show)}")
            print("  I will notify you as soon as its tickets go on sale.")
            log(f"WATCHING (from terminal): {show['title']} ({show['date']})")
        elif result == "already_watching":
            print(f"  Already on the watchlist: {describe(show)}")
        else:
            print(f"  Tickets are already on sale: {describe(show)}")
            print(f"  {show['ticket_url']}")
    return 0


def cmd_unwatch(query, preset=None):
    if not query:
        print("Usage: ./monitor.py unwatch <band, venue or city> [--pick <numbers|all>]")
        return 2
    q = norm(query)
    matches = [
        e for e in read_watchlist()
        if q in norm(f"{e.get('title', '')} {e.get('venue', '')} {e.get('city', '')}")
    ]
    if not matches:
        print(f"Nothing on the watchlist matches '{query}'.")
        return 1

    print(f"{len(matches)} watched show(s) match '{query}':")
    if len(matches) == 1:
        print(f"  {describe(matches[0])}")
    dropped = pick(matches, "Which one(s) do you want to stop watching", preset)
    if not dropped:
        return 0
    keys = {e["key"] for e in dropped}
    with watchlist_locked() as box:
        box["entries"] = [e for e in box["entries"] if e["key"] not in keys]
        box["dirty"] = True
    for entry in dropped:
        print(f"  Stopped watching: {describe(entry)}")
    return 0


def cmd_list():
    entries = sorted(read_watchlist(), key=show_date)
    if not entries:
        print("The watchlist is empty.")
        print("Add a show with:  ./monitor.py watch <band>")
        return 0
    print(f"Waiting for tickets on {len(entries)} show(s):")
    for e in entries:
        line = f"  {describe(e)}"
        if e.get("missing_since"):
            line += "   [not on the agenda right now]"
        print(line)
    return 0


def cmd_dashboard():
    """Rebuild dashboard.html from the live agenda without notifying anything."""
    try:
        shows = parse_shows(fetch(URL))
    except Exception as e:  # noqa: BLE001
        print(f"Could not fetch the agenda: {e}")
        return 1
    if not shows:
        print("Parsed 0 shows -- page format may have changed. Nothing rebuilt.")
        return 1
    import dashboard
    path = dashboard.rebuild({s["key"]: s for s in shows}, cache_image, log)
    print(f"Dashboard rebuilt: {path}")
    return 0


# --------------------------------------------------------------------------

def excluded_location(show):
    """True for shows somewhere Guido will not travel to (see dashboard.py)."""
    try:
        import dashboard
        return dashboard.excluido(show)
    except Exception as e:  # noqa: BLE001 -- a broken filter must not mute alerts
        log(f"location filter unavailable, notifying anyway: {e}")
        return False


def rebuild_dashboard(current):
    """Regenerate dashboard.html. Never let it take the watcher down with it."""
    try:
        import dashboard
        dashboard.rebuild(current, cache_image, log)
    except Exception as e:  # noqa: BLE001
        log(f"dashboard rebuild failed: {e}")


def run_check():
    try:
        page = fetch(URL)
    except Exception as e:  # noqa: BLE001
        log(f"FETCH FAILED: {e}")
        return 1

    shows = parse_shows(page)
    if not shows:
        log("Parsed 0 shows -- page format may have changed. Not touching state.")
        return 1

    current = {s["key"]: s for s in shows}
    state = load_state()

    if state is None:
        # First run: establish baseline silently.
        save_state({"shows": current, "seeded_at": datetime.now().isoformat()})
        log(f"Baseline seeded with {len(current)} shows. No notifications sent on first run.")
        rebuild_dashboard(current)
        return 0

    reap_waiters()

    known = state.get("shows", {})
    moved = detect_moves(known, current)
    new_keys = [k for k in current if k not in known and k not in moved]

    for new_key, old in moved.items():
        now = current[new_key]
        diff = [f"{f}: {old.get(f, '')} -> {now.get(f, '')}"
                for f in ("date", "time", "venue", "city") if old.get(f, "") != now.get(f, "")]
        log(f"Show moved (not new): {now['title']} -- " + "; ".join(diff))

    skipped = 0
    for k in new_keys:
        # Still recorded as seen, just not worth a notification.
        if excluded_location(current[k]):
            log(f"Skipped (excluded location): {describe(current[k])}")
            skipped += 1
            continue
        notify_new_show(current[k])
        time.sleep(0.4)  # let the daemon queue each one

    watch_events = check_watchlist(current)

    # Persist the full current set (also drops shows that fell off the page).
    state["shows"] = current
    state["last_check"] = datetime.now().isoformat()
    save_state(state)

    rebuild_dashboard(current)

    log(f"Checked {len(current)} shows; {len(new_keys)} new "
        f"({skipped} skipped by location); {watch_events} watchlist event(s).")
    return 0


def main(argv):
    if not argv:
        return run_check()

    cmd, rest = argv[0], argv[1:]

    # --pick lets watch/unwatch run unattended: --pick 1,3 or --pick all.
    preset = None
    if "--pick" in rest:
        i = rest.index("--pick")
        preset = rest[i + 1] if i + 1 < len(rest) else None
        rest = rest[:i] + rest[i + 2:]
        if not preset:
            print("--pick needs a value: numbers separated by commas, or 'all'.")
            return 2

    if cmd == "watch":
        return cmd_watch(" ".join(rest), preset)
    if cmd == "unwatch":
        return cmd_unwatch(" ".join(rest), preset)
    if cmd in ("list", "watching"):
        return cmd_list()
    if cmd == "dashboard":
        return cmd_dashboard()
    if cmd == "_await_click":
        return await_click(rest[0]) if rest else 2

    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
