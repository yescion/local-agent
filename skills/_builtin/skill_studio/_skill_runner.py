"""Uploaded into Daytona sandbox to invoke one tool from a draft or published skill."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-dir", required=True)
    parser.add_argument("--tool", required=True)
    parser.add_argument("--args", default="{}")
    parser.add_argument("--args-file", default="")
    ns = parser.parse_args()

    skill_dir = Path(ns.skill_dir)
    tools_py = skill_dir / "tools.py"
    if not tools_py.is_file():
        raise FileNotFoundError(f"tools.py not found in {skill_dir}")

    spec = importlib.util.spec_from_file_location("agent_skill_tools", tools_py)
    if not spec or not spec.loader:
        raise ImportError(f"Cannot load {tools_py}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    fn = getattr(module, ns.tool, None)
    if not callable(fn):
        raise AttributeError(f"Tool not callable: {ns.tool}")

    if ns.args_file:
        raw_args = Path(ns.args_file).read_text(encoding="utf-8")
    else:
        raw_args = ns.args
        if raw_args.startswith('"') and raw_args.endswith('"'):
            raw_args = json.loads(raw_args)
    kwargs = json.loads(raw_args)
    if not isinstance(kwargs, dict):
        raise TypeError("args must be a JSON object")

    result = fn(**kwargs)
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        sys.exit(1)
