"""Static guards for this integration.

Catches mistakes that are valid Python (so linters stay quiet) but break at
runtime inside Home Assistant. Run it before shipping:

    python3 scripts/check_integration.py
"""
import sys, pathlib, ast

PKG = pathlib.Path('/home/riza-aslan/DEV/Anthbot-HA/repo/custom_components/anthbot_genie')

# Names HA's Entity/base classes own. Overriding these with a different
# meaning silently corrupts the entity (this is what broke the settings).
# Members that carry HA-defined meaning and that we would only ever redefine
# by accident. `state` is the one that actually bit us: returning the mower's
# shadow dict from it made every settings entity report "unknown", because HA
# takes Entity.state as the entity's state string (max 255 chars).
RESERVED = {
    "state", "hass", "platform", "registry_entry", "entity_id",
    "coordinator", "entity_description",
}
# Documented override points are fine — those are meant to be implemented.
ALLOWED = set()

bad = []
for path in sorted(PKG.glob("*.py")):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        for item in cls.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            is_prop = any(getattr(d, "id", getattr(getattr(d, "attr", None), "__str__", lambda: None)()) == "property"
                          for d in item.decorator_list)
            if not is_prop:
                continue
            if item.name in RESERVED and item.name not in ALLOWED:
                bad.append(f"{path.name}:{item.lineno} {cls.name}.{item.name} shadows HA Entity.{item.name}")

# hass.services.async_register(domain, service, handler) takes exactly three
# positional arguments. A stray extra one silently binds to `schema` and setup
# dies with "got multiple values for argument 'schema'".
for path in sorted(PKG.glob("*.py")):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "async_register"):
            continue
        if len(node.args) != 3:
            bad.append(
                f"{path.name}:{node.lineno} async_register() takes 3 positional "
                f"args, got {len(node.args)}"
            )

if bad:
    print("PROBLEMS:")
    for b in bad: print("  " + b)
    sys.exit(1)
print("OK: no reserved Entity names shadowed; service registrations well-formed")
