# Commands

Comandos slash configurados mediante YAML para Agent Zero.

Este plugin le permite definir `/commands` reutilizables como archivos `.command.yaml` con cualquiera de las siguientes opciones:

- un cuerpo de plantilla `.txt`
- un hook de script `.py`

Los comandos se gestionan desde el modal del plugin y pueden insertarse directamente desde el compositor del chat cuando el primer token comienza con `/`.

## Características

- Archivos de configuración `.command.yaml` con metadatos del comando
- Comandos de plantilla de texto con marcadores de posición `{}` y argumentos analizados
- Comandos de hook de Python con argumentos analizados y carga útil opcional del historial del chat
- Analizador unificado para argumentos posicionales, cola de texto libre y banderas (flags)
- Resolución de comandos consciente del ámbito (scope) a través de los ámbitos de proyecto y global
- Selector de slash en el compositor del chat con navegación por teclado y flujo de creación si está vacío

## Modelo de Archivo de Comando

Cada comando se define mediante un archivo de configuración más un archivo de contenido en el mismo directorio de ámbito.

Ejemplo de comando de texto:

`scan.command.yaml`

```yaml
name: scan
description: Scan a Git repository.
argument_hint: /scan --git-url https://github.com/org/repo
type: text
template_path: scan.txt
```

`scan.txt`

```txt
Please scan repository: {args.flags.git_url}

Raw input:
{raw}
```

Ejemplo de comando de hook de python:

`optimize.command.yaml`

```yaml
name: optimize
description: Optimize the current request.
argument_hint: /optimize 30%
type: script
script_path: optimize.py
include_history: true
```

`optimize.py`

```python
def run(payload):
    args = payload["arguments"]
    pct = args["positional"][0] if args["positional"] else "10%"
    return {
        "text": f"Optimize this response by {pct}.",
        "effects": [],
    }
```

## Análisis de Argumentos

El analizador soporta:

- Entrada posicional: `/scan https://github.com/org/repo`
- Banderas largas: `/scan --git-url https://github.com/org/repo`
- Banderas largas con signo igual: `/scan --git-url=https://github.com/org/repo`
- Banderas cortas y agrupadas: `/scan -v -q` o `/scan -vq`

Los datos analizados están disponibles para:

- Plantillas de texto a través de marcadores de posición `{}`:
  - `{raw}`
  - `{args.positional.0}`
  - `{args.flags.git_url}`
- Scripts de Python a través de `payload["arguments"]`

## Contrato del Hook de Script

El archivo de hook de Python debe exponer:

```python
def run(payload): ...
```

Puede devolver:

- `str` (utilizado como texto de reemplazo)
- `dict` con:
  - `text: str` (texto de reemplazo)
  - `effects: list[dict]`

Efectos de frontend soportados:

- `{"type": "replace_input", "text": "..."}`
- `{"type": "append_input", "text": "..."}`
- `{"type": "toast", "level": "info|error|success", "message": "..."}`

## Resolución de Ámbito (Scope)

Los comandos se descubren en estas carpetas de ámbito:

- Proyecto: `usr/projects/<project>/.a0proj/plugins/commands/commands/`
- Global (fallback): `usr/plugins/commands/commands/`

Precedencia en el selector del chat:

1. Proyecto
2. Global

## Interfaces de UI

- Modal del plugin: abra el gestor de Comandos desde el diálogo de Plugins
- Acción rápida de la barra lateral: icono de terminal junto al botón de Plugins
- Compositor del chat: escriba `/` al inicio de la entrada en línea para navegar por los comandos

## Habilidad del Agente

El plugin incluye `commands-create-slash-command`, una habilidad limitada al ámbito del plugin que ayuda a Agent Zero a crear o actualizar archivos de comandos.
