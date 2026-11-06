<!-- HUELLA-README-ES-20261105 -->
**Idioma:** Español · [English](README.md)

# preflight-gate

**Repository:** [`git-preflight-gate`](https://github.com/alexisromtz-lab/git-preflight-gate)

**Un gate de integridad para agentes de IA autónomos: que un bot no ensucie el árbol
ni cometa colisiones de concurrencia.**

## Qué se entrega como producto, y qué está en el banco de pruebas

| nivel | artefacto | estado | medido el 06-Nov-2026 |
|---|---|---|---|
| **producto** | `preflight-gate.sh` — 145 líneas de bash, cero dependencias | estable | banco de casos **9/9**, cada código con su causa |
| banco | `sim/gate_workflows_ci.py` + el `action.yml` de la raíz | **experimental** | dispara en **9/9** repos públicos mantenidos ⇒ todavía no discrimina |

Todo lo que hay desde [`Parte 2`](#parte-2--análisis-topológico-avanzado-experimental)
hacia abajo es ese segundo instrumento. Se publica porque sus falsadores están publicados,
no porque esté listo para bloquear un merge: su tasa base medida está en esa sección, y
leerla es el punto.

Descargar el producto:

```bash
curl -fsSL https://raw.githubusercontent.com/alexisromtz-lab/git-preflight-gate/main/preflight-gate.sh \
  -o preflight-gate.sh
```

Sin paso de instalación, sin `pip`, sin action, sin token.

Antes de que un agente escriba una línea, el gate exige una tupla de destino —
`TARGET` (absoluto) · `BLOB_PRE` · `HUELLA` · `LINEAS_PRE` — y devuelve un código que
**autoriza o bloquea** la escritura. Sin corrida previa con `RC 0`, no se escribe.

```bash
bash preflight-gate.sh /ruta/absoluta/archivo.py <blob_pre> <huella_exclusiva> <lineas_pre>
```

## Los códigos (fail-closed)

| RC | significado |
|---:|---|
| `0` | PRE-VUELO OK — el destino acepta la edición sobre `BLOB_PRE` |
| `10` | el objeto no existe (creación) |
| `11` | **la huella ya habita en el destino** ⇒ colisión: la fila ya está escrita |
| `12` | blob medido ≠ contrato ⇒ el árbol se movió |
| `13` | estado sucio en git ⇒ modificaciones no adjudicadas |
| `14` | el destino no vive en un árbol git ⇒ el gate no puede validar identidad |
| `15` | líneas distintas al contrato |
| `20` | uso incorrecto (tupla incompleta, o `TARGET` no absoluto) |

Cada código sale **con su causa impresa**. Un `RC` correcto por el motivo equivocado
no es un gate: es una coincidencia.

## Por qué `RC 11` es el caso que importa

El defecto más caro de un agente no es equivocarse de ruta: es **volver a escribir algo
que otra mano ya escribió**, y reportar éxito. La huella es un fragmento literal
exclusivo del texto a insertar; si ya está en el destino, la escritura se rechaza antes
de tocar el archivo. El gate no adivina intenciones: niega la colisión.

## Por qué `TARGET` debe ser absoluto

El gate re-basa con `git -C <directorio>` para medir el blob y el estado. Una ruta
relativa se contaría desde **dos bases distintas** (`cwd` y el directorio del objeto) y
podría hashear *otro* archivo que sí existe. Fail-closed: ruta relativa ⇒ `RC 20`.

## Por qué `RC 14` existe

Sin árbol git, `git status` devuelve 128 con salida vacía. Un gate ingenuo lee esa
salida vacía como «limpio» y da verde. Aquí se declara la imposibilidad: sin árbol no
hay identidad de blob que valga.

## Banco de casos

```bash
bash tests/must_fail.sh
```

9 casos, **9/9**, cada uno verificando código **y** causa: `20` (tupla incompleta),
`20` (ruta relativa), `10`, `11`, `12`, `15`, `13`, `14` y el control positivo `0`.
Un banco sin control positivo sólo demuestra que el instrumento sabe decir que no.

## Telemetría fuera de banda

Cada corrida anota 7 campos (`hora_utc target blob_pre blob_medido rc hash_arbol_ini
hash_arbol_fin`) en `${GATE_TELEMETRIA_LOG:-$HOME/preflight-telemetria.log}`. La
telemetría **no puede mover el RC**, **no puede abortar** y **no puede refrescar el
índice** (`--no-optional-locks`). La ruta nunca es relativa: un log dentro del árbol se
vuelve un archivo no rastreado, y entonces el gate termina midiendo su propia
telemetría — el instrumento que se cuenta a sí mismo.

## Límites declarados

- Sobre un `TARGET` inexistente el gate corta en `RC 10` **antes** de comparar blob y
  líneas: en la rama de creación, la tupla es **contrato**, no medición. Se declara; no
  se repara (fail-closed es correcto).
- No juzga el contenido: certifica identidad y colisión, no corrección.
- **Este build es un subconjunto del gate del que salió.** Las 145 líneas publicadas aquí
  implementan nueve códigos. La implementación de referencia de la que vienen implementa
  cuatro más, y son justo los que defienden contra un *falso verde*: `RC 19` (la huella
  está pero el blob **no** es el contratado ⇒ ratificación *sin* identidad), `RC 23` (el
  destino está ignorado por git ⇒ `git status` devuelve vacío, un gate ingenuo lee «limpio»
  y **autoriza** una escritura sin historia), `RC 24` (el índice lleva un bit de frescura
  ⇒ git se niega a comparar y la misma salida vacía se lee como limpio) y `RC 31` (el
  objeto está vacío con `LINEAS_PRE > 0`). Mientras este archivo no se ponga al día, un
  `RC 11` aquí significa *la marca está*, no *el objeto es el que contrataste*.
  Medido sobre la edición de esta misma página: post-vuelo con blob contratado `ec33b0c0`
  sobre un disco que tenía `c63c73ce` devolvió `RC 11`; el gate de referencia devuelve
  `RC 19` ahí. Mismo archivo, misma tupla, dos veredictos: ese es el hueco, y es lo
  siguiente que se cierra.

---

# Parte 2 — Análisis topológico avanzado (experimental)

**Nada de esta parte es el producto.** Es un segundo instrumento, con su propio dominio,
su propia dependencia (`PyYAML`) y su propio defecto sin resolver. Se documenta porque un
instrumento de banco que esconde su tasa base es indistinguible de una estafa.

## Estado medido: todavía no discrimina

El veredicto es `RC = min(causas)`, así que **gana la causa de número más bajo presente**.
Las causas `1`, `2`, `4` y `5` describen la postura ordinaria de un pipeline de release
real — un job con `contents: write` que corre `npm ci`, un sumidero que publica sin
`download-artifact`, `${{ secrets.* }}` en un bloque `env:`, `uses: …@v4` en vez de un
SHA de 40 caracteres. Ninguna de esas es un defecto: son la forma de publicar.

Barrido medido el 06-Nov-2026 sobre `.github/workflows/` de nueve repositorios públicos
mantenidos — `git clone --depth 1`, una llamada `--root` por repo:

| repo | archivos de workflow | veredicto | causas presentes |
|---|---:|---|---|
| `psf/requests` | 8 | RC 1 · FALLO CERRADO | 1 |
| `astral-sh/ruff` | 25 | RC 1 · FALLO CERRADO | 1, 2, 4, 5 |
| `pydantic/pydantic` | 9 | RC 1 · FALLO CERRADO | 1, 2, 4 |
| `tiangolo/fastapi` | 18 | RC 1 · FALLO CERRADO | 1, 2, 4 |
| `pallets/flask` | 5 | RC 1 · FALLO CERRADO | 1 |
| `numpy/numpy` | 23 | RC 2 · FALLO CERRADO | 2, 4 |
| `vitejs/vite` | 13 | RC 1 · FALLO CERRADO | 1, 2, 4, 5 |
| `sharkdp/bat` | 2 | RC 4 · FALLO CERRADO | 4, 5 |
| `jqlang/jq` | 8 | RC 1 · FALLO CERRADO | 1, 2, 4, 5 |
| **total** | **111** | **9/9 FALLO CERRADO** | — |

La tasa base del veredicto bloqueante sobre repositorios mantenidos es por tanto **100 %**,
y un gate que está rojo en todo no está midiendo: está rechazando. Sólo la causa `3`,
`DISPARADOR_ENVENENADO` — `pull_request_target` / `workflow_run` más `actions/checkout`
de `github.event.pull_request.head` dentro de un contexto con scopes de escritura o
secretos, la forma "pwn request" — disparó **0 de 9**. Es la única causa que describe
explotación por un atacante y no postura de un mantenedor.

**Lo que haría publicable este instrumento** no es otra causa. Es particionar el veredicto:
la causa `3` bloquea, las causas `1/2/4/5` pasan a ser postura declarada que se imprime en
cada corrida, y `RC 31` sigue siendo lo que es — una falla de *lectura*, nunca un veredicto.
Esa partición sólo es publicable junto con su control positivo: el caso
`C3_DISPARADOR_ENVENENADO` de `--self-test` tiene que seguir disparando `RC 3`, o el
arreglo cambiaría un instrumento rojo-en-todo por uno verde-en-todo, que es el más
peligroso de los dos. Hasta que existan los dos, esto está en el banco.

## La Action de la raíz: CI Authority Gate

**Marketplace:** [Install the action](https://github.com/marketplace/actions/ci-authority-gate)
— la ficha conserva el nombre con el que se registró.

El `action.yml` de este repositorio es una **action composite** que ejecuta un segundo
instrumento, `sim/gate_workflows_ci.py`: un verificador estructural de la topología de
autoridad en `.github/workflows/`. Cinco invariantes contables, siete causas tipadas,
`RC = min(causas)`, `UNIVERSO_VACIO` = causa `31` (cero archivos es fracaso, no
aprobación).

Identidad medida del instrumento copiado a este árbol:

| propiedad | valor |
|---|---|
| líneas / bytes | 615 / 21470 |
| git blob | `ff9c69a944e7965b3fda0901f7745d80a9e85c7c` |
| sha256-16 | `073954a84f3c84fd` |

Uso como consumidor:

```yaml
- uses: alexisromtz-lab/git-preflight-gate@v0.1.4
  with:
    workflows-dir: .github/workflows
    fail-on-red: "true"
```

<!-- HUELLA-RELEASE-V013-20261031 -->
`v0.1.3`, `v0.1.2` y `v0.1.1` ejecutan el mismo `action.yml` (`9ef420ec`) y el mismo
`sim/gate_workflows_ci.py` (`ff9c69a9`): el código del gate no cambió entre los tres.
Lo que cambia es el envoltorio de adopción —`v0.1.2` añadió `templates/platino-gate.yml`
y `v0.1.3` añadió `action-selftest.yml`, la alineación del manifiesto y esta
documentación—. Si fijas por SHA, usa el commit —no el tag—.

Los cuatro inputs (`workflows-dir`, `root`, `python-bin`, `fail-on-red`) y los dos
outputs (`rc`, `veredicto`) conservan el contrato del `action.yml` que este repositorio
**reemplaza**: cualquier CI que apuntaba a la action de la raíz de un repositorio de
trabajo migra cambiando sólo el nombre del repositorio en `uses:`; el resto del bloque
`with:` no cambia.

La acción no adivina el dominio: el instrumento resuelve un único punto,
`<raiz>/.github/workflows`. Por eso `workflows-dir` se enruta a `--file` cuando el path
existe y a `--root` cuando no. Un `--root` que aceptara cualquier directorio con YAMLs
sería editar el metro para que quepa la demo.

Dependencia única: `PyYAML==6.0.3`, declarada como extra opcional
(`pip install ".[ci-authority-gate]"`). El resto es stdlib. El instrumento no lee red,
no escribe archivos, no usa aleatoriedad y no consulta el reloj.

Instalable sin clonar el repositorio, desde el wheel de la release. El extra
`ci-authority-gate` es obligatorio para el CLI: sin PyYAML el instrumento no mide y
sale con `RC=30` (fail-closed), no con verde.

```bash
pip install "git-preflight-gate[ci-authority-gate] @ https://github.com/alexisromtz-lab/git-preflight-gate/releases/download/v0.1.4/git_preflight_gate-0.1.4-py3-none-any.whl"
ci-authority-gate --self-test   # banco must-fail incorporado; no toca disco
ci-authority-gate --root .      # mide <raiz>/.github/workflows y devuelve su RC
```

<!-- HUELLA-README-V014-20261106 -->
`v0.1.4` no cambia el gate: `action.yml` (`9ef420ec`) y `sim/gate_workflows_ci.py`
(`ff9c69a9`) son los mismos blobs que en `v0.1.3`. Lo que cambia es el paquete:
`MANIFEST.in` hace que el sdist lleve el producto, y el manifiesto declara el paquete
`sim` y el script `ci-authority-gate`. Antes de este cambio el wheel eran 6 768 B de
solo `dist-info` y no existía ningún CLI. En PyPI todavía no está publicado: la única
vía de `pip` hoy es la URL de la release.

Control positivo medido: workflow con `permissions: contents: read` y `uses` fijado por
SHA completo ⇒ `CAUSAS PRESENTES: ninguna`, `VEREDICTO: PASA`, `RC=0`. Control negativo:
`pull_request_target` + `permissions: write-all` + `curl | bash` + `actions/checkout@v4`
⇒ `CAUSAS PRESENTES: [1, 2, 5]`, `RC=1`. Universo vacío ⇒ `CAUSAS PRESENTES: [31]`,
`RC=31`.

## Los dos instrumentos no se confunden

| instrumento | pregunta | forma |
|---|---|---|
| `preflight-gate.sh` | ¿este agente puede escribir *este archivo* ahora? | CLI bash, tupla de destino |
| `sim/gate_workflows_ci.py` | ¿esta topología de CI concentra autoridad sin control? | action composite + CLI Python |

El primero protege una escritura; el segundo audita un árbol de workflows. Comparten la
doctrina (fail-closed, causa impresa, cero archivos = imposibilidad declarada), no el
código.

## Instalar la Action en tu repositorio en 1 minuto

> **Esto instala el instrumento experimental, no el producto.** La plantilla de abajo
> ejecuta `action.yml`, que ejecuta `sim/gate_workflows_ci.py`. Lee antes
> [Estado medido](#estado-medido-todavía-no-discrimina): en un repositorio mantenido este
> workflow se pone rojo hoy por motivos que no son defectos.

<!-- HUELLA-BADGE-PLATINO-README-20261031 -->

```bash
mkdir -p .github/workflows
curl -fsSL https://raw.githubusercontent.com/alexisromtz-lab/git-preflight-gate/main/templates/platino-gate.yml \
  -o .github/workflows/platino-gate.yml
git add .github/workflows/platino-gate.yml
git commit -m "ci: platino preflight gate"
git push
```

Eso es todo: el workflow se dispara en el siguiente `push` o PR.

### El archivo debe llamarse `platino-gate.yml` (esto es un contrato, no un consejo)

Si lo renombras —`ci.yml`, `gate.yml`, `platino-gate.yaml`— el primer job falla
cerrado con `RC 20` y te dice por qué. La razón es medida, no estética: el badge
de estado se resuelve **por nombre de archivo** (`.../workflow/status/TU-REPO/TU-REPO/platino-gate.yml`).
Con otro nombre, el badge leería *tu* workflow de CI, no este gate, y publicaría un
verde que no mide nada. El contrato está dentro del workflow, no en esta página.

Falsado por `tests/test_platino_gate_template.py`: 5 casos de nombre y 5
estructurales, `RC 0` solo si los 10 concuerdan; un template mutado para aceptar
cualquier `.yml` devuelve `RC 1` nombrando la fila culpable.

## El badge

Al terminar el run, la pestaña **Summary** publica el badge ya rellenado con tu
`owner/repo`. Hay dos, y no son lo mismo:

| badge | qué afirma | permisos que pide |
|---|---|---|
| de **estado** (dinámico) | el resultado real del run más reciente de `platino-gate.yml` | `contents: read` |
| **sello** (estático) | «este repositorio pasó el gate» | `contents: read` |

```markdown
[![Platino Preflight Gate](https://img.shields.io/github/actions/workflow/status/OWNER/REPO/platino-gate.yml?label=preflight%20gate&branch=main)](https://github.com/alexisromtz-lab/la-auditora)

[![Audited by Platino Labs](https://img.shields.io/badge/audited_by-Platino_Labs-6f42c1)](https://github.com/alexisromtz-lab/la-auditora)
```

El de estado no puede mentir: lo dibuja GitHub desde el run. **El sello, sí**: es un
literal que cualquiera puede pegar en verde sin haber corrido nada. Ponlo solo cuando
el run esté en verde — el gate no lo puede verificar por ti.

**Cero permisos de escritura, en los dos casos.** El workflow no toca tu README, no
pide `contents: write` y no necesita ningún servicio nuestro: el badge es una URL de
`shields.io` que lee el estado público de tu propio workflow. No hay endpoint que
hospedar, ni token que caducar.

### Qué mide y qué no

| mide | no mide |
|---|---|
| topología de autoridad en `.github/workflows/`: `permissions`, disparadores, `uses` por SHA, sumideros de ejecución | si tu código hace lo que dice |
| siete causas tipadas, `RC = min(causas)`, `UNIVERSO_VACIO` = causa `31` | los permisos por defecto del `GITHUB_TOKEN` a nivel de organización |
| el árbol que tienes, en el commit que corre | confianza OIDC / Trusted Publishing en el registro destino |

El segundo bloque está impreso en cada run, bajo `RESIDUO DECLARADO`. Un gate que no
declara sus límites no es un gate: es una promesa.

### Cómo se prueba el propio envoltorio

<!-- HUELLA-BADGE-SELFTEST-DOC-20261031 -->
El `action.yml` no se prueba leyendo su YAML: se ejecuta. En cada push a `main`, el
workflow [`action-selftest.yml`](.github/workflows/action-selftest.yml) corre la acción
dos veces con `uses: ./` —sobre este mismo repositorio, donde exige `rc=0` / `PASA`, y
sobre una fixture envenenada en `tests/fixtures/sumidero`, donde exige `rc=2` /
`SUMIDERO_IMPUDO`—. Si la instalación del extra (`pip install "<action_dir>[ci-authority-gate]"`)
o el enrutado de inputs se rompen, enrojece aquí antes de enrojecer en tu runner.

Un self-test que sólo sabe estar verde no discrimina nada: por eso el segundo caso exige
que la acción **falle** con la causa correcta.

## Licencia

MIT. Ver `LICENSE`.
