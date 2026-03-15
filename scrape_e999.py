#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import html
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from xml.dom import minidom
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

ENVIVO_URL = "https://elcanaldelfutbol.com/envivo/"
PROGRAMACION_URL = "https://www.elcanaldelfutbol.com/programacion"
TIMEZONE = ZoneInfo("America/Guayaquil")
CHANNEL_ID = "e999.ec"
DISPLAY_NAMES = ["E999", "ECDF", "El Canal del Fútbol"]
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"
)
RANGE_RE = re.compile(r"^(?P<start>\d{1,2}:\d{2})\s*[-–—]\s*(?P<stop>\d{1,2}:\d{2})$")
INLINE_RANGE_RE = re.compile(r"^(?P<title>.+?)\s+(?P<start>\d{1,2}:\d{2})\s*[-–—]\s*(?P<stop>\d{1,2}:\d{2})$")
HERO_RANGE_RE = re.compile(
    r"^[A-Z]?\s*·\s*(?P<start>\d{1,2}(?::\d{2})?\s*(?:a\.m\.|p\.m\.|am|pm))\s*[–-]\s*(?P<stop>\d{1,2}(?::\d{2})?\s*(?:a\.m\.|p\.m\.|am|pm))$",
    re.IGNORECASE,
)
PROGRAMACION_ROW_RE = re.compile(
    r"^(?P<time>(?:\d{1,2}(?::\d{2})?\s*(?:a\.m\.|p\.m\.|am|pm)|noon))\s+(?P<title>.+)$",
    re.IGNORECASE,
)
DAY_LABEL_RE = re.compile(
    r"^(?P<day>lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo|mon|monday|tue|tuesday|wed|wednesday|thu|thursday|fri|friday|sat|saturday|sun|sunday)\s+(?P<daynum>\d{1,2})$",
    re.IGNORECASE,
)
IGNORE_EXACT = {
    "Guía de Programación",
    "En vivo",
    "Canales",
    "Todos los canales Fútbol Hípica Golf",
    "Todos los canales",
    "quedan:",
    "empty !!",
    "Suscríbete para continuar",
    "Ir a contratar",
    "El Canal del Fútbol",
    "P",
}
IGNORE_PREFIXES = (
    "Suscríbete",
    "Este contenido requiere",
    "Términos y Condiciones",
    "Terminos y Condiciones",
    "202",
    "Iniciar Sesión",
    "Contratar",
)


class ScrapeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Programme:
    start: dt.datetime
    stop: dt.datetime
    title: str


def request_text(url: str) -> str:
    response = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "es-EC,es;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": "https://www.elcanaldelfutbol.com/",
        },
        timeout=45,
    )
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return response.text


def playwright_text(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(
                user_agent=USER_AGENT,
                locale="es-EC",
                timezone_id="America/Guayaquil",
            )
            page.set_extra_http_headers(
                {
                    "Accept-Language": "es-EC,es;q=0.9,en;q=0.8",
                    "Referer": "https://www.elcanaldelfutbol.com/",
                }
            )
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(4000)
            return page.content()
        finally:
            browser.close()


def jina_urls(url: str) -> list[str]:
    urls = [f"https://r.jina.ai/{url}"]
    if url.startswith("https://"):
        urls.append(f"https://r.jina.ai/http://{url[len('https://'):]}")
    elif url.startswith("http://"):
        urls.append(f"https://r.jina.ai/https://{url[len('http://'):]}")
    deduped: list[str] = []
    seen: set[str] = set()
    for item in urls:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


def jina_text(url: str) -> str:
    response = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/plain,text/markdown;q=0.9,*/*;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
        timeout=60,
    )
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return response.text


def text_to_lines(text: str) -> list[str]:
    if "<html" in text.lower() or "<!doctype" in text.lower():
        soup = BeautifulSoup(text, "html.parser")
        for node in soup(["script", "style", "noscript", "svg"]):
            node.decompose()
        text = soup.get_text("\n")
    lines: list[str] = []
    for raw in text.splitlines():
        line = " ".join(raw.split()).strip()
        if line:
            lines.append(line)
    return lines


def is_noise(line: str) -> bool:
    if not line:
        return True
    if line in IGNORE_EXACT:
        return True
    if line.startswith("http://") or line.startswith("https://"):
        return True
    if line.startswith("【") and "†" in line:
        return True
    if any(line.startswith(prefix) for prefix in IGNORE_PREFIXES):
        return True
    if DAY_LABEL_RE.match(line):
        return True
    if RANGE_RE.match(line):
        return True
    if INLINE_RANGE_RE.match(line):
        return True
    if PROGRAMACION_ROW_RE.match(line):
        return False
    if re.fullmatch(r"\d+", line):
        return True
    return False


def clean_title(title: str) -> str:
    title = re.sub(r"\s*\[[^\]]+\]\([^\)]+\)", "", title).strip()
    title = re.sub(r"\s+Vivo$", "", title, flags=re.IGNORECASE).strip()
    title = re.sub(r"\s+En\s+vivo$", "", title, flags=re.IGNORECASE).strip()
    return html.unescape(title)


def parse_24h(token: str) -> int:
    hour, minute = map(int, token.split(":"))
    return hour * 60 + minute


def parse_12h(token: str) -> int:
    norm = token.lower().replace(" ", "")
    norm = norm.replace("a.m.", "am").replace("p.m.", "pm")
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)", norm)
    if not match:
        raise ScrapeError(f"Could not parse 12-hour token: {token}")
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    suffix = match.group(3)
    if suffix == "am":
        if hour == 12:
            hour = 0
    else:
        if hour != 12:
            hour += 12
    return hour * 60 + minute


def build_dt(base_date: dt.date, minutes: int) -> dt.datetime:
    hour, minute = divmod(minutes, 60)
    return dt.datetime.combine(base_date, dt.time(hour=hour, minute=minute), tzinfo=TIMEZONE)


def categories_for_title(title: str) -> list[str]:
    text = title.lower()
    categories = ["Deportes"]
    if "reprise" in text or "resumen" in text:
        categories.append("Repetición")
    if any(token in text for token in ["línea", "linea", "entrevista", "banda", "f de fútbol", "f de futbol"]):
        categories.append("Programa")
    if any(token in text for token in ["vs", "brasileirao", "liga", "superliga", "copa"]):
        categories.append("Fútbol")
    ordered: list[str] = []
    seen: set[str] = set()
    for category in categories:
        if category not in seen:
            ordered.append(category)
            seen.add(category)
    return ordered


def previous_title(lines: list[str], idx: int) -> str | None:
    for back in range(idx - 1, max(-1, idx - 5), -1):
        candidate = lines[back].strip()
        if is_noise(candidate):
            continue
        if HERO_RANGE_RE.match(candidate):
            continue
        if RANGE_RE.match(candidate) or INLINE_RANGE_RE.match(candidate):
            continue
        return clean_title(candidate)
    return None


def next_title(lines: list[str], idx: int) -> str | None:
    for fwd in range(idx + 1, min(len(lines), idx + 5)):
        candidate = lines[fwd].strip()
        if is_noise(candidate):
            continue
        if RANGE_RE.match(candidate) or INLINE_RANGE_RE.match(candidate):
            continue
        return clean_title(candidate)
    return None


def dedupe(programmes: list[Programme]) -> list[Programme]:
    unique: list[Programme] = []
    seen: set[tuple[str, str, str]] = set()
    for prog in sorted(programmes, key=lambda p: (p.start, p.stop, p.title.lower())):
        key = (prog.start.isoformat(), prog.stop.isoformat(), prog.title.strip().lower())
        if key in seen:
            continue
        if prog.stop <= prog.start:
            continue
        seen.add(key)
        unique.append(prog)
    return unique


def parse_envivo_today(lines: list[str], base_date: dt.date) -> list[Programme]:
    programmes: list[Programme] = []

    for line in lines:
        inline = INLINE_RANGE_RE.match(line)
        if inline:
            title = clean_title(inline.group("title"))
            if is_noise(title):
                continue
            start = parse_24h(inline.group("start"))
            stop = parse_24h(inline.group("stop"))
            start_dt = build_dt(base_date, start)
            stop_dt = build_dt(base_date, stop)
            if stop <= start:
                stop_dt += dt.timedelta(days=1)
            programmes.append(Programme(start_dt, stop_dt, title))

    for idx, line in enumerate(lines):
        direct = RANGE_RE.match(line)
        if not direct:
            continue
        title = previous_title(lines, idx)
        if not title:
            continue
        start = parse_24h(direct.group("start"))
        stop = parse_24h(direct.group("stop"))
        start_dt = build_dt(base_date, start)
        stop_dt = build_dt(base_date, stop)
        if stop <= start:
            stop_dt += dt.timedelta(days=1)
        programmes.append(Programme(start_dt, stop_dt, title))

    if len(programmes) >= 3:
        return dedupe(programmes)

    for idx, line in enumerate(lines):
        hero = HERO_RANGE_RE.match(line)
        if not hero:
            continue
        title = next_title(lines, idx)
        if not title:
            continue
        start = parse_12h(hero.group("start"))
        stop = parse_12h(hero.group("stop"))
        start_dt = build_dt(base_date, start)
        stop_dt = build_dt(base_date, stop)
        if stop <= start:
            stop_dt += dt.timedelta(days=1)
        programmes.append(Programme(start_dt, stop_dt, title))

    return dedupe(programmes)


WEEKDAY_NAMES = {
    0: {"mon", "monday", "lun", "lunes"},
    1: {"tue", "tuesday", "mar", "martes"},
    2: {"wed", "wednesday", "mie", "mié", "miercoles", "miércoles"},
    3: {"thu", "thursday", "jue", "jueves"},
    4: {"fri", "friday", "vie", "viernes"},
    5: {"sat", "saturday", "sab", "sáb", "sabado", "sábado"},
    6: {"sun", "sunday", "dom", "domingo"},
}


def find_today_row_block(lines: list[str], now: dt.datetime) -> list[tuple[int, str]]:
    today_tokens = WEEKDAY_NAMES[now.weekday()]
    start_idx: int | None = None
    for idx, line in enumerate(lines):
        match = DAY_LABEL_RE.match(line)
        if not match:
            continue
        token = match.group("day").lower()
        if token in today_tokens:
            start_idx = idx + 1
            break
    if start_idx is None:
        return []

    rows: list[tuple[int, str]] = []
    for idx in range(start_idx, len(lines)):
        line = lines[idx]
        if idx > start_idx and DAY_LABEL_RE.match(line):
            break
        match = PROGRAMACION_ROW_RE.match(line)
        if not match:
            continue
        title = clean_title(match.group("title"))
        if not title:
            continue
        time_token = match.group("time")
        if time_token.lower() == "noon":
            minutes = 12 * 60
        else:
            minutes = parse_12h(time_token)
        rows.append((minutes, title))
    return rows


def parse_programacion_today(lines: list[str], base_date: dt.date, now: dt.datetime) -> list[Programme]:
    rows = find_today_row_block(lines, now)
    rows = sorted(set(rows), key=lambda item: (item[0], item[1].lower()))
    programmes: list[Programme] = []
    for idx, (start_minutes, title) in enumerate(rows):
        start_dt = build_dt(base_date, start_minutes)
        if idx + 1 < len(rows):
            stop_minutes = rows[idx + 1][0]
            stop_dt = build_dt(base_date, stop_minutes)
        else:
            stop_dt = build_dt(base_date, 24 * 60 - 1) + dt.timedelta(minutes=1)
        if stop_dt <= start_dt:
            continue
        programmes.append(Programme(start_dt, stop_dt, title))
    return dedupe(programmes)


def fetch_candidates() -> Iterable[tuple[str, str, str]]:
    yield ("requests-html", ENVIVO_URL, request_text(ENVIVO_URL))
    yield ("playwright-html", ENVIVO_URL, playwright_text(ENVIVO_URL))
    for reader_url in jina_urls(ENVIVO_URL):
        yield (f"jina:{reader_url}", ENVIVO_URL, jina_text(reader_url))
    yield ("requests-html", PROGRAMACION_URL, request_text(PROGRAMACION_URL))
    yield ("playwright-html", PROGRAMACION_URL, playwright_text(PROGRAMACION_URL))
    for reader_url in jina_urls(PROGRAMACION_URL):
        yield (f"jina:{reader_url}", PROGRAMACION_URL, jina_text(reader_url))


def scrape_today(now: dt.datetime) -> tuple[list[Programme], str, str]:
    errors: list[str] = []
    base_date = now.date()

    for fetch_kind, origin_url, raw_text in fetch_candidates():
        try:
            lines = text_to_lines(raw_text)
            if origin_url == ENVIVO_URL:
                programmes = parse_envivo_today(lines, base_date)
            else:
                programmes = parse_programacion_today(lines, base_date, now)
            if len(programmes) >= 3:
                return programmes, origin_url, fetch_kind
            errors.append(f"{origin_url} via {fetch_kind} produced only {len(programmes)} programme rows")
        except Exception as exc:
            errors.append(f"{origin_url} via {fetch_kind} failed: {exc}")

    detail = " | ".join(errors) if errors else "no fetch attempts ran"
    raise ScrapeError(f"Could not parse a usable today-only schedule. {detail}")


def to_xmltv(programmes: list[Programme], source_url: str) -> str:
    generated = dt.datetime.now(TIMEZONE).strftime("%Y%m%d%H%M%S %z")
    tv = ET.Element(
        "tv",
        {
            "generator-info-name": "E999 today-only XMLTV generator",
            "source-info-name": "E999 (today-only from ECDF official guide)",
            "source-info-url": source_url,
            "date": generated,
        },
    )

    channel = ET.SubElement(tv, "channel", {"id": CHANNEL_ID})
    for display_name in DISPLAY_NAMES:
        ET.SubElement(channel, "display-name", {"lang": "es"}).text = display_name

    for programme in dedupe(programmes):
        prog_el = ET.SubElement(
            tv,
            "programme",
            {
                "channel": CHANNEL_ID,
                "start": programme.start.strftime("%Y%m%d%H%M%S %z"),
                "stop": programme.stop.strftime("%Y%m%d%H%M%S %z"),
            },
        )
        ET.SubElement(prog_el, "title", {"lang": "es"}).text = programme.title
        ET.SubElement(
            prog_el,
            "desc",
            {"lang": "es"},
        ).text = (
            "Programación de hoy obtenida de la guía oficial de ECDF. "
            "Los horarios se emiten en hora de Ecuador (-05:00)."
        )
        for category in categories_for_title(programme.title):
            ET.SubElement(prog_el, "category", {"lang": "es"}).text = category

    xml_bytes = ET.tostring(tv, encoding="utf-8")
    pretty = minidom.parseString(xml_bytes).toprettyxml(indent="  ", encoding="utf-8")
    return pretty.decode("utf-8")


def build_index(xml_name: str, schedule_note: str) -> str:
    xml_name = html.escape(xml_name, quote=True)
    envivo = html.escape(ENVIVO_URL, quote=True)
    programacion = html.escape(PROGRAMACION_URL, quote=True)
    schedule_note = html.escape(schedule_note, quote=True)
    return f"""<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
    <title>E999 XMLTV</title>
    <style>
      body {{ font-family: system-ui, sans-serif; margin: 2rem; line-height: 1.5; }}
      code {{ background: #f4f4f4; padding: .15rem .35rem; border-radius: 4px; }}
      a {{ color: #0b57d0; }}
    </style>
  </head>
  <body>
    <h1>E999 XMLTV</h1>
    <p>This feed publishes the official ECDF schedule as a <strong>today-only</strong> XMLTV guide.</p>
    <p><strong>XMLTV URL:</strong> <a href=\"{xml_name}\">{xml_name}</a></p>
    <p><strong>Main source:</strong> <a href=\"{envivo}\">{envivo}</a></p>
    <p><strong>Fallback source:</strong> <a href=\"{programacion}\">{programacion}</a></p>
    <p><strong>Refresh cadence:</strong> {schedule_note}</p>
    <p>Times in the XML are emitted in Ecuador time (<code>-0500</code>).</p>
  </body>
</html>
"""


def write_nojekyll(index_path: Path) -> None:
    nojekyll = index_path.parent / ".nojekyll"
    nojekyll.write_text("", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the E999 today-only XMLTV feed")
    parser.add_argument("--output", default="guide.xml", help="Path to write the XMLTV file")
    parser.add_argument("--index", default=None, help="Optional path for a landing page")
    parser.add_argument(
        "--schedule-note",
        default="GitHub Actions updates this site every 6 hours.",
        help="Text shown on the landing page describing the refresh cadence",
    )
    args = parser.parse_args()

    now = dt.datetime.now(TIMEZONE)

    try:
        programmes, source_url, _fetch_kind = scrape_today(now)
        if not programmes:
            raise ScrapeError("No programmes were created")

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(to_xmltv(programmes, source_url), encoding="utf-8")

        if args.index:
            index_path = Path(args.index)
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index_path.write_text(
                build_index(Path(args.output).name, args.schedule_note),
                encoding="utf-8",
            )
            write_nojekyll(index_path)

        return 0
    except Exception as exc:
        print(f"Scrape failed: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
