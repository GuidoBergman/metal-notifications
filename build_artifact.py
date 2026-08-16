#!/usr/bin/env python3
"""Build a self-contained copy of the dashboard, for publishing as an Artifact.

An Artifact is served under a strict CSP that blocks every external host, so the
page cannot reference images/ the way the local dashboard does. Every flyer has
to travel inside the HTML as a data: URI, and the whole page has to fit in 16 MB.
The flyers are 43 MB on disk and base64 adds a third on top, so they get scaled
down and recompressed here.

The result is a snapshot. Cron cannot republish it, so the show list freezes at
the moment you run this. The countdown does not freeze: dashboard.py computes it
in the browser, so "en 2 semanas" keeps counting down and past shows keep
archiving themselves even on an old copy.

    python3 build_artifact.py            # -> artifact_dashboard.html

Needs Pillow, unlike the rest of the project. It is a publishing tool, not part
of the hourly run, so the cron path stays stdlib-only.
"""
import base64
import re
import io
import sys
from datetime import date, datetime
from pathlib import Path

from PIL import Image

import dashboard as d

LADO_MAX = 420        # flyers render at ~290 px wide, so 420 covers 2x screens
CALIDAD = 72
LIMITE_MB = 16
SALIDA = d.HERE / "artifact_dashboard.html"


def miniatura(path):
    """Scale and recompress one flyer into a data: URI."""
    try:
        im = Image.open(path)
        im = im.convert("RGB")
        im.thumbnail((LADO_MAX, LADO_MAX), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=CALIDAD, optimize=True, progressive=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as e:  # noqa: BLE001
        print(f"  no pude procesar {path.name}: {e}")
        return ""


def fragmento(pagina):
    """Strip the document wrapper: the Artifact host supplies its own.

    Keeps the <title>, the <style>, everything that was inside <body>, and the
    <script>. Drops <!doctype>, <html>, <head>, <meta> and the body tags.
    """
    titulo = re.search(r"<title>.*?</title>", pagina, re.S).group(0)
    estilo = re.search(r"<style>.*?</style>", pagina, re.S).group(0)
    cuerpo = re.search(r"<body>(.*)</body>", pagina, re.S).group(1).strip()
    return f"{titulo}\n{estilo}\n{cuerpo}\n"


def main():
    archive = d.load_archive()
    if not archive:
        print("dashboard_archive.json está vacío. Corré antes: python3 monitor.py dashboard")
        return 1

    bands = d.load_genres()
    hoy = date.today()
    rows, sin_flyer, bytes_img = [], 0, 0

    for show in sorted(archive.values(), key=d.show_date):
        if d.excluido(show):
            continue
        titulo = show.get("title", "")
        if titulo not in bands:
            # No network here on purpose: publishing must not trigger lookups.
            print(f"  sin género en genres.json, lo dejo vacío: {titulo}")
        acts = bands.get(titulo, {}).get("acts", [])

        # Reuse whatever monitor.py already cached; never download here.
        local = d._flyer(show, lambda url: _cacheado(url))
        if local:
            uri = miniatura(d.HERE / local)
            bytes_img += len(uri)
        else:
            uri, sin_flyer = "", sin_flyer + 1
        rows.append((show, acts, uri, d.show_date(show) < hoy))

    generado = datetime.now().strftime("%d/%m/%Y %H:%M")
    html = fragmento(d.render(rows, generado))
    SALIDA.write_text(html, encoding="utf-8")

    mb = len(html.encode("utf-8")) / 1e6
    print(f"{len(rows)} shows, {len(rows) - sin_flyer} con flyer, {sin_flyer} sin flyer")
    print(f"imágenes embebidas: {bytes_img / 1e6:.1f} MB de un total de {mb:.1f} MB")
    print(f"-> {SALIDA}")
    if mb > LIMITE_MB:
        print(f"DEMASIADO GRANDE: {mb:.1f} MB supera el límite de {LIMITE_MB} MB. "
              f"Bajá LADO_MAX o CALIDAD.")
        return 1
    return 0


def _cacheado(url):
    """cache_image, but read-only: return the cached path or nothing."""
    import hashlib
    import os
    name = hashlib.sha1(url.encode("utf-8")).hexdigest()
    ext = os.path.splitext(url.split("?")[0])[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        ext = ".jpg"
    path = d.IMG_DIR / f"{name}{ext}"
    return str(path) if path.exists() and path.stat().st_size > 0 else None


if __name__ == "__main__":
    sys.exit(main())
