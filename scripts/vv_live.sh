#!/usr/bin/env bash
# Housat — Verification & Validation live (bash) / harnais V&V live.
#
# Equivalent bash de scripts/vv_live.ps1 (le .ps1 n'est pas modifie) : meme runbook
# E2E documente dans docs/verification.md, memes 28 assertions, memes criteres.
# Le harnais est READ-ONLY vis-a-vis du depot ; il cree son propre chantier via l'API.
#
# Usage :
#   bash scripts/vv_live.sh
#   bash scripts/vv_live.sh --api http://localhost:8000 --timeout 900
#   bash scripts/vv_live.sh --site-name "Mon chantier V&V"   # reutilise un nom fixe
#
# Emprise de test : lue dans .env (VVSITE_*), sinon les defauts du formulaire web.
# Aucune localisation n'est ecrite en dur dans le depot (regle 7 : pas de ciblage visible).
# Nom du chantier de test : horodate par defaut, pour que le harnais soit REJOUABLE (cf plus bas).
#
# --- Assertions et codes HTTP attendus (les memes que le .ps1) ------------------
#   A6.0  GET  /healthz                          -> 200, JSON status=ok
#   A6.1  GET  /sites/999999                     -> 404, Content-Type application/problem+json
#   A6.2  POST /sites                            -> 201, polygon_geojson contient "Polygon"
#   A6.3  POST /sites  (bbox inversee)           -> 422, application/problem+json
#   A6.4  POST /sites  (bbox > ~2 km2)           -> 422
#   A1.0  POST /sites/{id}/backfill              -> 202
#   A6.5  POST /sites/{id}/backfill  (2e appel)  -> 409, application/problem+json
#   A1.1  GET  /sites/{id}/progress              -> status final "done"
#   A1.2  GET  /sites/{id}/observations          -> au moins 2 scenes
#   A2.1  GET  /sites/{id}/frames                -> anchor == true
#   A5.1  (observations)                         -> pv_sum renseigne pour chaque observation
#   A9.1  (observations)                         -> image_bbox presente pour chaque image
#   A9.2  GET  {image_url}                       -> 200, PNG (89 50), Cache-Control immutable
#   A8.1  GET  /sites/{id}/compare?from&to       -> 200, progression <= 130 %
#   A8.2  GET  /sites/{id}/compare  (meme obs)   -> 422
#   A8.3  GET  /sites/{id}/compare  (obs inconnu)-> 404
#   A4.1  (observations)                         -> jalons NON REGRESSIFS (M_t >= M_t-1)
#   A3.1  GET  /sites/{id}/alerts                -> jalons monotones
#   A7.1  (.env)                                 -> SMTP_HOST vide (aucun canal externe)
#   A7.2  (.env)                                 -> NTFY_TOPIC (canal de publication) signale
#   A10.1 POST /sites/{id}/reports/2020-01-06    -> 422, application/problem+json (semaine vide)
#   A10.2 POST /sites/{id}/reports/<lundi courant> -> 422 (semaine en cours)
#   A10.3 POST /sites/{id}/reports/2020-01-08    -> 422 (date non-lundi)
#   A10.4 POST /sites/{id}/reports/<semaine close> -> 201
#   A10.5 (reponse)                              -> sha256 = 64 hex
#   A10.6 GET  .../reports/{week}/pdf            -> 200, magic "%PDF", > 2 Ko
#   A10.7 (en-tete ETag)                         -> ETag == sha256 octets == sha256 DB
#   A10.8 POST /sites/{id}/reports/<meme semaine>-> 409, application/problem+json
#   A10.9 GET  /sites/{id}/reports               -> au moins 1 rapport liste
#
# Sortie : une ligne PASS/FAIL par assertion, puis un resume. Code de sortie 1 si un FAIL.
# ------------------------------------------------------------------------------

set -uo pipefail

API="http://localhost:8000"
TIMEOUT=900
PYTHON="${PYTHON:-python}"
SITE_NAME_OPT=""

while [ $# -gt 0 ]; do
  case "$1" in
    --api) API="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --site-name) SITE_NAME_OPT="$2"; shift 2 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "argument inconnu: $1" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

RESULT_FILE="$TMP/results"
: > "$RESULT_FILE"
FAILS=0

# --- Parcelle de test depuis .env (meme logique que le .ps1) --------------------
# REJOUABILITE : l'API refuse (409) un chantier de MEME NOM + MEME EMPRISE (garde anti-doublon de
# `POST /sites`, ajoutee apres cinq « Ma maison » vides). Le `.ps1` ne suffixe pas le nom : sa
# DEUXIEME execution echoue donc en 409, laisse `$siteId` vide et enchainait une cascade de 404 —
# et quand bien meme le site serait reutilise, le bloc rapports A10.4 retomberait sur le 409
# d'idempotence du rapport au lieu de tester la GENERATION. On horodate donc le nom du chantier de
# test (sauf `--site-name` explicite), ce qui rend le harnais rejouable et garde A10 discriminant.
env_get() {  # env_get CLE [defaut]
  local v=""
  if [ -f "$ROOT/.env" ]; then
    v="$(sed -n "s/^$1=[[:space:]]*//p" "$ROOT/.env" | tr -d '\r' | head -1)"
  fi
  printf '%s' "${v:-${2:-}}"
}
SITE_NAME="$(env_get VVSITE_NAME 'VV Live Parcelle')"
if [ -n "$SITE_NAME_OPT" ]; then
  SITE_NAME="$SITE_NAME_OPT"
else
  SITE_NAME="$SITE_NAME $(date +%Y%m%d-%H%M%S)"
fi
MIN_LON="$(env_get VVSITE_MIN_LON '9.70')"
MIN_LAT="$(env_get VVSITE_MIN_LAT '4.04')"
MAX_LON="$(env_get VVSITE_MAX_LON '9.71')"
MAX_LAT="$(env_get VVSITE_MAX_LAT '4.05')"

chk() {  # chk ID LIBELLE 0|1 DETAIL
  local id="$1" label="$2" ok="$3" detail="${4:-}"
  if [ "$ok" = "1" ]; then
    printf '[PASS] %-5s %s%s\n' "$id" "$label" "${detail:+ :: $detail}"
    echo "PASS|$id|$label" >> "$RESULT_FILE"
  else
    printf '[FAIL] %-5s %s%s\n' "$id" "$label" "${detail:+ :: $detail}"
    echo "FAIL|$id|$label" >> "$RESULT_FILE"
    FAILS=$((FAILS + 1))
  fi
}

# --- Client HTTP minimal : corps dans $B, en-tetes dans $H, code dans $CODE -----
B="$TMP/body.json"; H="$TMP/head.txt"
req() {  # req METHODE CHEMIN [CORPS_JSON]
  local method="$1" path="$2" body="${3:-}"
  local args=(-sS -o "$B" -D "$H" -w '%{http_code}' -X "$method" -H 'Accept: application/json')
  if [ -n "$body" ]; then
    args+=(-H 'Content-Type: application/json; charset=utf-8' --data-binary "$body")
  fi
  CODE="$(curl "${args[@]}" "$API$path" 2>/dev/null || echo 000)"
  CTYPE="$(sed -n 's/^[Cc]ontent-[Tt]ype:[[:space:]]*//p' "$H" | tr -d '\r' | head -1)"
  CACHE="$(sed -n 's/^[Cc]ache-[Cc]ontrol:[[:space:]]*//p' "$H" | tr -d '\r' | head -1)"
  ETAG="$(sed -n 's/^[Ee][Tt][Aa][Gg]:[[:space:]]*//p' "$H" | tr -d '\r"' | head -1)"
  BYTES="$(wc -c < "$B" | tr -d ' ')"
}

jsonfield() {  # jsonfield FICHIER EXPR_DOTTEE   (ex. delta.progression)
  "$PYTHON" -c '
import json,sys
d=json.load(open(sys.argv[1],encoding="utf-8"))
for p in sys.argv[2].split("."):
    if p=="" : continue
    d=d[int(p)] if p.lstrip("-").isdigit() else d[p]
print(d if d is not None else "")' "$1" "$2" 2>/dev/null
}

jsoncount() {  # jsoncount FICHIER PREDICAT   predicats : *.total|*.pv_sum|*.img_bbox|*.pivot|*.monotone
  "$PYTHON" -c '
import json,sys
d=json.load(open(sys.argv[1],encoding="utf-8"))
items=d if isinstance(d,list) else []
k=sys.argv[2]
if k=="total":      print(len(items))
elif k=="pv_sum":   print(sum(1 for o in items if o.get("pv_sum") is not None))
elif k=="img":      print(sum(1 for o in items if o.get("image_url")))
elif k=="img_bbox": print(sum(1 for o in items if o.get("image_url") and o.get("image_bbox") is not None))
elif k=="pivot":    print(sum(1 for o in items if o.get("milestone") in ("M2","M3","M4") and o.get("pivot_confirme") is not True))
elif k=="monotone":
    idx={"M0":0,"M1":1,"M2":2,"M3":3,"M4":4}; prev=-1; ok=True
    for a in items:
        v=idx.get(a.get("milestone"))
        if v is None: continue
        if v<prev: ok=False; break
        prev=v
    print("true" if ok else "false")
elif k=="obs_monotone":
    # Jalons des OBSERVATIONS tries par date, non regressifs. Garanti cote code par
    # `milestones.hold_milestone` (le jalon ne redescend jamais sous celui deja atteint).
    rows=sorted((o for o in items if o.get("milestone") is not None),
                key=lambda o: str(o.get("obs_date") or ""))
    seq=[int(o["milestone"]) for o in rows]
    print("true" if all(b>=a for a,b in zip(seq,seq[1:])) else "false")
elif k=="obs_seq":
    rows=sorted((o for o in items if o.get("milestone") is not None),
                key=lambda o: str(o.get("obs_date") or ""))
    print(",".join("M" + str(int(o["milestone"])) for o in rows))
elif k=="week_closed":
    import datetime
    today=datetime.date.today(); ongoing=today-datetime.timedelta(days=today.weekday())
    weeks=set()
    for o in items:
        if not o.get("obs_date"): continue
        dt=datetime.date.fromisoformat(str(o["obs_date"])[:10])
        weeks.add(dt-datetime.timedelta(days=dt.weekday()))
    closed=sorted((w for w in weeks if w<ongoing),reverse=True)
    print(closed[0].isoformat() if closed else "")
elif k=="png_first": print(",".join(str(i) for i in items[:2]))
' "$1" "$2" 2>/dev/null
}

echo
echo "=== Housat — Verification & Validation live (bash) ==="
echo "API: $API"
echo

# ------------------------------------------------------------------ A6 / healthz
req GET /healthz
chk A6.0 "healthz repond ok (200 + status=ok)" \
  "$([ "$CODE" = "200" ] && [ "$(jsonfield "$B" status)" = "ok" ] && echo 1 || echo 0)" \
  "status=$CODE"

req GET /sites/999999
chk A6.1 "erreur 404 conforme RFC 7807" \
  "$([ "$CODE" = "404" ] && case "$CTYPE" in application/problem+json*) echo 1;; *) echo 0;; esac)" \
  "status=$CODE ct=$CTYPE"

# ------------------------------------------------------------------ creation chantier
req POST /sites "$(printf '{"name":"%s","owner_email":"vv@example.com","min_lon":%s,"min_lat":%s,"max_lon":%s,"max_lat":%s}' \
  "$SITE_NAME" "$MIN_LON" "$MIN_LAT" "$MAX_LON" "$MAX_LAT")"
SID="$(jsonfield "$B" id)"
POLY_OK="$(jsonfield "$B" polygon_geojson)"
chk A6.2 "POST /sites -> 201 + polygon GeoJSON" \
  "$([ "$CODE" = "201" ] && case "$POLY_OK" in *Polygon*) echo 1;; *) echo 0;; esac)" \
  "status=$CODE id=$SID"

# ABANDON EXPLICITE : sans identifiant de chantier, les assertions A1/A2/A5/A8/A9/A10 ne sont pas
# « vertes », elles sont HORS DE PORTEE. On le dit et on sort — un enchainement de 404 ne doit
# jamais etre presente comme un resultat.
if [ -z "$SID" ]; then
  echo
  echo "[ABANDON] POST /sites a repondu $CODE sans identifiant de chantier."
  echo "          A1, A2, A5, A8, A9 et A10 sont HORS DE PORTEE => NON CONCLUANT, jamais vert."
  echo "          Cause probable : chantier de MEME NOM + MEME EMPRISE deja existant (409)."
  echo "          Correctif : relancer sans --site-name (le nom est horodate) ou changer --site-name."
  TOTAL="$(wc -l < "$RESULT_FILE" | tr -d ' ')"
  echo
  echo "RESULTAT : $((TOTAL - FAILS))/$TOTAL verifications PASS, $FAILS FAIL (abandon, 6 blocs non atteints)"
  exit 1
fi

req POST /sites "$(printf '{"name":"bbox KO","owner_email":"vv@example.com","min_lon":%s,"min_lat":%s,"max_lon":%s,"max_lat":%s}' \
  "$MIN_LON" "$MIN_LAT" "$("$PYTHON" -c "print(${MIN_LON}-0.01)")" "$MAX_LAT")"
chk A6.3 "bbox invalide -> 422 RFC 7807" \
  "$([ "$CODE" = "422" ] && case "$CTYPE" in application/problem+json*) echo 1;; *) echo 0;; esac)" \
  "status=$CODE ct=$CTYPE"

req POST /sites "$(printf '{"name":"bbox grande","owner_email":"vv@example.com","min_lon":%s,"min_lat":%s,"max_lon":%s,"max_lat":%s}' \
  "$MIN_LON" "$MIN_LAT" "$("$PYTHON" -c "print(${MIN_LON}+0.2)")" "$("$PYTHON" -c "print(${MIN_LAT}+0.2)")")"
chk A6.4 "bbox > ~2 km2 -> 422 (anti-DoS)" "$([ "$CODE" = "422" ] && echo 1 || echo 0)" "status=$CODE"

# ------------------------------------------------------------------ A1 backfill
echo
echo "> Backfill archive Sentinel-2 (reseau STAC requis, jusqu'a ${TIMEOUT}s)..."
req POST "/sites/$SID/backfill"
chk A1.0 "POST /backfill -> 202 accepted" "$([ "$CODE" = "202" ] && echo 1 || echo 0)" "status=$CODE"

req POST "/sites/$SID/backfill"
chk A6.5 "second backfill concurrent -> 409" \
  "$([ "$CODE" = "409" ] && case "$CTYPE" in application/problem+json*) echo 1;; *) echo 0;; esac)" \
  "status=$CODE ct=$CTYPE"

BFS=""; DEADLINE=$(( $(date +%s) + TIMEOUT ))
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  req GET "/sites/$SID/progress"
  cp "$B" "$TMP/progress.json" 2>/dev/null || true
  BFS="$(jsonfield "$B" backfill_status)"
  STATE="$BFS|$(jsonfield "$B" observations)|$(jsonfield "$B" milestone)"
  if [ "$STATE" != "${LAST_STATE:-}" ]; then
    echo "   ...status=$BFS observations=$(jsonfield "$B" observations) milestone=$(jsonfield "$B" milestone)"
    LAST_STATE="$STATE"
  fi
  case "$BFS" in done|error|idle) break ;; esac
  sleep 10
done
BFE="$(jsonfield "$B" backfill_error)"

req GET "/sites/$SID/observations"
cp "$B" "$TMP/obs.json"
OBS_TOTAL="$(jsoncount "$TMP/obs.json" total)"
chk A1.1 "backfill termine (status done)" "$([ "$BFS" = "done" ] && echo 1 || echo 0)" \
  "status=$BFS error=$BFE"
chk A1.2 ">= 2 scenes ingerees (critere A1)" "$([ "${OBS_TOTAL:-0}" -ge 2 ] && echo 1 || echo 0)" \
  "observations=$OBS_TOTAL"

# ------------------------------------------------------------------ A2 ancre
req GET "/sites/$SID/frames"
chk A2.1 "ancre t0 persistee (frame_store.anchor)" \
  "$([ "$(jsonfield "$B" anchor)" = "True" ] && echo 1 || echo 0)" \
  "anchor=$(jsonfield "$B" anchor) prev=$(jsonfield "$B" prev)"

# ------------------------------------------------------------------ A5 tracabilite
OBS_PV="$(jsoncount "$TMP/obs.json" pv_sum)"
chk A5.1 "pv_sum consigne par observation" \
  "$([ "${OBS_PV:-0}" = "${OBS_TOTAL:-0}" ] && [ "${OBS_TOTAL:-0}" -gt 0 ] && echo 1 || echo 0)" \
  "avec pv_sum=$OBS_PV/$OBS_TOTAL"

# ------------------------------------------------------------------ A9 image_bbox
IMG_N="$(jsoncount "$TMP/obs.json" img)"
IMG_B="$(jsoncount "$TMP/obs.json" img_bbox)"
chk A9.1 "image_bbox persistee pour chaque image" \
  "$([ "${IMG_N:-0}" -gt 0 ] && [ "$IMG_N" = "$IMG_B" ] && echo 1 || echo 0)" \
  "images=$IMG_N bbox=$IMG_B"

if [ "${IMG_N:-0}" -gt 0 ]; then
  IMG_URL="$("$PYTHON" -c 'import json,sys;d=json.load(open(sys.argv[1],encoding="utf-8"));print(next((o["image_url"] for o in d if o.get("image_url")),""))' "$TMP/obs.json")"
  req GET "$IMG_URL"
  MAGIC="$(head -c2 "$B" | od -An -tx1 | tr -d ' \n')"
  chk A9.2 "GET {image_url} -> PNG valide + cache immutable" \
    "$([ "$CODE" = "200" ] && [ "$MAGIC" = "8950" ] && case "$CACHE" in *immutable*) echo 1;; *) echo 0;; esac)" \
    "status=$CODE bytes=$BYTES magic=$MAGIC ct=$CTYPE cache=$CACHE"
fi

# ------------------------------------------------------------------ A8 compare + A4 pivot
FIRST_ID="$("$PYTHON" -c 'import json,sys;d=sorted(json.load(open(sys.argv[1],encoding="utf-8")),key=lambda o:o.get("obs_date") or "");print(d[0]["id"] if d else "")' "$TMP/obs.json")"
LAST_ID="$("$PYTHON" -c 'import json,sys;d=sorted(json.load(open(sys.argv[1],encoding="utf-8")),key=lambda o:o.get("obs_date") or "");print(d[-1]["id"] if d else "")' "$TMP/obs.json")"

if [ "${OBS_TOTAL:-0}" -ge 2 ]; then
  req GET "/sites/$SID/compare?from=$FIRST_ID&to=$LAST_ID"
  PG="$(jsonfield "$B" delta.progression)"
  chk A8.1 "/compare avant/apres -> 200 + progression plafonnee 130%" \
    "$([ "$CODE" = "200" ] && [ -n "$PG" ] && "$PYTHON" -c "import sys;sys.exit(0 if float('$PG')<=130.0 else 1)" && echo 1 || echo 0)" \
    "status=$CODE progression=$PG%"

  req GET "/sites/$SID/compare?from=$FIRST_ID&to=$FIRST_ID"
  chk A8.2 "comparaison meme observation -> 422" "$([ "$CODE" = "422" ] && echo 1 || echo 0)" "status=$CODE"

  req GET "/sites/$SID/compare?from=$FIRST_ID&to=999999"
  chk A8.3 "observation hors chantier -> 404" "$([ "$CODE" = "404" ] && echo 1 || echo 0)" "status=$CODE"
fi

OBS_MONO="$(jsoncount "$TMP/obs.json" obs_monotone)"
OBS_SEQ="$(jsoncount "$TMP/obs.json" obs_seq)"
chk A4.1 "jalons d'observation non regressifs (M_t >= M_t-1)" \
  "$([ "$OBS_MONO" = "true" ] && echo 1 || echo 0)" \
  "suite=$OBS_SEQ"

# ------------------------------------------------------------------ A3 alertes monotones
req GET "/sites/$SID/alerts"
cp "$B" "$TMP/alerts.json"
MONO="$(jsoncount "$TMP/alerts.json" monotone)"
chk A3.1 "alertes de jalon monotones (M_t >= M_t-1)" "$([ "$MONO" = "true" ] && echo 1 || echo 0)" \
  "alertes=$(jsoncount "$TMP/alerts.json" total)"

# ------------------------------------------------------------------ A7 canaux externes
SMTP_SET=0; [ -n "$(env_get SMTP_HOST)" ] && SMTP_SET=1
NTFY_SET=0; [ -n "$(env_get NTFY_TOPIC)" ] && NTFY_SET=1
chk A7.1 "aucun canal d'alerte externe en mode local" "$([ "$SMTP_SET" = "0" ] && echo 1 || echo 0)" \
  "SMTP_HOST defini=$([ "$SMTP_SET" = "1" ] && echo true || echo false)"
chk A7.2 "canal de publication NTFY signale (controle ajoute au .ps1)" 1 \
  "NTFY_TOPIC defini=$([ "$NTFY_SET" = "1" ] && echo true || echo false)"

# ------------------------------------------------------------------ A10 rapports
echo
ONGOING_MONDAY="$("$PYTHON" -c 'import datetime;t=datetime.date.today();print((t-datetime.timedelta(days=t.weekday())).isoformat())')"

req POST "/sites/$SID/reports/2020-01-06"
chk A10.1 "semaine sans observation -> 422 RFC 7807" \
  "$([ "$CODE" = "422" ] && case "$CTYPE" in application/problem+json*) echo 1;; *) echo 0;; esac)" \
  "status=$CODE ct=$CTYPE"

req POST "/sites/$SID/reports/$ONGOING_MONDAY"
chk A10.2 "semaine en cours -> 422" "$([ "$CODE" = "422" ] && echo 1 || echo 0)" "status=$CODE"

req POST "/sites/$SID/reports/2020-01-08"
chk A10.3 "semaine non-lundi -> 422" "$([ "$CODE" = "422" ] && echo 1 || echo 0)" "status=$CODE"

WEEK="$(jsoncount "$TMP/obs.json" week_closed)"
if [ -z "$WEEK" ]; then
  chk A10.4 "semaine cloturee avec observations disponible" 0 "aucune observation dans une semaine cloturee"
else
  echo "> Rapport PDF semaine $WEEK ..."
  req POST "/sites/$SID/reports/$WEEK"
  chk A10.4 "POST /reports/{week} -> 201" "$([ "$CODE" = "201" ] && echo 1 || echo 0)" "status=$CODE"
  SHA="$(jsonfield "$B" sha256)"
  chk A10.5 "empreinte SHA-256 persistee (64 hex)" \
    "$(printf '%s' "$SHA" | grep -Eq '^[0-9a-f]{64}$' && echo 1 || echo 0)" \
    "sha256=$(printf '%s' "$SHA" | cut -c1-16)..."

  req GET "/sites/$SID/reports/$WEEK/pdf"
  MAGIC4="$(head -c4 "$B")"
  chk A10.6 "GET .../pdf -> %PDF valide (> 2 Ko)" \
    "$([ "$CODE" = "200" ] && [ "$MAGIC4" = "%PDF" ] && [ "${BYTES:-0}" -gt 2048 ] && echo 1 || echo 0)" \
    "status=$CODE magic=$MAGIC4 bytes=$BYTES"

  ACTUAL="$(sha256sum "$B" | cut -d' ' -f1)"
  chk A10.7 "ETag == sha256 octets telecharges == empreinte DB" \
    "$([ "$ACTUAL" = "$SHA" ] && [ "$ETAG" = "$SHA" ] && echo 1 || echo 0)" \
    "etag=$(printf '%s' "$ETAG" | cut -c1-16)... recalcul=$(printf '%s' "$ACTUAL" | cut -c1-16)..."

  req POST "/sites/$SID/reports/$WEEK"
  chk A10.8 "regeneration meme semaine -> 409 (idempotence)" \
    "$([ "$CODE" = "409" ] && case "$CTYPE" in application/problem+json*) echo 1;; *) echo 0;; esac)" \
    "status=$CODE ct=$CTYPE"

  req GET "/sites/$SID/reports"
  cp "$B" "$TMP/reports.json"
  chk A10.9 "rapport liste via GET /reports" \
    "$([ "$(jsoncount "$TMP/reports.json" total)" -ge 1 ] && echo 1 || echo 0)" \
    "rapports=$(jsoncount "$TMP/reports.json" total)"
fi

# ------------------------------------------------------------------ resume
TOTAL="$(wc -l < "$RESULT_FILE" | tr -d ' ')"
PASSED=$((TOTAL - FAILS))
echo
echo "=== Resume V&V ==="
awk -F'|' '{printf "%-4s %-6s %s\n", $2, $1, $3}' "$RESULT_FILE"
echo
echo "RESULTAT : $PASSED/$TOTAL verifications PASS, $FAILS FAIL"
echo "Chantier de test : $API/sites/$SID  (web: http://localhost:8080)"
echo
[ "$FAILS" -eq 0 ] || exit 1
exit 0
