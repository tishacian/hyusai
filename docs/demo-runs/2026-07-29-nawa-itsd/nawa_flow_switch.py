"""Basculer le System Password Reset entre son flow à modèles et son jumeau simulé.

Les deux graphes vivent déjà en prod avec leurs `skill_id` résolus : l'actif dans
`flow_definition`, le jumeau dans `settings.fallback_flow_definition`. Repartir de
l'artefact du dépôt perdrait ces liens, donc la bascule se fait de base à base, et
le graphe quitté est rangé dans `settings.<sens>_flow_snapshot` avant d'être
remplacé.

    python nawa_flow_switch.py            # dire où on en est
    python nawa_flow_switch.py fallback   # passer au jumeau sans modèle
    python nawa_flow_switch.py primary    # revenir au flow à modèles
"""

import json
import subprocess
import sys

BASE = "https://agentium.papai.ai/api/v1"
SYSTEM = "571d067a-f82b-472b-b746-db8f5c87b7d2"
TOKEN = open("/tmp/tok").read().strip()
HEAD = ["-H", f"Authorization: Bearer {TOKEN}", "-H", "X-Workspace-Slug: nawa"]


def call(args):
    out = subprocess.run(["curl", "-s", *args], capture_output=True, text=True).stdout
    return json.loads(out)


def system():
    return call([f"{BASE}/systems/{SYSTEM}", *HEAD])


def kinds(flow):
    """Combien de nœuds appellent un modèle : c'est ce qui distingue les deux graphes."""
    return sum(1 for n in flow.get("nodes", []) if n.get("type") == "llm")


def patch(flow, settings):
    body = json.dumps({"flow_definition": flow, "settings": settings})
    return call(
        [
            "-X", "PATCH", f"{BASE}/systems/{SYSTEM}", *HEAD,
            "-H", "Content-Type: application/json", "-d", body,
        ]
    )


def main():
    want = sys.argv[1] if len(sys.argv) > 1 else "status"
    s = system()
    settings = dict(s.get("settings") or {})
    active = s["flow_definition"]
    live = "primary" if kinds(active) else "fallback"
    print(f"en place : {live}  ({kinds(active)} nœuds de modèle, {len(active['nodes'])} nœuds)")

    if want == "status":
        return
    if want == live:
        print("rien à faire")
        return

    if want == "fallback":
        target = settings.get("fallback_flow_definition")
        if not target:
            sys.exit("pas de jumeau dans les réglages du System")
        settings["primary_flow_snapshot"] = active
    elif want == "primary":
        target = settings.get("primary_flow_snapshot")
        if not target:
            sys.exit("pas d'instantané du flow à modèles : bascule non réversible depuis la base")
    else:
        sys.exit("usage : nawa_flow_switch.py [status|fallback|primary]")

    result = patch(target, settings)
    if "id" not in result:
        sys.exit(f"le PATCH a échoué : {json.dumps(result)[:300]}")
    after = system()["flow_definition"]
    now = "primary" if kinds(after) else "fallback"
    print(f"basculé vers : {now}  ({kinds(after)} nœuds de modèle, {len(after['nodes'])} nœuds)")
    if now != want:
        sys.exit("la bascule n'a pas pris")


main()
