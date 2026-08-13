#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor de oportunidades - Banqueteria Gran Concepcion
-----------------------------------------------------
Lee el feed RSS de Mercado Publico (filtrado por los rubros de la cuenta),
detecta la zona (Gran Concepcion / Biobio / Nacional), marca palabras clave
de banqueteria, y (opcional) enriquece cada licitacion con su fecha de cierre
y monto usando la API oficial si hay un ticket disponible.

Escribe data.json, que el tablero (index.html) muestra.

Sin dependencias externas: usa solo la libreria estandar de Python.
Corre en GitHub Actions cada 12 h.

Variables de entorno (todas opcionales):
  MP_ORGCODE   -> OrgCode del feed RSS (default 891391)
  MP_TICKET    -> ticket de la API de Mercado Publico (para enriquecer cierre/monto)
  MP_FEED_FILE -> si se define, lee el RSS desde un archivo local (para pruebas)
  MP_OUT       -> ruta de salida (default data.json)
"""

import os
import re
import json
import html
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone, timedelta, date
from xml.etree import ElementTree as ET

ORGCODE   = os.environ.get("MP_ORGCODE", "891391")
TICKET    = os.environ.get("MP_TICKET", "").strip()
FEED_FILE = os.environ.get("MP_FEED_FILE", "").strip()
OUT       = os.environ.get("MP_OUT", "data.json")

FEED_URL = f"https://www.mercadopublico.cl/Portal/feed.aspx?OrgCode={ORGCODE}"
API_URL  = "https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json"

# Compra Agil: API publica del buscador (sin ticket). Filtra por palabra clave.
# NOTA: el endpoint bloquea peticiones de servidores (403). Por eso, desde
# GitHub Actions esta parte se deja DESACTIVADA. Se reactiva poniendo
# MP_CA_ACTIVO=1 (util cuando se ejecute desde un navegador real).
CA_ACTIVO    = os.environ.get("MP_CA_ACTIVO", "0") == "1"
CA_URL       = "https://api.buscador.mercadopublico.cl/compra-agil"
CA_DIAS      = int(os.environ.get("MP_CA_DIAS", "6"))       # ventana hacia atras
CA_MAX_PAGES = int(os.environ.get("MP_CA_MAX_PAGES", "6"))  # tope de paginas por keyword
CA_KEYWORDS  = [
    "COFFEE BREAK", "CATERING", "BANQUETERIA", "ALIMENTACION",
    "COCTEL", "EMPANADA", "ALMUERZO", "COLACION", "CAFETERIA",
]

# Cabeceras de navegador real: el endpoint tiene deteccion de bots.
CA_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://buscador.mercadopublico.cl",
    "Referer": "https://buscador.mercadopublico.cl/",
}

# Chile usa UTC-4 (o -3 en verano). El feed entrega hora local sin zona;
# la tratamos como -04:00 de forma estable para el conteo.
TZ_CL = timezone(timedelta(hours=-4))

GRAN_CONCEPCION = [
    "CONCEPCION", "CONCEPCIÓN", "TALCAHUANO", "SAN PEDRO DE LA PAZ",
    "PENCO", "CHIGUAYANTE", "HUALPEN", "HUALPÉN",
    "SALUD CONCEPCION", "SALUD TALCAHUANO",
]

BIOBIO = [
    "CORONEL", "LOTA", "TOME", "TOMÉ", "HUALQUI", "SANTA JUANA",
    "LOS ANGELES", "LOS ÁNGELES", "CABRERO", "YUMBEL", "LAJA",
    "NACIMIENTO", "MULCHEN", "MULCHÉN", "ARAUCO", "CAÑETE", "CANETE",
    "CURANILAHUE", "LEBU", "CONTULMO", "TIRUA", "TIRÚA", "LOS ALAMOS",
    "SAN ROSENDO", "QUILLECO", "ANTUCO", "TUCAPEL", "NEGRETE", "QUILACO",
    "BIO BIO", "BIOBIO", "BÍO-BÍO", "BIO-BÍO", "BÍO BÍO",
    "REGION DEL BIO", "REGIÓN DEL BÍO", "VIII REGION", "VIII REGIÓN",
]

# Palabras clave que confirman que la oportunidad es de banqueteria / eventos.
KEYWORDS = [
    "catering", "banqueter", "banquete", "coffee break", "coffe break",
    "coctel", "cóctel", "cocteler", "alimentaci", "colacion", "colación",
    "almuerzo", "empanada", "produccion de evento", "producción de evento",
    "servicio de produccion", "servicio de producción", "aniversario",
    "fiestas patrias", "chilenidad", "cafeteria", "cafetería", "vino de honor",
    "menaje", "casino", "suministro de aliment",
]


def log(*a):
    print("[motor]", *a, file=sys.stderr)


def fetch_feed():
    if FEED_FILE:
        log("leyendo feed local:", FEED_FILE)
        with open(FEED_FILE, "r", encoding="utf-8") as f:
            return f.read()
    log("descargando feed:", FEED_URL)
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": "Mozilla/5.0 (motor-banqueteria)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_feed(xml_text):
    """Devuelve lista de dicts base a partir del RSS."""
    items = []
    root = ET.fromstring(xml_text)
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        desc  = (it.findtext("description") or "").strip()
        pub   = (it.findtext("pubDate") or "").strip()
        link  = (it.findtext("link") or "").strip()

        desc = html.unescape(desc)
        # title: "Id: XXXX-YY-LE26 Nombre: ...."
        m = re.match(r"Id:\s*(\S+)\s*Nombre:\s*(.*)", title, re.S)
        code = m.group(1).strip() if m else ""
        nombre = (m.group(2).strip() if m else title)

        # description: "Comprador: XXX<br/>Descripcion: YYY"
        comprador, descripcion = "", ""
        dm = re.search(r"Comprador:\s*(.*?)\s*(?:<br\s*/?>|\n)\s*Descripcion:\s*(.*)", desc, re.S | re.I)
        if dm:
            comprador = re.sub(r"\s+", " ", dm.group(1)).strip()
            descripcion = re.sub(r"\s+", " ", dm.group(2)).strip()
        else:
            comprador = re.sub(r"\s+", " ", desc).strip()

        items.append({
            "id": code,
            "nombre": nombre,
            "organismo": comprador,
            "descripcion": descripcion[:400],
            "publicada": normalize_date(pub),
            "link": link,
            "tipo": tipo_from_code(code),
        })
    return items


def tipo_from_code(code):
    # 1234-56-LE26 -> "LE"
    m = re.search(r"-([A-Za-z]{1,3})\d{2}$", code)
    return m.group(1).upper() if m else ""


def normalize_date(pub):
    # "2026-08-12T17:18:33.360" o "2026-08-14 15:00:00" -> ISO con zona -04:00
    if not pub:
        return ""
    pub = pub.strip().replace("Z", "").replace(" ", "T")
    try:
        dt = datetime.fromisoformat(pub.split(".")[0])
        dt = dt.replace(tzinfo=TZ_CL)
        return dt.isoformat()
    except Exception:
        return pub


def _palabra(token, texto):
    """True si token aparece como palabra/frase completa (no como fragmento)."""
    patron = r"(?<![0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ])" + re.escape(token) + r"(?![0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ])"
    return re.search(patron, texto) is not None


def zona_de(texto):
    t = (texto or "").upper()
    for k in GRAN_CONCEPCION:
        if _palabra(k, t):
            return "Gran Concepción"
    for k in BIOBIO:
        if _palabra(k, t):
            return "Biobío"
    return "Nacional"


def comuna_de(texto, zona):
    t = (texto or "").upper()
    nombres = {
        "TALCAHUANO": "Talcahuano", "SAN PEDRO DE LA PAZ": "San Pedro de la Paz",
        "CHIGUAYANTE": "Chiguayante", "HUALPEN": "Hualpén", "HUALPÉN": "Hualpén",
        "PENCO": "Penco", "CONCEPCION": "Concepción", "CONCEPCIÓN": "Concepción",
        "CORONEL": "Coronel", "LOTA": "Lota", "TOME": "Tomé", "TOMÉ": "Tomé",
        "HUALQUI": "Hualqui", "CABRERO": "Cabrero", "LOS ANGELES": "Los Ángeles",
        "ARAUCO": "Arauco", "CAÑETE": "Cañete", "CONTULMO": "Contulmo",
    }
    for k, v in nombres.items():
        if _palabra(k, t):
            return v
    return zona


def keywords_de(texto):
    t = (texto or "").lower()
    found = []
    for k in KEYWORDS:
        if k in t:
            label = {
                "banqueter": "banquetería", "banquete": "banquetería",
                "coctel": "cóctel", "cóctel": "cóctel", "cocteler": "cóctel",
                "alimentaci": "alimentación", "produccion de evento": "producción de eventos",
                "producción de evento": "producción de eventos",
                "servicio de produccion": "producción", "servicio de producción": "producción",
                "cafeteria": "cafetería", "cafetería": "cafetería",
                "coffe break": "coffee break", "colacion": "colación", "colación": "colación",
                "suministro de aliment": "suministro de alimentos",
            }.get(k, k)
            if label not in found:
                found.append(label)
    return found[:4]


# La API de Mercado Publico es sensible al ritmo: si se le consulta muy seguido
# responde 429 (Too Many Requests). Vamos despacio y reintentamos con esperas
# crecientes cuando eso ocurre.
API_PAUSA = float(os.environ.get("MP_API_PAUSA", "2.0"))   # segundos entre consultas
API_REINTENTOS = int(os.environ.get("MP_API_REINTENTOS", "4"))


def _api_get(url):
    """GET con reintentos ante 429/errores transitorios. Devuelve dict o None."""
    espera = 5
    for intento in range(API_REINTENTOS):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "motor-banqueteria"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and intento < API_REINTENTOS - 1:
                log(f"429, esperando {espera}s y reintentando...")
                time.sleep(espera)
                espera *= 2   # 5s, 10s, 20s...
                continue
            raise
    return None


def enrich_api(item):
    """Si hay ticket, consulta la ficha para obtener fecha de cierre y monto."""
    if not TICKET or not item.get("id"):
        return
    url = f"{API_URL}?codigo={urllib.parse.quote(item['id'])}&ticket={urllib.parse.quote(TICKET)}"
    try:
        data = _api_get(url)
        if not data:
            return
        listado = data.get("Listado") or []
        if not listado:
            return
        d = listado[0]
        fechas = d.get("Fechas") or {}
        cierre = fechas.get("FechaCierre") or d.get("FechaCierre")
        if cierre:
            item["fecha_cierre"] = normalize_date(cierre)
        monto = d.get("MontoEstimado")
        if monto:
            item["monto_label"] = f"${int(monto):,}".replace(",", ".")
    except Exception as e:
        log("API sin dato para", item.get("id"), "-", e)
    finally:
        time.sleep(API_PAUSA)   # ritmo suave entre consultas


def _ca_get(url):
    """GET al buscador de Compra Agil con cabeceras de navegador y reintentos."""
    espera = 5
    for intento in range(4):
        try:
            req = urllib.request.Request(url, headers=CA_HEADERS)
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 403) and intento < 3:
                log(f"CA {e.code}, esperando {espera}s...")
                time.sleep(espera)
                espera *= 2
                continue
            log("CA HTTPError", e.code, "-", url[:80])
            return None
        except Exception as e:
            log("CA error:", e)
            return None
    return None


def fetch_compra_agil():
    """Consulta Compra Agil por cada palabra clave y devuelve items (solo abiertas)."""
    hoy = date.today()
    dfrom = (hoy - timedelta(days=CA_DIAS)).isoformat()
    dto = hoy.isoformat()
    vistos = set()
    items = []
    bloqueado = True

    for kw in CA_KEYWORDS:
        page = 1
        while page <= CA_MAX_PAGES:
            q = urllib.parse.urlencode({
                "date_from": dfrom, "date_to": dto, "keywords": kw,
                "order_by": "recent", "status": "2",   # 2 = Publicada (abierta)
                "page": page, "pageSize": 100,
            })
            data = _ca_get(f"{CA_URL}?{q}")
            if data is None:
                break
            bloqueado = False
            payload = data.get("payload") or {}
            res = payload.get("resultados") or []
            for r in res:
                cod = r.get("codigo") or str(r.get("id", ""))
                if not cod or cod in vistos:
                    continue
                vistos.add(cod)
                org = (r.get("organismo") or "").strip()
                if r.get("unidad"):
                    org = f"{org} - {r['unidad']}"
                monto = r.get("monto_disponible_CLP") or r.get("monto_disponible")
                items.append({
                    "id": cod,
                    "nombre": (r.get("nombre") or "").strip(),
                    "organismo": org,
                    "descripcion": (r.get("nombre") or ""),
                    "publicada": normalize_date(r.get("fecha_publicacion") or ""),
                    "fecha_cierre": normalize_date(r.get("fecha_cierre") or ""),
                    "link": "https://buscador.mercadopublico.cl/compra-agil",
                    "tipo": "Compra Ágil",
                    "monto_label": (f"${int(monto):,}".replace(",", ".") if monto else ""),
                })
            pc = payload.get("pageCount") or 1
            if page >= pc:
                break
            page += 1
            time.sleep(1.5)
        time.sleep(1.0)

    if bloqueado:
        log("Compra Agil: el endpoint no respondio (posible bloqueo).")
    else:
        log("Compra Agil: recolectadas", len(items), "solicitudes (antes de filtrar zona)")
    return items


def main():
    xml_text = fetch_feed()
    base = parse_feed(xml_text)
    log("items en el feed:", len(base))

    vistos = set()
    out = []
    descartadas = 0
    for it in base:
        if it["id"] in vistos:
            continue
        vistos.add(it["id"])

        blob = f"{it['organismo']} {it['nombre']} {it['descripcion']}"
        it["zona"] = zona_de(it["organismo"])
        it["comuna"] = comuna_de(it["organismo"], it["zona"])

        # Guardar SOLO Región del Biobío (incluye Gran Concepción).
        # Para decidir miramos organismo + descripción, así no perdemos
        # oportunidades reales de la región cuyo comprador no nombra la comuna
        # (p. ej. ministerios que dicen "VIII Región" o "Biobío" en el texto).
        if it["zona"] == "Nacional" and zona_de(blob) != "Nacional":
            it["zona"] = zona_de(blob)  # rescate por descripción
            it["comuna"] = comuna_de(blob, it["zona"])
        if it["zona"] == "Nacional":
            descartadas += 1
            continue

        it["keywords"] = keywords_de(blob)
        it["fuente"] = "Licitación"
        it["monto_label"] = it.get("monto_label", "")
        it.pop("descripcion", None)
        out.append(it)

    log("descartadas por fuera de Biobío:", descartadas)

    # --- Compra Ágil (fuente independiente, ya trae cierre y monto) ---
    ca = fetch_compra_agil() if CA_ACTIVO else []
    if not CA_ACTIVO:
        log("Compra Ágil: desactivada (MP_CA_ACTIVO=0). Solo licitaciones.")
    ca_desc = 0
    for it in ca:
        if it["id"] in vistos:
            continue
        vistos.add(it["id"])
        blob = f"{it['organismo']} {it['nombre']} {it['descripcion']}"
        it["zona"] = zona_de(it["organismo"])
        it["comuna"] = comuna_de(it["organismo"], it["zona"])
        if it["zona"] == "Nacional" and zona_de(blob) != "Nacional":
            it["zona"] = zona_de(blob)
            it["comuna"] = comuna_de(blob, it["zona"])
        if it["zona"] == "Nacional":
            ca_desc += 1
            continue
        it["keywords"] = keywords_de(blob)
        it["fuente"] = "Compra Ágil"
        it.pop("descripcion", None)
        out.append(it)
    log("Compra Ágil en Biobío:", len([o for o in out if o["fuente"] == "Compra Ágil"]),
        "| descartadas fuera de zona:", ca_desc)

    # enriquecer con API solo las LICITACIONES (Compra Ágil ya viene completa)
    if TICKET:
        log("enriqueciendo licitaciones con API (ticket presente)...")
        for it in out:
            if it.get("fuente") == "Licitación":
                enrich_api(it)

    payload = {
        "generado": datetime.now(TZ_CL).isoformat(),
        "orgcode": ORGCODE,
        "fuente_api": bool(TICKET),
        "total": len(out),
        "oportunidades": out,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    log("escrito", OUT, "con", len(out), "oportunidades")

    # resumen
    from collections import Counter
    log("por zona:", dict(Counter(o["zona"] for o in out)))
    log("por fuente:", dict(Counter(o["fuente"] for o in out)))


if __name__ == "__main__":
    import urllib.parse  # noqa
    main()
