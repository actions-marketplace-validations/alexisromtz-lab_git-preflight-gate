#!/usr/bin/env bash
# banco_raiz_workflows.sh — banco must-fail de la RESOLUCION DEL UNIVERSO.
#
# HUELLA-BANCO-RAIZ-WORKFLOWS-20261106
#
# El banco de `--self-test` mide YAML en memoria y no puede ver este defecto:
# nace ANTES de leer un archivo. Medido el 2026-11-06 sobre `pallets/flask`,
# pasar la ruta que el README pide (`.github/workflows`) devolvia RC 31
# UNIVERSO_VACIO — `RAIZ: .../workflows/.github/workflows`, 0 archivos — y
# culpaba al arbol auditado de un error de argv.
#
# Cada caso exige DOS cosas:
#   (a) el RC esperado          -> condicion necesaria
#   (b) el aviso/causa impresos -> la que dice QUE se midio
# Un caso que devuelve el RC esperado por otro motivo NO discrimina y sale ROJO.
#
# Los casos 6 y 7 son CONTROLES NEGATIVOS: si la resolucion empezara a
# "adivinar cualquier directorio con YAMLs", se pondrian verdes midiendo el
# directorio equivocado y este banco enrojeceria.
#
# Uso: bash tests/banco_raiz_workflows.sh [ruta/al/sim/gate_workflows_ci.py]
set -uo pipefail

AQUI="$(cd "$(dirname "$0")" && pwd)"
GATE="${1:-$AQUI/../sim/gate_workflows_ci.py}"
[ -f "$GATE" ] || { echo "GATE AUSENTE: $GATE"; exit 2; }

PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "PYTHON3 AUSENTE: el instrumento declara python3"; exit 2; }

SUMIDERO="$AQUI/fixtures/sumidero"
[ -d "$SUMIDERO/.github/workflows" ] || { echo "FIXTURE AUSENTE: $SUMIDERO"; exit 2; }

T="$(mktemp -d "${TMPDIR:-/tmp}/banco_raiz.XXXXXX")" || exit 2
trap 'rm -rf "$T"' EXIT

# Arbol vacio: NO tiene .github/workflows, para que el RC 31 siga siendo alcanzable.
mkdir -p "$T/vacio"
# Control negativo: un directorio llamado `workflows` que NO cuelga de `.github`.
mkdir -p "$T/repo/workflows"
printf 'on: push\njobs:\n  b:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hola\n' \
  > "$T/repo/workflows/ci.yml"

FALLOS=0
TOTAL=0
corre() { # corre <nombre> <rc_esperado> <fragmento_esperado> <args...>
  local nombre="$1" rc_esp="$2" frag_esp="$3"; shift 3
  local salida rc
  salida="$("$PY" "$GATE" "$@" 2>&1)"; rc=$?
  TOTAL=$((TOTAL + 1))
  if [ "$rc" = "$rc_esp" ] && printf '%s' "$salida" | grep -qF -- "$frag_esp"; then
    printf 'OK    %-26s rc=%-3s %s\n' "$nombre" "$rc" "$frag_esp"
  else
    FALLOS=$((FALLOS + 1))
    printf 'ROJO  %-26s rc=%-3s (esperado %s / fragmento "%s")\n' \
      "$nombre" "$rc" "$rc_esp" "$frag_esp"
    printf '%s\n' "$salida" | sed 's/^/        | /' | tail -6
  fi
}

echo "GATE=$GATE"
echo ""

# 1 — control positivo: la raiz del repo resuelve sola y mide el YAML envenenado
corre R0_RAIZ_REPO 2 "UNIVERSO RESUELTO: $SUMIDERO/.github/workflows" "$SUMIDERO"
# 2 — EL DEFECTO: la ruta que el README pide ya es el directorio de workflows
corre R1_YA_ES_WORKFLOWS 2 "AVISO D5_RAIZ_YA_ES_WORKFLOWS" "$SUMIDERO/.github/workflows"
# 3 — misma ruta con barra final
corre R2_BARRA_FINAL 2 "AVISO D5_RAIZ_YA_ES_WORKFLOWS" "$SUMIDERO/.github/workflows/"
# 4 — la forma --root acepta lo mismo
corre R3_ROOT_EXPLICITO 2 "AVISO D5_RAIZ_YA_ES_WORKFLOWS" \
  --root "$SUMIDERO/.github/workflows"
# 5 — el RC 31 NO se retira: un arbol sin workflows sigue siendo universo vacio
corre R4_RC31_PRESERVADO 31 "UNIVERSO_VACIO" "$T/vacio"
# 6 — CONTROL: `<repo>/workflows` NO es el directorio de workflows
corre R5_CONTROL_BASENAME 31 "UNIVERSO_VACIO" "$T/repo/workflows"
# 7 — CONTROL: un `.github/workflowz` tampoco
corre R6_CONTROL_PARECIDO 31 "UNIVERSO_VACIO" "$SUMIDERO/.github/workflowz"

echo ""
echo "BANCO_RUTAS: $((TOTAL - FALLOS))/$TOTAL"
[ "$FALLOS" -eq 0 ] || exit 1
