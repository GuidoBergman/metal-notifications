#!/usr/bin/env python3
"""Dashboard for the Metal-Daze agenda: one card per show, with genre and flyer.

monitor.py calls rebuild() at the end of every run. Shows that fell off the
agenda because they already happened are kept in dashboard_archive.json and
rendered behind a "ver pasados" filter, so nothing is lost.

Genres come from genres.json. Titles seeded there by seed_genres.py carry Metal
Archives data, which is richer but had to be harvested by hand because the site
is behind Cloudflare. Anything new is looked up on Spirit of Metal, which is
reachable over plain HTTP. A title is looked up once and then stored, otherwise
every hourly run would hammer Spirit of Metal with 140 requests.

Favourites live in the browser's localStorage, keyed by band, and never touch
watchlist.json -- ticket alerts are still driven by `monitor.py watch`.
"""

import html
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
GENRES_FILE = HERE / "genres.json"
ARCHIVE_FILE = HERE / "dashboard_archive.json"
DASHBOARD_FILE = HERE / "dashboard.html"
IMG_DIR = HERE / "images"

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 MetalDazeWatcher/1.0"

SOM_FIND = "https://www.spirit-of-metal.com/find.php?l=en&nom="
SOM_ROW = re.compile(
    r'href="https://www\.spirit-of-metal\.com/en/band/([^"]+)"[^>]*>([^<]+)</a>\s*\(([^)]*)\)'
)
# Homonyms carry the country in the displayed name: "Pogrom (ARG)", "Left To Die (USA-1)".
SOM_SUFFIX = re.compile(r"\s*\(([A-Z]{2,4})(?:-\d+)?\)\s*$")

# A show priced above this is almost certainly a touring foreign act; below it,
# a local band. It is the only signal the agenda gives us to tell homonyms apart.
PRECIO_INTERNACIONAL = 50000

# Places Guido will not travel to. Matched against the show's city, ignoring
# case and accents, so "chubut" catches both Comodoro Rivadavia and Puerto
# Madryn. Shows here are left out of the dashboard AND never trigger a new-show
# notification (monitor.py reads this through excluido()).
#
# Filtering happens at render time only: the shows stay in the archive, so
# dropping a line here brings them straight back. Deleting them instead would
# not work, since they are still on the agenda and the next run would re-add them.
#
# Watchlist alerts are deliberately NOT filtered: if you explicitly asked to be
# told when a show's tickets drop, location is your problem, not the script's.
EXCLUIR_CIUDADES = ("chubut", "santa cruz")

# Spirit of Metal writes "USA" where Metal Archives writes "United States".
COUNTRY_ES = {
    "United States": "Estados Unidos", "USA": "Estados Unidos",
    "United Kingdom": "Reino Unido", "Sweden": "Suecia", "Germany": "Alemania",
    "Finland": "Finlandia", "Netherlands": "Países Bajos", "Italy": "Italia",
    "France": "Francia", "Brazil": "Brasil", "Norway": "Noruega",
    "Denmark": "Dinamarca", "Spain": "España", "Poland": "Polonia",
    "Tunisia": "Túnez", "Canada": "Canadá", "Japan": "Japón", "Mexico": "México",
    "Czechia": "Chequia", "Czech Republic": "Chequia", "Russia": "Rusia",
    "Greece": "Grecia", "Switzerland": "Suiza", "Belgium": "Bélgica",
    "Hungary": "Hungría", "Ireland": "Irlanda", "Turkey": "Türkiye",
    "Costa Rica": "Costa Rica", "New Zealand": "Nueva Zelanda",
    "South Korea": "Corea del Sur", "Korea, South": "Corea del Sur",
    "Austria": "Austria", "Australia": "Australia", "Chile": "Chile",
    "Colombia": "Colombia", "Peru": "Perú", "Uruguay": "Uruguay",
    "Ecuador": "Ecuador", "Venezuela": "Venezuela", "Israel": "Israel",
    "Ukraine": "Ucrania", "Romania": "Rumania", "Serbia": "Serbia",
    "Croatia": "Croacia", "Slovakia": "Eslovaquia", "Slovenia": "Eslovenia",
    "Iceland": "Islandia", "Indonesia": "Indonesia", "India": "India",
    "China": "China", "Malaysia": "Malasia", "Philippines": "Filipinas",
    "South Africa": "Sudáfrica", "Argentina": "Argentina", "Portugal": "Portugal",
}

SIN_DATO = "sin dato"


def _es(country):
    return COUNTRY_ES.get(country, country)


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", s.lower())


# --------------------------------------------------------------------------
# Genre store
# --------------------------------------------------------------------------

def load_genres():
    if GENRES_FILE.exists():
        try:
            return json.loads(GENRES_FILE.read_text(encoding="utf-8")).get("bands", {})
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def save_genres(bands):
    tmp = GENRES_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"version": 1, "bands": bands}, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    tmp.replace(GENRES_FILE)


# --------------------------------------------------------------------------
# Spirit of Metal
# --------------------------------------------------------------------------

def _get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def som_search(name):
    """[{name, bare, style, country, url}] for one Spirit of Metal search."""
    body = _get(SOM_FIND + urllib.parse.quote(name))
    out = []
    for slug, display, meta in SOM_ROW.findall(body):
        display = display.strip()
        meta = meta.strip()
        # meta is "<style>-<country>", e.g. "Death Metal-Argentina" or
        # "Death Grind-United-Kingdom". Styles are spelled with spaces and never
        # contain a dash; countries spell their spaces with dashes. So the split
        # is at the FIRST dash, and the country's remaining dashes are spaces.
        style, _, country = meta.partition("-")
        country = country.replace("-", " ")
        out.append({
            "name": display,
            "bare": SOM_SUFFIX.sub("", display),
            "style": style.strip(),
            "country": country.strip(),
            "url": f"https://www.spirit-of-metal.com/en/band/{slug}",
        })
    return out


def parse_price(show):
    """'desde 80.000,00' -> 80000. Returns None when the agenda gives no price."""
    m = re.search(r"([\d.]+),\d{2}", show.get("price", "") or "")
    if not m:
        return None
    try:
        return int(m.group(1).replace(".", ""))
    except ValueError:
        return None


def som_resolve(band, show):
    """Resolve one band name against Spirit of Metal, using the show to disambiguate."""
    try:
        hits = som_search(band)
    except Exception:  # noqa: BLE001 -- network trouble must never break a run
        return None

    exact = [h for h in hits if norm(h["bare"]) == norm(band)]
    if not exact:
        return None

    note = ""
    if len(exact) > 1:
        price = parse_price(show)
        argentinas = [h for h in exact if h["country"].lower() == "argentina"]
        extranjeras = [h for h in exact if h["country"].lower() != "argentina"]
        # The agenda's only usable signal: a cheap show is a local band, an
        # expensive one is a touring act. It narrows the field, rarely settles it.
        if price is not None and price < PRECIO_INTERNACIONAL and argentinas:
            chosen, quedaron = argentinas[0], argentinas
            razon = "El precio bajo apunta a una banda local"
        elif price is not None and price >= PRECIO_INTERNACIONAL and extranjeras:
            chosen, quedaron = extranjeras[0], extranjeras
            razon = "El precio alto apunta a una banda de gira"
        else:
            chosen, quedaron = exact[0], exact
            razon = "La agenda no da precio, así que no pude descartar ninguna"
        otros = ", ".join(sorted({h["country"] for h in exact if h is not chosen}))
        if len(quedaron) > 1:
            note = (f"SIN RESOLVER: {len(exact)} bandas con este nombre ({otros}). "
                    f"{razon}, pero quedaron {len(quedaron)} candidatas y elegí la primera.")
        else:
            note = (f"Había {len(exact)} bandas con este nombre ({otros}). "
                    f"{razon}.")
    else:
        chosen = exact[0]

    return {
        # bare, not name: drop the "(ARG)" disambiguator, the country has its own field
        "name": chosen["bare"],
        "country": _es(chosen["country"]) or SIN_DATO,
        "genre": chosen["style"] or SIN_DATO,
        "url": chosen["url"],
        "source": "spirit-of-metal",
        "note": note,
    }


def split_billing(title):
    """'TESTAMENT, MUNICIPAL WASTE & IMMOLATION' -> the three band names."""
    parts = re.split(r"\s*&\s*|\s*,\s*", title)
    return [p.strip() for p in parts if p.strip()]


def resolve_title(title, show, bands, log):
    """Return the acts for a title, looking it up on Spirit of Metal if unseen."""
    if title in bands:
        return bands[title]["acts"]

    acts = []
    for band in split_billing(title):
        act = som_resolve(band, show)
        time.sleep(1.0)  # Spirit of Metal is a small site; do not hammer it
        if act:
            acts.append(act)
        else:
            acts.append({"name": band.title(), "country": SIN_DATO, "genre": SIN_DATO,
                         "url": "", "source": "sin-datos",
                         "note": "No la encontré en Spirit of Metal."})
    bands[title] = {"acts": acts, "resolved_at": date.today().isoformat()}
    found = sum(1 for a in acts if a["source"] == "spirit-of-metal")
    log(f"genre lookup: {title} -> {found}/{len(acts)} resolved on Spirit of Metal")
    return acts


# --------------------------------------------------------------------------
# Archive
# --------------------------------------------------------------------------

def load_archive():
    if ARCHIVE_FILE.exists():
        try:
            return json.loads(ARCHIVE_FILE.read_text(encoding="utf-8")).get("shows", {})
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def save_archive(shows):
    tmp = ARCHIVE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"version": 1, "shows": shows}, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    tmp.replace(ARCHIVE_FILE)


def excluido(show):
    """True when the show is somewhere Guido does not want to see listed."""
    ciudad = norm(show.get("city", ""))
    return any(norm(x) in ciudad for x in EXCLUIR_CIUDADES)


def show_date(show):
    try:
        return datetime.strptime(show.get("date", ""), "%d/%m/%Y").date()
    except ValueError:
        return date.max


DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def dia_semana(d):
    return DIAS[d.weekday()] if d is not date.max else ""


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def _flyer(show, cache_image):
    """Cache the full-size flyer, falling back to the thumbnail the agenda embeds."""
    thumb = show.get("image_url") or ""
    if not thumb:
        return ""
    full = re.sub(r"-\d+x\d+(?=\.\w+$)", "", thumb)
    for url in ([full, thumb] if full != thumb else [thumb]):
        path = cache_image(url)
        if path:
            return "images/" + Path(path).name
    return ""


SRC_BADGE = {
    "metal-archives": "MA",
    "spirit-of-metal": "SoM",
    "propio": "yo",     # no entry anywhere, the genre is my own call
    "sin-datos": "—",
}

# A note either flags real uncertainty about *which* band this is, or just adds
# context ("ex-cantante de V8"). Only the first kind earns a warning triangle;
# marking every note as a warning makes the warning meaningless.
DUDA = ("sin resolver", "homónimos", "verificar", "no la conozco",
        "no la encontré", "line-up solo en el flyer", "el que encaja es")


def _es_duda(note):
    n = note.lower()
    return any(k in n for k in DUDA)


def _card(show, acts, flyer, past):
    e = html.escape
    title = show.get("title", "")
    fecha = show.get("date", "")
    hora = show.get("time", "")
    lugar = ", ".join(x for x in (show.get("venue", ""), show.get("city", "")) if x)
    d = show_date(show)
    iso = d.isoformat() if d is not date.max else ""
    dow = dia_semana(d)

    tickets = show.get("ticket_url", "")
    estado = show.get("tickets_status") or ""
    precio = show.get("price", "")

    def marca_nota(a):
        nota = a.get("note") or ""
        if not nota:
            return ""
        duda = _es_duda(nota)
        return (f' <span class="{"warn" if duda else "info"}" '
                f'title="{e(nota)}">{"⚠" if duda else "ⓘ"}</span>')

    def badge(a):
        src = a.get("source", "")
        return (f'<span class="src src-{e(src)}" title="fuente: {e(src)}">'
                f'{SRC_BADGE.get(src, "?")}</span>')

    # One act: its name is the card's title, so printing it again would just
    # repeat it. Several acts: each keeps its own name and its own link.
    solo = len(acts) == 1
    if solo and acts[0].get("url"):
        titulo_html = (f'<a class="titulo" href="{e(acts[0]["url"])}" target="_blank" '
                       f'rel="noopener" title="Ver en Metal Archives">{e(title)}</a>')
    else:
        titulo_html = f'<span class="titulo">{e(title)}</span>'

    filas = []
    for a in acts:
        cab = ""
        if not solo:
            nombre = e(a.get("name") or "")
            if a.get("url"):
                nombre = f'<a href="{e(a["url"])}" target="_blank" rel="noopener">{nombre}</a>'
            cab = f'<div class="acto-cab">{nombre}{badge(a)}{marca_nota(a)}</div>'
        extra = f'{badge(a)}{marca_nota(a)}' if solo else ""
        filas.append(
            f'<div class="acto">{cab}'
            f'<div class="genero">{e(a.get("genre") or SIN_DATO)}{extra}</div>'
            f'<div class="pais">{e(a.get("country") or SIN_DATO)}</div></div>'
        )

    if flyer:
        img = f'<img loading="lazy" src="{e(flyer)}" alt="Flyer de {e(title)}">'
        if tickets:
            # The flyer is the buy button; nothing else in the card links to tickets.
            img = (f'<a class="compra" href="{e(tickets)}" target="_blank" rel="noopener" '
                   f'title="Comprar entradas para {e(title)}">{img}'
                   f'<span class="overlay">Entradas</span></a>')
    else:
        img = '<div class="sinflyer">sin flyer</div>'

    if tickets:
        estado_html = '<span class="tix">Entradas a la venta</span>'
    else:
        estado_html = f'<span class="tix off">{e(estado or "sin datos")}</span>'

    generos_txt = " ".join((a.get("genre") or "") + " " + (a.get("country") or "") for a in acts)
    nombres_txt = " ".join(a.get("name") or "" for a in acts)
    buscar = e(f"{title} {nombres_txt} {lugar} {generos_txt}".lower())

    ficha = (f'<a class="mas" href="{e(show["page_url"])}" target="_blank" '
             f'rel="noopener">Ficha</a>') if show.get("page_url") else ""

    return (
        f'<article class="card{" past" if past else ""}" data-band="{e(title)}" '
        f'data-past="{"1" if past else "0"}" data-date="{iso}" data-search="{buscar}">'
        f'<div class="flyer">{img}</div>'
        f'<div class="cuerpo">'
        f'<div class="cab"><h2>{titulo_html}</h2>'
        f'<button class="fav" type="button" aria-label="Marcar {e(title)} como favorita">☆</button></div>'
        f'{"".join(filas)}'
        f'<div class="pie"><span class="fecha">{e(dow)} {e(fecha)}'
        f'{" · " + e(hora) if hora else ""}</span>'
        f'<span class="falta" hidden></span>'
        f'{f"""<span class="precio">{e(precio)}</span>""" if precio else ""}</div>'
        f'<div class="lugar">{e(lugar)}</div>'
        f'<div class="acciones">{estado_html}{ficha}</div>'
        f'</div></article>'
    )


CSS = """
/* Dark is the base look. The viewer has three theme states: an explicit
   data-theme stamp either way, or nothing at all (the "system" default), where
   only prefers-color-scheme applies. So the light palette is declared twice,
   once per state, and components only ever read tokens -- a colour defined
   inside a media block would never apply in the unstamped state. */
:root{
--bg:#0f1012;--card:#191b1f;--card2:#202329;--tx:#e8e6e3;--dim:#9a9691;
--line:#2c2f36;--acc:#c8963e;--warn:#e0a03a;--ya:#7a3030;--yatx:#fff;
--onacc:#17140d;--header:rgba(15,16,18,.96)}
@media(prefers-color-scheme:light){
:root:not([data-theme="dark"]){
--bg:#f6f5f3;--card:#fff;--card2:#eceae6;--tx:#1b1a18;--dim:#6b665f;
--line:#dedad3;--acc:#8a5f14;--warn:#8a5f14;--ya:#8a2f2f;--yatx:#fff;
--onacc:#fff;--header:rgba(246,245,243,.96)}
}
:root[data-theme="light"]{
--bg:#f6f5f3;--card:#fff;--card2:#eceae6;--tx:#1b1a18;--dim:#6b665f;
--line:#dedad3;--acc:#8a5f14;--warn:#8a5f14;--ya:#8a2f2f;--yatx:#fff;
--onacc:#fff;--header:rgba(246,245,243,.96)}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{position:sticky;top:0;z-index:10;background:var(--header);
backdrop-filter:blur(8px);border-bottom:1px solid var(--line);padding:14px 20px}
h1{margin:0 0 10px;font-size:19px;letter-spacing:.5px}
h1 small{color:var(--dim);font-weight:400;font-size:13px;letter-spacing:0}
.controles{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
input[type=search]{flex:1;min-width:200px;background:var(--card);color:var(--tx);
border:1px solid var(--line);border-radius:7px;padding:8px 11px;font-size:14px}
button.filtro{background:var(--card);color:var(--tx);border:1px solid var(--line);
border-radius:7px;padding:8px 13px;font-size:14px;cursor:pointer}
button.filtro[aria-pressed=true]{background:var(--acc);border-color:var(--acc);color:var(--onacc);font-weight:600}
.cuenta{color:var(--dim);font-size:13px;margin-left:auto}
main{display:grid;gap:14px;padding:18px 20px 60px;
grid-template-columns:repeat(auto-fill,minmax(290px,1fr));max-width:1700px;margin:0 auto}
.card{background:var(--card);border:1px solid var(--line);border-radius:11px;
overflow:hidden;display:flex;flex-direction:column}
/* Without this the filters do nothing: the JS sets .hidden, but an author
   `display:flex` beats the browser's `[hidden]{display:none}` every time. */
.card[hidden]{display:none}
.card.past{opacity:.5}
.flyer{aspect-ratio:1;background:var(--card2);overflow:hidden;position:relative}
.flyer img{width:100%;height:100%;object-fit:cover;display:block}
.sinflyer{display:grid;place-items:center;height:100%;color:var(--dim);font-size:13px}
.compra{display:block;height:100%;position:relative}
.compra .overlay{position:absolute;left:0;right:0;bottom:0;padding:7px 10px;
background:linear-gradient(transparent,rgba(0,0,0,.82));color:#fff;font-size:12.5px;
font-weight:600;opacity:0;transition:opacity .13s}
.compra:hover .overlay,.compra:focus-visible .overlay{opacity:1}
.compra::after{content:"🎟";position:absolute;top:7px;right:8px;font-size:14px;
background:rgba(0,0,0,.55);border-radius:5px;padding:2px 5px;line-height:1}
.cuerpo{padding:12px 13px 13px;display:flex;flex-direction:column;gap:7px;flex:1}
.cab{display:flex;gap:8px;align-items:flex-start}
.cab h2{margin:0;font-size:15px;line-height:1.25;flex:1;letter-spacing:.3px}
.titulo{color:var(--tx);text-decoration:none}
a.titulo{border-bottom:1px dotted var(--dim)}
a.titulo:hover{color:var(--acc);border-bottom-color:var(--acc)}
.fav{background:none;border:0;color:var(--dim);font-size:22px;line-height:1;
cursor:pointer;padding:0 2px}
.card.is-fav .fav{color:var(--acc)}
.acto{border-left:2px solid var(--line);padding-left:8px}
.acto-cab{font-size:13px;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.acto-cab a{color:var(--tx);text-decoration:none;border-bottom:1px dotted var(--dim)}
.src{font-size:9px;padding:1px 4px;border-radius:3px;background:var(--card2);
color:var(--dim);letter-spacing:.5px}
.src-metal-archives{color:#8fbf7a}
.src-spirit-of-metal{color:#7aa8bf}
.warn{color:var(--warn);cursor:help}
.info{color:var(--dim);cursor:help}
.genero{font-size:13px;color:var(--tx);display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.pais{font-size:12px;color:var(--dim)}
.pie{display:flex;gap:9px;align-items:baseline;margin-top:auto;padding-top:6px;flex-wrap:wrap}
.fecha{font-weight:600;font-size:14px}
.falta{font-size:11.5px;padding:2px 7px;border-radius:999px;background:var(--card2);
color:var(--dim);white-space:nowrap}
.falta.pronto{background:var(--acc);color:var(--onacc);font-weight:600}
.falta.ya{background:var(--ya);color:var(--yatx)}
.precio{color:var(--dim);font-size:12.5px;width:100%}
.lugar{font-size:12.5px;color:var(--dim)}
.acciones{display:flex;gap:7px;flex-wrap:wrap;padding-top:3px}
.tix{font-size:12.5px;padding:4px 9px;border-radius:6px;background:var(--acc);
color:var(--onacc);text-decoration:none;font-weight:600}
.tix.off{background:var(--card2);color:var(--dim);font-weight:400}
.mas{font-size:12.5px;padding:4px 9px;border-radius:6px;background:var(--card2);
color:var(--dim);text-decoration:none}
.vacio{grid-column:1/-1;text-align:center;color:var(--dim);padding:50px 20px}
/* Telefono: una columna, controles apilados, objetivos tactiles mas grandes. */
@media(max-width:520px){
header{padding:11px 13px}
main{padding:13px 13px 50px;gap:11px;grid-template-columns:1fr}
h1{font-size:17px}
.controles{gap:8px}
input[type=search]{min-width:0;width:100%;font-size:16px}
.cuenta{margin-left:0}
.fav{font-size:27px;padding:0 6px}
}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
"""

JS = """
const KEY='metaldaze.favoritos';
const favs=new Set(JSON.parse(localStorage.getItem(KEY)||'[]'));
const cards=[...document.querySelectorAll('.card')];
const q=document.getElementById('q');
const bFav=document.getElementById('soloFav');
const bPast=document.getElementById('verPasados');
const cuenta=document.getElementById('cuenta');

function guardar(){localStorage.setItem(KEY,JSON.stringify([...favs]))}

// Cuanto falta, calculado en el navegador y no al generar la pagina. Asi la
// cuenta sigue siendo correcta aunque el HTML tenga dias o meses de viejo,
// que es justo lo que pasa con la copia publicada como artifact.
function cuantoFalta(dias){
  if(dias<0)  return {txt:'pasó', clase:'ya'};
  if(dias===0)return {txt:'hoy', clase:'ya'};
  if(dias===1)return {txt:'mañana', clase:'pronto'};
  if(dias<7)  return {txt:'en '+dias+' días', clase:'pronto'};
  if(dias<28){const s=Math.round(dias/7);return {txt:'en '+s+(s===1?' semana':' semanas'), clase:''}}
  if(dias<345){const m=Math.max(1,Math.round(dias/30.44));return {txt:'en '+m+(m===1?' mes':' meses'), clase:''}}
  const a=Math.round(dias/365);
  return {txt:'en '+a+(a===1?' año':' años'), clase:''};
}

function fechar(){
  const hoy=new Date(); hoy.setHours(0,0,0,0);
  cards.forEach(c=>{
    const iso=c.dataset.date;
    const tag=c.querySelector('.falta');
    if(!iso){tag.hidden=true;return}
    const [y,m,d]=iso.split('-').map(Number);
    const cuando=new Date(y,m-1,d);
    const dias=Math.round((cuando-hoy)/86400000);
    const r=cuantoFalta(dias);
    tag.textContent=r.txt;
    tag.className='falta '+r.clase;
    tag.hidden=false;
    // El pasado se recalcula acá también, para que una copia vieja de la
    // página siga archivando sola los shows que ya ocurrieron.
    const paso=dias<0;
    c.dataset.past=paso?'1':'0';
    c.classList.toggle('past',paso);
  });
}

function pintar(){
  cards.forEach(c=>c.classList.toggle('is-fav',favs.has(c.dataset.band)));
  cards.forEach(c=>{
    const b=c.querySelector('.fav');
    b.textContent=favs.has(c.dataset.band)?'★':'☆';
  });
}

function filtrar(){
  const txt=q.value.trim().toLowerCase();
  const soloFav=bFav.getAttribute('aria-pressed')==='true';
  const verPast=bPast.getAttribute('aria-pressed')==='true';
  let n=0;
  cards.forEach(c=>{
    const esPasado=c.dataset.past==='1';
    let ok=true;
    if(esPasado&&!verPast) ok=false;
    if(soloFav&&!favs.has(c.dataset.band)) ok=false;
    if(ok&&txt&&!c.dataset.search.includes(txt)&&!c.dataset.band.toLowerCase().includes(txt)) ok=false;
    c.hidden=!ok;
    if(ok) n++;
  });
  cuenta.textContent=n+(n===1?' show':' shows');
  document.getElementById('vacio').hidden=n>0;
}

cards.forEach(c=>{
  c.querySelector('.fav').addEventListener('click',()=>{
    const b=c.dataset.band;
    // Una banda puede tocar varias veces: la estrella marca todos sus shows.
    favs.has(b)?favs.delete(b):favs.add(b);
    guardar();pintar();filtrar();
  });
});

[bFav,bPast].forEach(b=>b.addEventListener('click',()=>{
  b.setAttribute('aria-pressed',b.getAttribute('aria-pressed')!=='true');
  filtrar();
}));
q.addEventListener('input',filtrar);
fechar();pintar();filtrar();
"""


def render(rows, generado):
    total = len(rows)
    proximos = sum(1 for _, _, _, past in rows if not past)
    cards = "\n".join(_card(s, a, f, p) for s, a, f, p in rows)
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agenda Metal-Daze</title>
<style>{CSS}</style>
</head>
<body>
<header>
<h1>Agenda Metal-Daze <small>{proximos} próximos de {total} · actualizado {html.escape(generado)}</small></h1>
<div class="controles">
<input type="search" id="q" placeholder="Buscar banda, género, país o lugar…" autocomplete="off">
<button class="filtro" id="soloFav" type="button" aria-pressed="false">★ Solo favoritos</button>
<button class="filtro" id="verPasados" type="button" aria-pressed="false">Ver pasados</button>
<span class="cuenta" id="cuenta"></span>
</div>
</header>
<main>
{cards}
<p class="vacio" id="vacio" hidden>Nada coincide con el filtro.</p>
</main>
<script>{JS}</script>
</body>
</html>
"""


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def rebuild(current, cache_image, log):
    """Regenerate dashboard.html from the current agenda plus the archive.

    current      {key: show} as parsed from the agenda this run
    cache_image  callable(url) -> local path or None
    log          callable(str)
    """
    archive = load_archive()
    archive.update(current)          # current wins; past shows stay on
    save_archive(archive)

    bands = load_genres()
    before = len(bands)
    hoy = date.today()

    rows = []
    omitidos = 0
    for show in sorted(archive.values(), key=show_date):
        if excluido(show):
            omitidos += 1
            continue
        acts = resolve_title(show.get("title", ""), show, bands, log)
        flyer = _flyer(show, cache_image)
        rows.append((show, acts, flyer, show_date(show) < hoy))

    if len(bands) != before:
        save_genres(bands)

    generado = datetime.now().strftime("%d/%m/%Y %H:%M")
    tmp = DASHBOARD_FILE.with_suffix(".html.tmp")
    tmp.write_text(render(rows, generado), encoding="utf-8")
    tmp.replace(DASHBOARD_FILE)

    pasados = sum(1 for *_, past in rows if past)
    con_flyer = sum(1 for _, _, f, _ in rows if f)
    esperados = sum(1 for s in archive.values() if s.get("image_url") and not excluido(s))
    if esperados and not con_flyer:
        log(f"WARNING: dashboard written with 0 flyers but {esperados} shows have one. "
            f"Was cache_image passed correctly?")
    log(f"dashboard: {len(rows)} shows ({pasados} pasados, {omitidos} omitidos por lugar), "
        f"{con_flyer} con flyer, {len(bands) - before} títulos nuevos resueltos "
        f"-> {DASHBOARD_FILE.name}")
    return DASHBOARD_FILE
