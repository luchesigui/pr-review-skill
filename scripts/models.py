#!/usr/bin/env python3
"""Show or update the global review agent model settings."""
import argparse
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import common
from model_catalog import PROVIDERS


def save_role(role, changes):
    path = common.config_path()
    if not common.is_configured():
        raise ValueError("run /review-pr setup first")
    with open(path, encoding="utf-8") as source:
        config = json.load(source)
    agents = config.setdefault("agents", {})
    providers = {"native", *PROVIDERS}
    if "provider" in changes and changes["provider"] not in providers.union(
        agents.get("custom_commands", {})
    ):
        raise ValueError("provider must be built in or configured in agents.custom_commands")

    agents.setdefault("roles", {}).setdefault(role, {}).update(changes)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=os.path.dirname(path), delete=False
    ) as destination:
        temporary_path = destination.name
        try:
            json.dump(config, destination, indent=2, ensure_ascii=False)
            destination.write("\n")
            destination.close()
            os.replace(temporary_path, path)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", nargs="?", choices=common.DEFAULT_CONFIG["agents"]["roles"])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--pick", action="store_true")
    mode.add_argument("--list", action="store_true")
    parser.add_argument("--provider")
    parser.add_argument("--model", help='Model ID, or "" to use the provider default')
    parser.add_argument("--effort")
    args = parser.parse_args()
    changes = {
        field: getattr(args, field)
        for field in ("provider", "model", "effort")
        if getattr(args, field) is not None
    }
    if changes and (not args.role or args.list):
        parser.error("specify a role to change its settings")

    if args.pick or (not args.role and not args.list and sys.stdin.isatty() and sys.stdout.isatty()):
        if args.role or args.list:
            parser.error("--pick opens the selector without role arguments")
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            parser.error("--pick requires an interactive terminal")
        if not common.is_configured():
            parser.error("run /review-pr setup first")
        import model_menu

        try:
            model_menu.run(save_role)
        except KeyboardInterrupt:
            pass
        return

    if changes:
        try:
            save_role(args.role, changes)
        except ValueError as error:
            parser.error(str(error))

    roles = common.load_config()["agents"]["roles"]
    selected_roles = [args.role] if args.role else roles
    for name in selected_roles:
        role = roles[name]
        print(
            f"{name}: {role['provider']} / {role['model'] or '(default)'} "
            f"(effort: {role['effort']}, enabled: {role['enabled']})"
        )


if __name__ == "__main__":
    main()
