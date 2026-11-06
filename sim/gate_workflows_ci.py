#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gate_workflows_ci.py
====================
Verificador estructural DETERMINISTA de la topologia de autoridad en pipelines
de CI.  Analiza el AST de los YAML de .github/workflows/ y aplica CINCO
invariantes contables.  No lee red, no escribe archivos, no usa aleatoriedad,
no consulta el reloj.

INVARIANTE CENTRAL (forma corregida):

    Autoridad(Job) > 0   =>   Ejecucion(repo U deps)(Job) = vacio

No se afirma "cero ejecucion": la autoridad tiene que ejecutar ALGO (descargar
un artefacto, correr el cliente nativo).  Lo que se prohibe es que ese algo
provenga del repositorio o de sus dependencias.

UNIVERSO DECLARADO: .github/workflows/*.yml + .github/workflows/*.yaml
MOTOR: python3 stdlib + PyYAML (safe_load) -- sin red, sin escritura, sin azar
REGLA DE VEREDICTO: RC 0 (PASA) | RC > 0 (FALLO CERRADO, causa tipada)

TABLA DE CAUSAS (RC):
  1  AUTORIDAD_CONTAMINADA  Job con permisos de ESCRITURA que ejecuta codigo
                            de terceros mediante `run:` (gestor de paquetes,
                            interprete, descarga o mutacion de VCS).  Un
                            cliente nativo de publicacion (ALLOWLIST_SINK)
                            no cuenta como ejecucion: publica artefactos.
  2  SUMIDERO_IMPUDO         Job sumidero (`id-token: write`) que hace
                            `actions/checkout`, invoca herramientas dinamicas
                            (npx/pipx) o no consume exclusivamente artefactos
                            descargados (`actions/download-artifact`).
  3  DISPARADOR_ENVENENADO   Trigger `pull_request_target` / `workflow_run`
                            con checkout explicito del commit del PR / head
                            dentro de un contexto con secretos o autoridad.
  4  SECRETO_EXPUESTO        `${{ secrets.* }}` interpolado dentro de un bloque
                            `run:` (el valor entra al argv y al log), o en
                            `env:` / `with:` de un job con disparador
                            privilegiado que alcanza contenido no confiable.
                            Un secreto pasado como INPUT de una accion no es
                            exposicion: es el mecanismo documentado.  Ver el
                            dominio declarado de RC 4 mas abajo.
  5  REF_MUTABLE             `uses:` con tag flotante (@v*, @main, @master) en
                            vez de SHA-1 de 40 caracteres.
 31  UNIVERSO_VACIO          No hay archivos de workflow que medir.
 32  YAML_INVALIDO           El archivo no parsea.

AVISO DECLARADO (no es RC, no cambia el veredicto):
  D5_RAIZ_YA_ES_WORKFLOWS    El argumento ya apunta a `.github/workflows`, asi
                            que se mide ahi y NO se anexa la ruta otra vez.
                            Sin este aviso, el error de argv mas probable
                            (pasar el directorio de workflows como raiz)
                            devolvia RC 31 UNIVERSO_VACIO culpando al arbol
                            auditado de estar vacio, cuando el defecto estaba
                            en el argumento. No amplia el dominio: cualquier
                            otro directorio llamado `workflows` sigue
                            resolviendo a `<raiz>/.github/workflows`.

RESIDUO DECLARADO (PLANO CIEGO FUERA DEL ARCHIVO):
  1. Permisos por defecto del GITHUB_TOKEN a nivel de repositorio/organizacion.
  2. Politicas de confianza OIDC / Trusted Publishing en el registro destino.
  3. Ejecucion de codigo nativo no aislado en runtime (modificacion de deps).
  4. Workflows reutilizables (`workflow_call`) y acciones compuestas alojadas
     en repositorios ajenos.
  => El instrumento certifica la AUSENCIA de la forma `autoridad contaminada`
     en el archivo que PUEDE leer.  NO certifica el plano que no ve.

DOMINIO DECLARADO DE RC 1 (ancho, no umbral):
  `actions/checkout` por si solo NO dispara RC 1.  RC 1 mide EJECUCION
  (`run:`), no presencia del arbol.  La presencia del arbol en un job con
  autoridad de publicacion es RC 2 (SUMIDERO_IMPUDO).  La particion es
  declarada, no silenciosa.
  ALLOWLIST_SINK: el cliente nativo de publicacion (`npm publish ...`) queda
  fuera del computo de ejecucion de terceros, porque el sumidero canonico
  TIENE que ejecutarlo.  Es una restriccion de DOMINIO declarada, no una
  bajada de umbral: el conjunto admitido es exactamente el cliente nativo.

DOMINIO DECLARADO DE RC 4 (secreto + sumidero):
  El defecto es la EXPOSICION, no la PRESENCIA del secreto.  Hay dos sumideros
  y solo dos:
    SINK_SHELL    -> `${{ secrets.* }}` interpolado dentro de `run:`: el valor
                     entra al argv del proceso y al log del step, y habilita
                     inyeccion de shell.  Siempre RC 4.
    SINK_CONTEXTO -> `${{ secrets.* }}` en `env:` (global o de job) o en `with:`
                     de un paso, EN UN JOB cuyo disparador es privilegiado
                     (`pull_request_target` / `workflow_run`) y que hace checkout
                     de una ref no confiable.  RC 4.
  Un secreto en `env:` de un job ordinario, o como INPUT (`with:`) de una accion
  SHA-pinada, NO es exposicion: es la forma documentada de dar una credencial.
  Se publica como OBSERVACION (se vio y no es sumidero), no como hallazgo: el
  lector tiene que poder distinguir "no lo vi" de "lo vi y no lo es".
  Medido 2026-11-06 sobre 47 workflows de 6 repos maduros: 23 jobs con secreto,
  23/23 en `with:`, 0/23 en `run:`.  Con la regla anterior el 100 % de la clase
  era falso positivo (HUELLA-RC4-SUMIDERO-20261106).
"""

import argparse
import io
import json
import os
import re
import sys

try:
    import yaml
except Exception as _e:  # pragma: no cover
    sys.stderr.write("MOTOR INCOMPLETO: PyYAML ausente (%s). Fail-closed.\n" % (_e,))
    raise SystemExit(30)

MOTOR = "python3 stdlib + PyYAML %s (sin red, sin escritura, sin azar)" % (
    getattr(yaml, "__version__", "?"),
)
UNIVERSO = ".github/workflows/*.yml + .github/workflows/*.yaml del arbol objetivo"
INVARIANTE = "Autoridad(Job) > 0  =>  Ejecucion(repo U deps)(Job) = vacio"
REGLA = "RC 0 (PASA) | RC > 0 (FALLO CERRADO, causa tipada)"

RESIDUO = (
    "Permisos por defecto del GITHUB_TOKEN a nivel de repositorio u organizacion.",
    "Politicas de confianza OIDC / Trusted Publishing en el registro destino (npm, PyPI, AWS).",
    "Modificacion de dependencias en runtime si se ejecuta codigo nativo no aislado.",
    "Workflows reutilizables (workflow_call) y acciones compuestas alojadas en repositorios ajenos.",
)

CAUSAS = {
    1: "AUTORIDAD_CONTAMINADA",
    2: "SUMIDERO_IMPUDO",
    3: "DISPARADOR_ENVENENADO",
    4: "SECRETO_EXPUESTO",
    5: "REF_MUTABLE",
    31: "UNIVERSO_VACIO",
    32: "YAML_INVALIDO",
}

# HUELLA-RC31-RAIZ-YA-ES-WORKFLOWS-20261106: el posicional y `--root` nombran la
# RAIZ del arbol, no el directorio de workflows. Medido 06-Nov-2026 sobre
# `pallets/flask`: `ci-authority-gate <repo>/.github/workflows` devolvia
# RC 31 UNIVERSO_VACIO con `RAIZ: …/workflows/.github/workflows` y 0 archivos
# medidos. El instrumento se cerraba bien y culpaba al sujeto equivocado.
AVISO_D5 = "D5_RAIZ_YA_ES_WORKFLOWS"

# ----------------------------------------------------------------------------
# Patrones.  Todos son LEXICOS y se aplican linea por linea (dominio declarado:
# una linea de `run:` es la unidad de juicio).
# ----------------------------------------------------------------------------
PAT_EXEC = re.compile(
    r"\b(npm|pnpm|yarn|npx|pipx|pip3|pip|cargo|rustc|go|gem|bundle|composer"
    r"|make|cmake|node|deno|bun|python3|python|ruby|php|java|mvn|gradle|dotnet)\b"
)
PAT_FETCH = re.compile(r"\b(curl|wget)\b")
PAT_GITMUT = re.compile(r"\bgit\s+(push|commit|tag|remote|config)\b")
PAT_GH = re.compile(r"(^|[\s;&|(])gh\s+[a-z]")
# HUELLA-SINK-NATIVO-20261106: el allowlist cubria solo `npm publish`, asi que
# todo otro cliente nativo de publicacion (`gh release create`, `twine upload`,
# `docker push`, `cargo|poetry|uv publish`) contaba como "ejecuta codigo de
# terceros" y disparaba RC 1 en el patron de release canonico y endurecido.
# Medido en `pallets/flask`: `.github/workflows/publish.yaml :: create-release`
# (`permissions: contents: write`, sin checkout, `gh release create --draft`)
# -> RC 1 falso. La allowlist NO abre la puerta a `gh api` ni a `gh` en general:
# solo a los verbos de publicacion, que no ejecutan codigo del repositorio.
PAT_SINK_OK = re.compile(
    r"^\s*(?:"
    r"npm\s+publish\b"
    r"|pnpm\s+publish\b"
    r"|yarn\s+npm\s+publish\b"
    r"|twine\s+upload\b"
    r"|gh\s+release\s+(?:create|upload|edit)\b"
    r"|docker\s+push\b"
    r"|cargo\s+publish\b"
    r"|poetry\s+publish\b"
    r"|uv\s+publish\b"
    r")"
)
PAT_DINAMICO = re.compile(r"\b(npx|pipx)\b")
PAT_SECRETS = re.compile(r"\$\{\{\s*secrets\.[A-Za-z0-9_]")
PAT_SHA40 = re.compile(r"^[0-9a-f]{40}$")
PAT_UNTRUSTED_REF = re.compile(r"github\.event\.(pull_request\.head|workflow_run\.head)")


def _walk_str(obj):
    """Todos los literales de cadena de un subarbol YAML (claves incluidas)."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _walk_str(v)
    elif isinstance(obj, (list, tuple)):
        for x in obj:
            yield from _walk_str(x)


def _clave_on(wf):
    """PyYAML (YAML 1.1) convierte la clave `on` en el booleano True."""
    for k in (True, "on", "On", "ON"):
        if k in wf:
            return wf[k]
    return None


def _triggers(val):
    if val is None:
        return set()
    if isinstance(val, str):
        return {val}
    if isinstance(val, (list, tuple)):
        return {str(x) for x in val}
    if isinstance(val, dict):
        return {str(k) for k in val.keys()}
    return set()


def _mapa_perm(p):
    if p is None:
        return None
    if isinstance(p, str):
        v = p.strip().lower()
        if v == "write-all":
            return {"*": "write"}
        if v == "read-all":
            return {"*": "read"}
        return {v: "write"}
    if isinstance(p, dict):
        return {str(k): str(v).strip().lower() for k, v in p.items()}
    return None


def scopes_write(mapa):
    if not mapa:
        return set()
    return {k for k, v in mapa.items() if v == "write"}


def _pasos(job):
    out = []
    for s in (job.get("steps") or []):
        if isinstance(s, dict):
            out.append(s)
    return out


def _runs(job):
    return [str(s.get("run", "")) for s in _pasos(job) if "run" in s]


def _uses(job):
    return [str(s.get("uses", "")) for s in _pasos(job) if "uses" in s]


def _todos_los_uses(wf):
    out = []
    jobs = wf.get("jobs")
    if isinstance(jobs, dict):
        for job in jobs.values():
            if not isinstance(job, dict):
                continue
            if isinstance(job.get("uses"), str):
                out.append(job["uses"])
            out.extend(_uses(job))
    return out


def _tiene_checkout(job):
    return any(u.startswith("actions/checkout") for u in _uses(job))


def _tiene_download(job):
    return any(u.startswith("actions/download-artifact") for u in _uses(job))


def _secretos_por_ubicacion(wf, job):
    """Ubica cada `${{ secrets.* }}` en su sumidero real.

    HUELLA-RC4-SUMIDERO-20261106 (medido 2026-11-06): RC 4 medía PRESENCIA de
    `secrets.*`, no EXPOSICION.  Sobre 47 workflows de 6 repos maduros
    (pallets/flask, pydantic/pydantic, python-poetry/poetry, saleor/saleor,
    wagtail/wagtail, encode/httpx) hay 23 jobs con secreto y 23/23 lo pasan en
    `with:` a una accion SHA-pinada (codecov-action, create-github-app-token,
    configure-aws-credentials, create-pull-request): 0/23 en `run:`.  La forma
    documentada de dar una credencial a una accion se reportaba como fuga: el
    100 % de la clase era falso positivo.

    Devuelve (en_run, en_insumo, obs):
      en_run    -- textos `run:` que interpolan un secreto (SINK_SHELL)
      en_insumo -- valores secretos en `env:` (global / de job) o `with:` (SINK_CONTEXTO)
      obs       -- [(ubicacion, fuente)]: el secreto se vio y no es sumidero por si mismo
    """
    en_run, en_insumo, obs = [], [], []
    for etiqueta, src in (("env global", wf.get("env")), ("env de job", job.get("env"))):
        if src:
            vals = [x for x in _walk_str(src) if PAT_SECRETS.search(x)]
            if vals:
                en_insumo.extend(vals)
                obs.append((etiqueta, etiqueta))
    for s in _pasos(job):
        if "run" in s and PAT_SECRETS.search(str(s.get("run", ""))):
            en_run.append(str(s.get("run", "")))
        if "with" in s:
            vals = [x for x in _walk_str(s.get("with")) if PAT_SECRETS.search(x)]
            if vals:
                en_insumo.extend(vals)
                obs.append(("with:", "with: %s" % (str(s.get("uses", "?"))[:60],)))
    return en_run, en_insumo, obs


def _linea_ejecuta(linea):
    """Una linea de shell ejecuta codigo de terceros?"""
    s = linea.strip()
    if not s or s.startswith("#"):
        return False
    if PAT_SINK_OK.match(s):  # ALLOWLIST_SINK: cliente nativo de publicacion
        return False
    return bool(
        PAT_EXEC.search(s) or PAT_FETCH.search(s) or PAT_GITMUT.search(s) or PAT_GH.search(s)
    )


def ref_mutable(valor):
    v = valor.strip()
    if v.startswith("./") or v.startswith(".\\"):
        return False
    if v.startswith("docker://"):
        return "@sha256:" not in v
    if "@" not in v:
        return True
    return not PAT_SHA40.match(v.rsplit("@", 1)[1])


# ----------------------------------------------------------------------------
# NUCLEO
# ----------------------------------------------------------------------------
def analizar(texto, nombre):
    """Devuelve la lista de hallazgos [(rc, causa, archivo, job, detalle)]."""
    return analizar_detallado(texto, nombre)[0]


def analizar_detallado(texto, nombre):
    """Devuelve (hallazgos, observaciones).

    Las observaciones son secretos que el instrumento VIO y no son sumidero por
    si mismos.  Viajan aparte para que `rc` no las cuente como defecto y para
    que el lector pueda distinguir "no lo vi" de "lo vi y no lo es".
    """
    hs = []
    obs = {}
    try:
        wf = yaml.safe_load(texto)
    except yaml.YAMLError as e:
        return [{"rc": 32, "causa": CAUSAS[32], "archivo": nombre, "job": "-",
                 "detalle": str(e)[:200]}], []
    if not isinstance(wf, dict):
        return [{"rc": 32, "causa": CAUSAS[32], "archivo": nombre, "job": "-",
                 "detalle": "raiz del YAML no es un mapping"}], []

    wf_perm = _mapa_perm(wf.get("permissions"))
    triggers = _triggers(_clave_on(wf))
    pr_target = bool(triggers & {"pull_request_target", "workflow_run"})
    clase_trigger = ",".join(sorted(triggers & {"pull_request_target", "workflow_run"}))

    # ---- RC 5: barrido global de referencias
    for v in _todos_los_uses(wf):
        if ref_mutable(v):
            hs.append({"rc": 5, "causa": CAUSAS[5], "archivo": nombre, "job": "-",
                       "detalle": "uses con ref flotante: %s" % (v[:90],)})

    # HUELLA-RC4-SUMIDERO-20261106: el bloque `env:` global ya no emite RC 4 por
    # si mismo.  Lo mide cada job que lo hereda (el env global se propaga a todos
    # los jobs), y solo cuenta como exposicion si el job tiene sumidero.

    jobs = wf.get("jobs")
    if not isinstance(jobs, dict):
        jobs = {}

    for jn in sorted(jobs.keys(), key=str):
        job = jobs.get(jn)
        if not isinstance(job, dict):
            continue
        perm = _mapa_perm(job.get("permissions")) if "permissions" in job else wf_perm
        sw = scopes_write(perm)

        # ---- RC 1: AUTORIDAD_CONTAMINADA
        if sw:
            malas = []
            for cmd in _runs(job):
                for linea in cmd.splitlines():
                    if _linea_ejecuta(linea):
                        malas.append(linea.strip())
            if malas:
                hs.append({"rc": 1, "causa": CAUSAS[1], "archivo": nombre, "job": str(jn),
                           "detalle": "scopes=%s ejecuta: %s"
                                      % (",".join(sorted(sw)), malas[0][:90])})

        # ---- RC 2: SUMIDERO_IMPUDO
        if ("id-token" in sw) or ("*" in sw):
            motivos = []
            if _tiene_checkout(job):
                motivos.append("actions/checkout")
            if any(PAT_DINAMICO.search(c) for c in _runs(job)):
                motivos.append("herramienta dinamica (npx/pipx)")
            if not _tiene_download(job):
                motivos.append("sin actions/download-artifact")
            if motivos:
                hs.append({"rc": 2, "causa": CAUSAS[2], "archivo": nombre, "job": str(jn),
                           "detalle": "; ".join(motivos)})

        # ---- secretos: ubicacion por sumidero (HUELLA-RC4-SUMIDERO-20261106)
        en_run, en_insumo, obs_sec = _secretos_por_ubicacion(wf, job)

        untrusted = False
        if pr_target and _tiene_checkout(job):
            refs = []
            for s in _pasos(job):
                if str(s.get("uses", "")).startswith("actions/checkout"):
                    w = s.get("with")
                    if isinstance(w, dict):
                        refs.append(str(w.get("ref", "")))
            untrusted = any(PAT_UNTRUSTED_REF.search(r) for r in refs)

        # ---- RC 3: DISPARADOR_ENVENENADO
        contexto = bool(sw) or bool(en_run or en_insumo)
        if pr_target and _tiene_checkout(job) and untrusted and contexto:
            hs.append({"rc": 3, "causa": CAUSAS[3], "archivo": nombre, "job": str(jn),
                       "detalle": "trigger %s + checkout de ref no confiable en contexto privilegiado"
                                  % (clase_trigger,)})

        # ---- RC 4: SECRETO_EXPUESTO (secreto + sumidero, no presencia)
        if en_run:
            hs.append({"rc": 4, "causa": CAUSAS[4], "archivo": nombre, "job": str(jn),
                       "detalle": "secrets interpolado en run: (%d bloque(s)): el valor entra al argv"
                                  % (len(en_run),)})
        elif en_insumo and pr_target and untrusted:
            hs.append({"rc": 4, "causa": CAUSAS[4], "archivo": nombre, "job": str(jn),
                       "detalle": "secrets en env/with bajo %s + checkout de ref no confiable"
                                  " (el instrumento no evalua if:/labels: una etiqueta de"
                                  " mantenedor no cubre el relanzamiento por synchronize)"
                                  % (clase_trigger,)})
        else:
            for sitio, fuente in obs_sec:
                obs.setdefault((sitio, fuente), set()).add(str(jn))

    observaciones = [
        {"archivo": nombre, "ubicacion": k[0], "fuente": k[1],
         "job": ", ".join(sorted(js)) if len(js) < 6 else "%d jobs" % (len(js),)}
        for k, js in sorted(obs.items())
    ]
    return hs, observaciones


# ----------------------------------------------------------------------------
# BANCO MUST-FAIL INCORPORADO  (sobre cadenas: CERO escrituras a disco)
# ----------------------------------------------------------------------------
SHA_CHECKOUT = "11bd71901bbe5b1630ceea73d27597364c9af683"
SHA_SETUPNODE = "39370e3970a6d050c480ffad4ff0ed4d3fdee5af"
SHA_UPLOAD = "65c4c4a1ddee5b72f698fdd19549f0f0fb45cf08"
SHA_DOWNLOAD = "fa0a91b85d4f404e444e00e005971372dc801d16"

C0_CANONICO = """
name: publicar
on:
  release:
    types: [published]
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@%s
      - uses: actions/setup-node@%s
        with:
          node-version: "20"
      - run: npm ci --ignore-scripts
      - run: npm pack
      - run: sha256sum ./*.tgz > SHASUMS256.txt
      - uses: actions/upload-artifact@%s
        with:
          name: dist
          path: |
            *.tgz
            SHASUMS256.txt
  publish:
    needs: [build]
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      actions: read
    steps:
      - uses: actions/download-artifact@%s
        with:
          name: dist
      - run: sha256sum -c SHASUMS256.txt
      - run: npm publish --provenance ./*.tgz
""" % (SHA_CHECKOUT, SHA_SETUPNODE, SHA_UPLOAD, SHA_DOWNLOAD)

C1_AUTORIDAD = """
name: contaminado
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@%s
      - run: npm ci
""" % (SHA_CHECKOUT,)

# HUELLA-SINK-NATIVO-20261106: control positivo -- el release canonico de
# `pallets/flask` (autoridad de escritura, sin checkout, `gh release create`)
# tiene que PASAR.  Antes de la allowlist daba RC 1.
C7_PUBLICADOR_NATIVO = """
name: publish
on:
  push:
    tags: ['*']
permissions: {}
jobs:
  create-release:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/download-artifact@%s
        with:
          name: dist
          path: dist/
      - name: create release
        run: gh release create --draft --repo ${GITHUB_REPOSITORY} ${GITHUB_REF_NAME} dist/*
        env:
          GH_TOKEN: ${{ github.token }}
""" % (SHA_DOWNLOAD,)

# ... y su must-fail: `gh` NO es un sink en bloque.  Bajo la misma autoridad,
# `gh api` mutando la configuracion del repositorio sigue siendo RC 1.
C8_GH_API_EN_AUTORIDAD = """
name: contaminado-gh
on: push
jobs:
  alterar:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - run: gh api -X DELETE repos/${GITHUB_REPOSITORY}/branches/main/protection
"""

C2_SUMIDERO = """
name: sumidero
on:
  release:
    types: [published]
jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
    steps:
      - run: npm publish --provenance ./*.tgz
"""

C3_DISPARADOR = """
name: pr-target
on: pull_request_target
jobs:
  lint:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
    steps:
      - uses: actions/checkout@%s
        with:
          ref: ${{ github.event.pull_request.head.sha }}
""" % (SHA_CHECKOUT,)

D1_ENV_SECRETO_SIN_SUMIDERO = """
name: env-secreto
on: push
env:
  TOKEN: ${{ secrets.NPM_TOKEN }}
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - run: echo ok
"""

D2_ACCION_CON_SECRETO = """
name: inputo-de-accion
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@%s
        with:
          repository: alexisromtz-lab/privado
          token: ${{ secrets.REPO_TOKEN }}
""" % (SHA_CHECKOUT,)

D3_SECRETO_EN_RUN = """
name: secreto-en-shell
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - run: |
          curl -sS -H "Authorization: Bearer ${{ secrets.API_TOKEN }}" https://example.test/hook
"""

D4_SECRETO_EN_CONTEXTO_NO_CONFIABLE = """
name: pr-target-con-secreto
on: pull_request_target
jobs:
  comment:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
    steps:
      - uses: actions/checkout@%s
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          token: ${{ secrets.APP_TOKEN }}
""" % (SHA_CHECKOUT,)

C5_REF = """
name: flotante
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
      - run: npm ci --ignore-scripts
"""

C6_DOS_CAUSAS = """
name: sumidero-sucio
on:
  release:
    types: [published]
jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
    steps:
      - uses: actions/checkout@%s
      - uses: actions/download-artifact@%s
        with:
          name: dist
      - run: npx --yes provenance-publish ./dist/*.tgz
""" % (SHA_CHECKOUT, SHA_DOWNLOAD)

BANCO = (
    ("C0_CANONICO_DOS_JOBS", C0_CANONICO, 0, frozenset(), 0),
    ("C1_AUTORIDAD_CONTAMINADA", C1_AUTORIDAD, 1, frozenset([1]), 0),
    ("C2_SUMIDERO_IMPUDO", C2_SUMIDERO, 2, frozenset([2]), 0),
    ("C3_DISPARADOR_ENVENENADO", C3_DISPARADOR, 3, frozenset([3]), 0),
    ("C5_REF_MUTABLE", C5_REF, 5, frozenset([5]), 0),
    ("C6_DOS_CAUSAS_A_LA_VEZ", C6_DOS_CAUSAS, 1, frozenset([1, 2]), 0),
    ("C7_PUBLICADOR_NATIVO", C7_PUBLICADOR_NATIVO, 0, frozenset(), 0),
    ("C8_GH_API_EN_AUTORIDAD", C8_GH_API_EN_AUTORIDAD, 1, frozenset([1]), 0),
    ("D1_ENV_SECRETO_SIN_SUMIDERO", D1_ENV_SECRETO_SIN_SUMIDERO, 0, frozenset(), 1),
    ("D2_ACCION_CON_SECRETO", D2_ACCION_CON_SECRETO, 0, frozenset(), 1),
    ("D3_SECRETO_EN_RUN", D3_SECRETO_EN_RUN, 4, frozenset([4]), 0),
    ("D4_SECRETO_EN_CONTEXTO_NO_CONFIABLE", D4_SECRETO_EN_CONTEXTO_NO_CONFIABLE, 3,
     frozenset([3, 4]), 0),
)
CONTROL = "C0_CANONICO_DOS_JOBS"

# HUELLA-BANCO-RUTAS-20261106: el banco de arriba mide YAML en memoria y no
# puede ver el defecto de argv (RC 31 por ruta duplicada), porque ese defecto
# nace ANTES de leer un archivo. Este segundo banco mide la resolucion del
# universo: cada caso declara la raiz, el directorio esperado y el aviso.
# R4 y R5 son controles negativos: si la resolucion empezara a "adivinar
# cualquier directorio con YAMLs", esos dos casos se pondrian verdes con el
# directorio equivocado y el banco enrojeceria.
BANCO_RUTAS = (
    ("R0_RAIZ_REPO", "/tmp/repo", "/tmp/repo/.github/workflows", None),
    ("R1_YA_ES_WORKFLOWS", "/tmp/repo/.github/workflows",
     "/tmp/repo/.github/workflows", AVISO_D5),
    ("R2_BARRA_FINAL", "/tmp/repo/.github/workflows/",
     "/tmp/repo/.github/workflows", AVISO_D5),
    ("R3_RELATIVA", ".github/workflows", ".github/workflows", AVISO_D5),
    ("R4_CONTROL_BASENAME", "/tmp/repo/workflows",
     "/tmp/repo/workflows/.github/workflows", None),
    ("R5_CONTROL_PARECIDO", "/tmp/repo/.github/workflowz",
     "/tmp/repo/.github/workflowz/.github/workflows", None),
)


def correr_banco_rutas():
    filas = []
    for nombre, raiz, esperado, aviso_esp in BANCO_RUTAS:
        medido, aviso = dir_workflows_efectivo(raiz)
        ok = (medido == esperado) and (aviso == aviso_esp)
        filas.append({
            "caso": nombre,
            "raiz": raiz,
            "directorio_esperado": esperado,
            "directorio_medido": medido,
            "aviso_esperado": aviso_esp,
            "aviso_medido": aviso,
            "ok": ok,
        })
    return filas, all(f["ok"] for f in filas)


def correr_banco():
    filas = []
    for nombre, texto, rc_esp, causas_esp, obs_esp in BANCO:
        hs, obs = analizar_detallado(texto, "<memoria>/%s.yml" % nombre)
        rc = min((h["rc"] for h in hs), default=0)
        causas = frozenset(h["rc"] for h in hs)
        ok = (rc == rc_esp) and (causas == causas_esp) and (len(obs) == obs_esp)
        filas.append({
            "caso": nombre,
            "rc_esperado": rc_esp,
            "rc_medido": rc,
            "causas_esperadas": sorted(causas_esp),
            "causas_medidas": sorted(causas),
            "observaciones_esperadas": obs_esp,
            "observaciones_medidas": len(obs),
            "ok": ok,
            "detalle": [h["detalle"] for h in hs],
        })
    banco_ok = all(f["ok"] for f in filas)
    return filas, banco_ok


# ----------------------------------------------------------------------------
# SALIDA
# ----------------------------------------------------------------------------
def imprimir_cabecera():
    print("UNIVERSO DECLARADO: %s" % UNIVERSO)
    print("MOTOR: %s" % MOTOR)
    print("REGLA DE VEREDICTO: %s" % REGLA)
    print("INVARIANTE: %s" % INVARIANTE)
    print("RESIDUO DECLARADO (PLANO CIEGO FUERA DE YAML):")
    for r in RESIDUO:
        print("  - %s" % r)


def _fmt_causas(s):
    return "{rc:%s|%s}" % (
        ",".join(str(x) for x in s) if s else "-",
        ",".join(CAUSAS.get(x, "?") for x in s) if s else "ninguna",
    )


def dir_workflows_efectivo(raiz):
    """Resuelve el UNICO punto <raiz>/.github/workflows sin anexarlo dos veces.

    Devuelve (directorio, aviso). `aviso` es None salvo que el argumento ya
    apunte al punto resuelto, en cuyo caso vale AVISO_D5.

    No amplia el dominio: solo reconoce la forma exacta `.github/workflows`.
    Un directorio llamado `workflows` que no cuelgue de `.github` sigue
    resolviendo a `<raiz>/.github/workflows` (control negativo en BANCO_RUTAS).
    Funcion pura sobre el texto: no toca disco, para que el banco la ejercite.
    """
    p = os.path.normpath(raiz)
    partes = p.replace("\\", "/").rstrip("/").split("/")
    if len(partes) >= 2 and partes[-1] == "workflows" and partes[-2] == ".github":
        return p, AVISO_D5
    return os.path.join(p, ".github", "workflows"), None


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Gate estructural de CI: topologia de autoridad en .github/workflows/."
    )
    ap.add_argument("ruta", nargs="?", default=".", help="raiz del arbol objetivo (default: .)")
    ap.add_argument("--root", dest="root", default=None, help="raiz explicita del arbol objetivo")
    ap.add_argument("--file", dest="archivo", default=None, help="analizar UN archivo YAML")
    ap.add_argument("--json", dest="json", action="store_true", help="salida JSON")
    ap.add_argument("--self-test", dest="self_test", action="store_true",
                    help="correr el banco must-fail incorporado (sin tocar disco)")
    ap.add_argument("--must-fail", dest="must_fail", action="store_true",
                    help="alias de --self-test: exige que cada causa provoque su RC")
    ns = ap.parse_args(argv)

    banco = ns.self_test or ns.must_fail

    if banco:
        filas, yml_ok = correr_banco()
        filas_rutas, rutas_ok = correr_banco_rutas()
        banco_ok = yml_ok and rutas_ok
        if ns.json:
            print(json.dumps({
                "universo": UNIVERSO, "motor": MOTOR, "invariante": INVARIANTE,
                "regla_de_veredicto": REGLA, "residuo_declarado": list(RESIDUO),
                "causas": CAUSAS, "self_test": filas, "banco_ok": yml_ok,
                "self_test_rutas": filas_rutas, "banco_rutas_ok": rutas_ok,
                "banco_global_ok": banco_ok, "rc": 0 if banco_ok else 21,
            }, indent=2, ensure_ascii=False))
        else:
            imprimir_cabecera()
            print("")
            print("BANCO MUST-FAIL (casos en memoria; el instrumento no escribe disco)")
            print("%-28s %-20s %-20s %-6s %s" % ("CASO", "ESPERADO", "MEDIDO", "OBS", "OK"))
            for f in filas:
                print("%-28s %-20s %-20s %-6s %s" % (
                    f["caso"],
                    _fmt_causas(frozenset(f["causas_esperadas"])),
                    _fmt_causas(frozenset(f["causas_medidas"])),
                    "%d/%d" % (f["observaciones_medidas"], f["observaciones_esperadas"]),
                    "SI" if f["ok"] else "NO",
                ))
            print("")
            for f in filas:
                for d in f["detalle"]:
                    print("  [%s] %s" % (f["caso"], d))
            print("")
            print("BANCO RUTAS (resolucion del universo; funcion pura, sin disco)")
            print("%-24s %-40s %-40s %-6s %s" % (
                "CASO", "DIRECTORIO ESPERADO", "DIRECTORIO MEDIDO", "OK", "AVISO"))
            for f in filas_rutas:
                print("%-24s %-40s %-40s %-6s %s" % (
                    f["caso"], f["directorio_esperado"], f["directorio_medido"],
                    "SI" if f["ok"] else "NO", f["aviso_medido"] or "-",
                ))
            print("")
            print("banco_yml_ok = %s" % yml_ok)
            print("banco_rutas_ok = %s" % rutas_ok)
            print("banco_ok = %s" % banco_ok)
        return 0 if banco_ok else 21

    raiz = ns.root or ns.ruta
    archivos = []
    if ns.archivo:
        dir_universo, aviso = None, None
        archivos = [ns.archivo]
    else:
        dir_universo, aviso = dir_workflows_efectivo(raiz)
        if os.path.isdir(dir_universo):
            for fn in sorted(os.listdir(dir_universo)):
                if fn.endswith(".yml") or fn.endswith(".yaml"):
                    archivos.append(os.path.join(dir_universo, fn))

    hallazgos = []
    observaciones = []
    if not archivos:
        hallazgos.append({"rc": 31, "causa": CAUSAS[31], "archivo": "-", "job": "-",
                          "detalle": "0 archivos en %s: nada que medir" % (
                              dir_universo if dir_universo else raiz,)})
    else:
        for ruta in archivos:
            try:
                with io.open(ruta, "r", encoding="utf-8") as fh:
                    texto = fh.read()
            except Exception as e:
                hallazgos.append({"rc": 32, "causa": CAUSAS[32], "archivo": ruta, "job": "-",
                                  "detalle": "no legible: %s" % (e,)})
                continue
            hs_archivo, obs_archivo = analizar_detallado(texto, ruta)
            hallazgos.extend(hs_archivo)
            observaciones.extend(obs_archivo)

    causas = sorted({h["rc"] for h in hallazgos})
    rc = min(causas) if causas else 0

    if ns.json:
        print(json.dumps({
            "universo": UNIVERSO, "motor": MOTOR, "invariante": INVARIANTE,
            "regla_de_veredicto": REGLA, "residuo_declarado": list(RESIDUO),
            "causas": CAUSAS, "raiz": raiz, "universo_resuelto": dir_universo,
            "aviso": aviso, "archivos": archivos,
            "hallazgos": hallazgos, "causas_presentes": causas, "rc": rc,
            "observaciones": observaciones,
        }, indent=2, ensure_ascii=False))
    else:
        imprimir_cabecera()
        print("")
        print("RAIZ: %s" % raiz)
        if aviso:
            print("AVISO %s: el argumento ya es el directorio de workflows; se mide ahi." % aviso)
            print("  (sin esta normalizacion, anexar '.github/workflows' otra vez daria RC 31")
            print("   UNIVERSO_VACIO y culparia al arbol auditado de un error de argv.)")
        print("UNIVERSO RESUELTO: %s" % (dir_universo if dir_universo else "-"))
        print("ARCHIVOS MEDIDOS: %d" % len(archivos))
        for h in hallazgos:
            print("  RC %-2d %-22s %s :: %s :: %s"
                  % (h["rc"], h["causa"], h["archivo"], h["job"], h["detalle"]))
        print("")
        print("OBSERVACIONES (secreto visto, sin sumidero: NO es hallazgo): %d"
              % len(observaciones))
        for o in observaciones:
            print("  OBS    %-22s %s :: %s (%s)"
                  % (o["ubicacion"], o["archivo"], o["fuente"], o["job"]))
        print("")
        print("CAUSAS PRESENTES: %s" % (causas if causas else "ninguna"))
        print("VEREDICTO: %s  RC=%d" % ("PASA" if rc == 0 else "FALLO CERRADO", rc))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
