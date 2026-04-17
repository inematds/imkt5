#!/usr/bin/env bash
# scripts/new-worker.sh — scaffolding de worker novo.
#
# Uso:  scripts/new-worker.sh <nome> <capability> [<porta>]
#
# Exemplo:
#   scripts/new-worker.sh scraper research.scrape 8110
#
# Cria:
#   workers/<nome>/server.py  — skeleton BaseWorker
#   workers/<nome>/SKILL.md   — template de instruções
#   + entrada em config/workers.yaml
#   + linha em scripts/start-dev.sh

set -euo pipefail

if [ $# -lt 2 ]; then
  echo "uso: $0 <nome> <capability> [<porta>]"
  echo "ex:  $0 scraper research.scrape 8110"
  exit 1
fi

NAME="$1"
CAP="$2"
PORT="${3:-}"

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

if [ -z "$PORT" ]; then
  # Descobre próxima porta livre >= 8110
  USED=$(grep -oE "endpoint: http://localhost:[0-9]+" config/workers.yaml | grep -oE "[0-9]+$" | sort -n | tail -1)
  PORT=$((USED + 1))
  [ $PORT -lt 8110 ] && PORT=8110
fi

DIR="workers/$NAME"
if [ -d "$DIR" ]; then
  echo "erro: $DIR já existe"
  exit 1
fi

echo "→ Criando $DIR/ (capability=$CAP, porta=$PORT)"
mkdir -p "$DIR"

# SKILL.md template
cat > "$DIR/SKILL.md" <<SKILL_EOF
# ${NAME^}

## Role

Descreva o papel do worker em 2-3 frases. O que ele faz, quando é usado.

## Inputs

Payload JSON:
\`\`\`json
{
  "campo1": "...",
  "campo2": "..."
}
\`\`\`

## Output schema

Retorne APENAS este JSON:
\`\`\`json
{
  "result": {
    "field1": "...",
    "field2": "..."
  }
}
\`\`\`

## Quality bar

- Descreva as regras objetivas de qualidade aqui.
- Usadas pelo auto-reviewer como critérios.
SKILL_EOF

# server.py template
PORT_VAR="$(echo "$NAME" | tr '[:lower:]-' '[:upper:]_')_PORT"
CLASS_NAME="$(echo "$NAME" | sed -E 's/(^|-)([a-z])/\U\2/g')Worker"

cat > "$DIR/server.py" <<PY_EOF
"""${NAME} worker.

Capability: \`${CAP}\`. Porta ${PORT}.

Descreva o propósito do worker aqui.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from workers._base import BaseWorker
from workers._base.llm_client import complete_json, load_tenant_knowledge

SKILL_PATH = Path(__file__).parent / "SKILL.md"


class ${CLASS_NAME}(BaseWorker):
    name = "${NAME}"
    capabilities = ("${CAP}",)

    def __init__(self) -> None:
        self._skill = SKILL_PATH.read_text() if SKILL_PATH.exists() else ""

    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        # TODO: validar campos obrigatórios do payload

        knowledge = load_tenant_knowledge(job.tenant_id)

        system = f"{self._skill}\n\n## TENANT KNOWLEDGE\n\n{knowledge or '(none)'}"
        user = str(payload)  # TODO: estruturar prompt

        data = await complete_json(
            system_prompt=system,
            user_prompt=user,
            temperature=0.3,
        )
        return data


if __name__ == "__main__":
    import os
    port = int(os.environ.get("${PORT_VAR}", ${PORT}))
    ${CLASS_NAME}().run(port=port)
PY_EOF

# registra em config/workers.yaml
cat >> config/workers.yaml <<YAML_EOF

  - name: ${NAME}
    capabilities: [${CAP}]
    endpoint: http://localhost:${PORT}
    local: true
    priority: 50
    timeout_seconds: 120
    max_concurrent: 2
YAML_EOF

# linha em start-dev.sh (antes do "── gateway ──")
if ! grep -q "workers/${NAME}/server.py" scripts/start-dev.sh; then
  python3 - <<PATCH
import re
path = "scripts/start-dev.sh"
t = open(path).read()
marker = "── gateway ──"
# insere antes do separador do gateway
new_line = f'\nstart_bg "${NAME}" "\$VENV" workers/${NAME}/server.py\n'
t = t.replace("echo \"── gateway ──", new_line + "echo \"── gateway ──", 1)
open(path, "w").write(t)
PATCH
fi

echo "✓ Worker criado: $DIR/"
echo "  - SKILL.md (edite conforme necessário)"
echo "  - server.py (implemente handle())"
echo "  - registrado em config/workers.yaml"
echo "  - linha adicionada em scripts/start-dev.sh"
echo ""
echo "Próximos passos:"
echo "  1. Edite workers/$NAME/SKILL.md"
echo "  2. Implemente a lógica em workers/$NAME/server.py"
echo "  3. systemctl --user restart imkt4-dev"
