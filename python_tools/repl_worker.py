#!/usr/bin/env python3
"""
Python REPL worker for the tutoring system.
Reads JSON commands from stdin, executes them, writes JSON results to stdout.
"""

import sys
import json
import uuid
import math
import re
from typing import Any, Dict


def safe_exec(code: str) -> Dict[str, Any]:
    """Execute Python code in a restricted namespace and return result."""
    # Restricted globals
    safe_globals = {
        "__builtins__": {
            "abs": abs,
            "all": all,
            "any": any,
            "bool": bool,
            "dict": dict,
            "enumerate": enumerate,
            "filter": filter,
            "float": float,
            "format": format,
            "int": int,
            "len": len,
            "list": list,
            "map": map,
            "max": max,
            "min": min,
            "pow": pow,
            "range": range,
            "reversed": reversed,
            "round": round,
            "set": set,
            "sorted": sorted,
            "str": str,
            "sum": sum,
            "tuple": tuple,
            "zip": zip,
        },
        "math": math,
        "uuid": uuid,
        "re": re,
    }

    try:
        # Capture the result of the last expression
        # Compile and exec the code
        compiled = compile(code, "<repl>", "exec")
        local_vars: Dict[str, Any] = {}
        exec(compiled, safe_globals, local_vars)

        # Try to evaluate the last expression if it exists
        lines = code.strip().split("\n")
        if lines:
            last_line = lines[-1].strip()
            # If last line is an expression (not assignment), eval it
            if last_line and not any(
                op in last_line
                for op in (
                    "=",
                    "import ",
                    "def ",
                    "class ",
                    "if ",
                    "for ",
                    "while ",
                    "try:",
                    "except",
                    "with ",
                )
            ):
                try:
                    result = eval(last_line, safe_globals, local_vars)
                    return {"success": True, "result": result, "error": None}
                except:
                    # If evaluation fails, just return success
                    return {"success": True, "result": None, "error": None}
            else:
                return {
                    "success": True,
                    "result": local_vars.get("_", None),
                    "error": None,
                }
        # No input lines
        return {"success": True, "result": None, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
            action = request.get("action", "exec")
            code = request.get("code", "")
            request_id = request.get("id", str(uuid.uuid4()))

            if action == "exec":
                result = safe_exec(code)
            elif action == "reset":
                result = {"success": True, "result": "Environment reset", "error": None}
            elif action == "import":
                # Allow safe imports only
                allowed_modules = ["math", "re", "uuid", "collections", "itertools"]
                module = request.get("module", "")
                if module in allowed_modules:
                    try:
                        __import__(module)
                        result = {
                            "success": True,
                            "result": f"Imported {module}",
                            "error": None,
                        }
                    except Exception as e:
                        result = {"success": False, "result": None, "error": str(e)}
                else:
                    result = {
                        "success": False,
                        "result": None,
                        "error": f"Module {module} not allowed",
                    }
            else:
                result = {
                    "success": False,
                    "result": None,
                    "error": f"Unknown action: {action}",
                }

            response = {
                "id": request_id,
                "success": result["success"],
                "result": result["result"],
                "error": result["error"],
            }
            print(json.dumps(response))
            sys.stdout.flush()
        except json.JSONDecodeError:
            print(
                json.dumps(
                    {
                        "id": "error",
                        "success": False,
                        "result": None,
                        "error": "Invalid JSON input",
                    }
                )
            )
            sys.stdout.flush()


if __name__ == "__main__":
    main()
