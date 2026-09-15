"""Rapports PDF hebdomadaires Housat / Weekly PDF reports.

reportlab (pur Python) retenu : aucune dependance systeme (WeasyPrint exige pango/cairo,
incompatible avec les images slim non-root ; fpdf2 = tableaux trop pauvres).
Lectures SQL brutes (coherent avec worker.py), aucune IO reseau : le rapport consomme
les observations deja persistees — memes donnees que la carte web (image_bbox).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from housat.config import settings

logger = logging.getLogger("housat.reporting")


class ReportError(Exception):
    """Erreur metier rapport / report-domain error."""


class SiteNotFoundError(ReportError):
    """Chantier inconnu."""


class NoObservationsError(ReportError):
    """Aucune observation sur la semaine demandee."""


class DuplicateReportError(ReportError):
    """Rapport deja genere pour (site, semaine)."""


def week_bounds(any_day: date) -> tuple[date, date]:
    """(lundi, dimanche) de la semaine ISO contenant `any_day`."""
    monday = any_day - timedelta(days=any_day.weekday())
    return monday, monday + timedelta(days=6)


def last_iso_week(ref: date | None = None) -> tuple[date, date]:
    """Semaine ISO complete precedente (lundi..dimanche)."""
    monday, _ = week_bounds(ref or date.today())
    start = monday - timedelta(days=7)
    return start, start + timedelta(days=6)


def _latin1(s: str) -> str:
    """Helvetica standard = Latin-1 : remplace proprement ce qui depasse (tirets, etc.)."""
    return s.encode("latin-1", errors="replace").decode("latin-1")


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(row.get("payload") or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _fmt(v: Any, nd: int = 2) -> str:
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return "n/d"


def week_kpis(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """KPI semaine : dernier jalon, pivot, progression pv_sum (meme regle que /compare)."""
    compared = [r for r in rows if _payload(r).get("status") == "ok"]
    last = rows[-1] if rows else None
    pl = _payload(last) if last else {}
    pv_first = float(_payload(compared[0]).get("pv_sum") or 0.0) if compared else 0.0
    pv_last = float(_payload(compared[-1]).get("pv_sum") or 0.0) if compared else 0.0
    progression = round(100.0 * min(pv_last / max(pv_first, 1e-6), 1.3), 1) if pv_first > 0 else None
    confs = [float(r["confidence"]) for r in rows if r.get("confidence") is not None]
    return {
        "milestone": pl.get("milestone"),
        "milestone_label": pl.get("milestone_label") or "n/d",
        "pivot": bool(pl.get("pivot_confirme", False)),
        "progression": progression,
        "observations": len(rows),
        "confidence_avg": round(sum(confs) / len(confs), 2) if confs else None,
    }


def _footer(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#6b7280"))
    canvas.drawString(18 * mm, 10 * mm,
                      "Housat - Sentinel-2 (Copernicus) - genere localement, sans donnee externe")
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"page {doc.page}")
    canvas.restoreState()


def render_weekly_pdf(
    site: dict[str, Any],
    rows: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
    week_start: date,
    week_end: date,
) -> bytes:
    """Rend le PDF hebdomadaire : KPI, avant/apres, observations, alertes, limites."""
    styles = getSampleStyleSheet()
    h2 = ParagraphStyle("h2x", parent=styles["Heading2"], fontSize=13, spaceBefore=10,
                        spaceAfter=4, textColor=colors.HexColor("#1f2937"))
    body = ParagraphStyle("bodyx", parent=styles["BodyText"], fontSize=9, leading=12)
    small = ParagraphStyle("smallx", parent=body, fontSize=7.5, leading=9,
                           textColor=colors.HexColor("#555555"))

    iso = week_start.isocalendar()
    name = _latin1(str(site.get("name", "chantier")))
    title = f"Housat - Rapport hebdomadaire - {name} - {iso[0]}-S{iso[1]:02d}"

    story: list[Any] = []
    story.append(Paragraph(_latin1("Rapport hebdomadaire de suivi de chantier"),
                           styles["Title"]))
    story.append(Paragraph(_latin1(f"{name} - semaine ISO {iso[0]}-S{iso[1]:02d} "
                                   f"({week_start.isoformat()} au {week_end.isoformat()})"), body))
    story.append(Paragraph(_latin1(
        f"Genere le {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC - "
        f"{len(rows)} observation(s), {len(alerts)} alerte(s)"), small))
    story.append(Spacer(1, 4 * mm))

    kpi = week_kpis(rows)
    kpi_rows = [
        ("Dernier jalon", f"M{kpi['milestone']} - {kpi['milestone_label']}"
         if kpi["milestone"] is not None else "n/d"),
        ("Pivot confirme", "oui" if kpi["pivot"] else "non"),
        ("Progression de la semaine",
         f"{kpi['progression']} %" if kpi["progression"] is not None else "n/d"),
        ("Confiance moyenne",
         f"{kpi['confidence_avg']:.2f}" if kpi["confidence_avg"] is not None else "n/d"),
    ]
    kt = Table([[Paragraph(f"<b>{_latin1(a)}</b>", body), Paragraph(_latin1(str(b)), body)]
                for a, b in kpi_rows], colWidths=[55 * mm, 110 * mm])
    kt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef2f7")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9ced6")),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(kt)

    imgs = [r for r in rows if r.get("image_png")]
    if imgs:
        story.append(Paragraph(_latin1("Avant / apres (semaine)"), h2))
        cells = []
        for r, tag in ((imgs[0], "Debut"), (imgs[-1], "Fin")):
            cells.append([Image(io.BytesIO(bytes(r["image_png"])),
                                width=64 * mm, height=64 * mm),
                          Paragraph(_latin1(f"{tag} : {str(r.get('obs_date', ''))[:10]}"), small)])
        it = Table([cells], colWidths=[82 * mm, 82 * mm])
        it.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(it)

    story.append(Paragraph(_latin1("Observations de la semaine"), h2))
    header = ["Date", "Jalon", "Pivot", "Confiance", "PV cumulee", "Emprise"]
    data = [[Paragraph(f"<b>{h}</b>", body) for h in header]]
    for r in rows[:20]:
        p = _payload(r)
        label = str(p.get("milestone_label") or "baseline")
        ms = p.get("milestone", r.get("milestone"))
        data.append([
            str(r.get("obs_date", ""))[:10],
            _latin1(f"M{ms} {label}" if ms is not None else label),
            "oui" if (p.get("pivot_confirme") or r.get("pivot_confirme")) else "non",
            _fmt(r.get("confidence"), 2),
            _fmt(p.get("pv_sum"), 1),
            _fmt(p.get("emprise"), 4),
        ])
    t = Table(data, colWidths=[24 * mm, 60 * mm, 14 * mm, 20 * mm, 24 * mm, 22 * mm],
              repeatRows=1)
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e0e7f1")),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d1d5db")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f7f9")]),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(t)
    if len(rows) > 20:
        story.append(Paragraph(
            _latin1(f"... et {len(rows) - 20} observation(s) supplementaire(s)."), small))

    if alerts:
        story.append(Paragraph(_latin1("Alertes (jalons franchis)"), h2))
        for a in alerts:
            story.append(Paragraph(_latin1(
                f"- {a.get('message', '')} ({str(a.get('sent_at', ''))[:10]})"), body))

    story.append(Paragraph(_latin1("Methodologie et limites"), h2))
    story.append(Paragraph(_latin1(
        "Chaque date compare la scene Sentinel-2 super-resolue (2,5 m) a la scene d'ancrage t0 "
        "du chantier, sur les memes coordonnees geographiques que la carte web (image_bbox). "
        "La PV mesure le changement positif agrege des indices NDVI/NDBI/BSI ; la progression "
        "est le ratio de PV cumulee entre le debut et la fin de la semaine (plafond 130 %)."
    ), body))
    for limite in (
        "- Resolution utile 2,5 m : toiture et finition non distinguees (M3 = probable).",
        "- Comparaison a l'ancre t0 uniquement : hysterese precise, reactivite lente.",
        "- Scenes tres nuageuses marquees, jamais utilisees pour alerter.",
        "- Verification visuelle recommandee avant toute decision contractuelle.",
    ):
        story.append(Paragraph(_latin1(limite), small))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=title, author="Housat",
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


def ensure_report_table(engine: Engine) -> None:
    """Cree la table reports si absente (le worker tourne sans l'API en CI cron)."""
    lite = engine.dialect.name == "sqlite"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if lite else "SERIAL PRIMARY KEY"
    blob = "BLOB" if lite else "BYTEA"
    ddl = f"""
    CREATE TABLE IF NOT EXISTS reports (
        id {pk},
        site_id INTEGER NOT NULL REFERENCES sites(id),
        week_start VARCHAR(10) NOT NULL,
        week_end VARCHAR(10) NOT NULL,
        sha256 VARCHAR(64) NOT NULL,
        observations_count INTEGER NOT NULL DEFAULT 0,
        pdf {blob} NOT NULL,
        created_at VARCHAR(32) NOT NULL,
        CONSTRAINT uq_report_site_week UNIQUE (site_id, week_start)
    )
    """
    with engine.begin() as c:
        c.execute(text(ddl))


def _fetch_week(engine: Engine, site_id: int, start: date, end: date
                ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    after = end + timedelta(days=1)
    with engine.begin() as c:
        site = c.execute(text("SELECT id, name, created_at FROM sites WHERE id=:i"),
                         {"i": site_id}).mappings().first()
        if site is None:
            raise SiteNotFoundError(f"chantier {site_id} introuvable")
        rows = [dict(r) for r in c.execute(
            text("SELECT id, obs_date, milestone, pivot_confirme, confidence, payload, image_png "
                 "FROM observations WHERE site_id=:i AND obs_date >= :a AND obs_date < :b "
                 "ORDER BY obs_date, id"),
            {"i": site_id, "a": start.isoformat(), "b": after.isoformat()},
        ).mappings().all()]
        alerts = [dict(r) for r in c.execute(
            text("SELECT message, milestone, sent_at FROM alerts WHERE site_id=:i "
                 "AND sent_at >= :a AND sent_at < :b ORDER BY sent_at"),
            {"i": site_id, "a": start.isoformat(), "b": after.isoformat()},
        ).mappings().all()]
    return dict(site), rows, alerts


def build_weekly_report(engine: Engine, site_id: int, week_start: date) -> dict[str, Any]:
    """Construit + persiste le rapport hebdo. Leve NoObservations/DuplicateReportError."""
    if week_start.weekday() != 0:
        raise ReportError("week_start doit etre un lundi (debut de semaine ISO)")
    ensure_report_table(engine)
    week_end = week_start + timedelta(days=6)
    with engine.begin() as c:
        dup = c.execute(text("SELECT id FROM reports WHERE site_id=:i AND week_start=:w"),
                        {"i": site_id, "w": week_start.isoformat()}).first()
    if dup is not None:
        raise DuplicateReportError(week_start.isoformat())

    site, rows, alerts = _fetch_week(engine, site_id, week_start, week_end)
    if not rows:
        raise NoObservationsError(f"chantier {site_id} : aucune observation "
                                  f"semaine {week_start.isoformat()}")
    pdf = render_weekly_pdf(site, rows, alerts, week_start, week_end)
    digest = hashlib.sha256(pdf).hexdigest()
    # SQLite (sqlalchemy DATETIME) et PostgreSQL (TIMESTAMP) acceptent ce format, sans tz naive.
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
    try:
        with engine.begin() as c:
            c.execute(
                text("INSERT INTO reports (site_id, week_start, week_end, sha256,"
                     " observations_count, pdf, created_at)"
                     " VALUES (:i, :ws, :we, :h, :n, :p, :t)"),
                {"i": site_id, "ws": week_start.isoformat(), "we": week_end.isoformat(),
                 "h": digest, "n": len(rows), "p": pdf, "t": now})
    except IntegrityError as exc:  # concurrence : double generation simultanee
        raise DuplicateReportError(week_start.isoformat()) from exc
    logger.info("rapport site %s semaine %s : %d octets, %d observations",
                site_id, week_start.isoformat(), len(pdf), len(rows))
    return {"site_id": site_id, "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(), "sha256": digest,
            "observations_count": len(rows), "bytes": len(pdf)}


def weekly_reports(engine: Engine, week_start: date) -> list[dict[str, Any]]:
    """Rapports de la semaine pour tous les chantiers actifs (isolation par site)."""
    with engine.begin() as c:
        ids = [r[0] for r in
               c.execute(text("SELECT id FROM sites WHERE status='active' ORDER BY id"))]
    out: list[dict[str, Any]] = []
    for sid in ids:
        try:
            out.append(build_weekly_report(engine, sid, week_start))
        except DuplicateReportError:
            logger.info("site %s : rapport %s deja present, ignore", sid, week_start.isoformat())
        except ReportError as exc:
            logger.warning("site %s : rapport %s ignore (%s)", sid, week_start.isoformat(), exc)
        except Exception:  # noqa: BLE001 — isolation par site, tracee
            logger.exception("site %s : echec rapport %s", sid, week_start.isoformat())
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser(description="Housat — rapports PDF hebdomadaires")
    p.add_argument("--weekly", action="store_true",
                   help="tous les chantiers actifs, semaine ISO ecoulee (cron lundi)")
    p.add_argument("--week", help="lundi ISO YYYY-MM-DD (defaut : semaine ecoulee)")
    p.add_argument("--site", type=int, metavar="SITE_ID", help="limiter a un chantier")
    args = p.parse_args()
    try:
        monday = date.fromisoformat(args.week) if args.week else last_iso_week()[0]
    except ValueError as exc:
        p.error(f"--week invalide : {exc}")
        return
    if monday.weekday() != 0:
        p.error("--week doit tomber un lundi (debut de semaine ISO)")
        return
    engine = create_engine(settings.database_url)
    results = ([build_weekly_report(engine, args.site, monday)] if args.site
               else weekly_reports(engine, monday))
    logger.info("rapports generes : %d (semaine %s)", len(results), monday.isoformat())


if __name__ == "__main__":
    main()
