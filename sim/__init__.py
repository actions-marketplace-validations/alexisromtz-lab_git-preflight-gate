"""Paquete del gate estructural de CI (`gate_workflows_ci`).

HUELLA-SIM-PAQUETE-20261106: el manifiesto declara este paquete para que el
wheel lleve el instrumento y `pip install` deje un CLI en el PATH. El action
composite NO lo usa: invoca el instrumento por ruta absoluta, porque en un
runner `github.action_path` apunta al checkout de la accion, no a
site-packages. Las dos rutas conviven y ninguna depende de la otra.
"""
