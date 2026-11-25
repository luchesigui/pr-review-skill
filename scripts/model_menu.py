"""Terminal picker for review role providers and models."""
import curses
import shutil

import common
import model_catalog


def choose(screen, title, options, selected=0, footer=""):
    while True:
        screen.erase()
        height, width = screen.getmaxyx()
        if height >= 5 and width >= 12:
            visible = height - 4
            start = max(0, selected - visible + 1)
            screen.addnstr(0, 0, title, width - 1, curses.A_BOLD)
            for row, label in enumerate(options[start:start + visible], start=2):
                highlight = curses.A_REVERSE if row - 2 + start == selected else curses.A_NORMAL
                screen.addnstr(row, 0, label, width - 1, highlight)
            screen.addnstr(height - 2, 0, footer, width - 1)
            screen.addnstr(height - 1, 0, "Up/Down to move  Enter to select  Esc to go back", width - 1)
        key = screen.getch()
        if key in (curses.KEY_UP, ord("k")):
            selected = (selected - 1) % len(options)
        elif key in (curses.KEY_DOWN, ord("j")):
            selected = (selected + 1) % len(options)
        elif key in (10, 13, curses.KEY_ENTER):
            return selected
        elif key in (27, curses.KEY_LEFT):
            return None


def edit_role(screen, name, role, custom_providers, catalogs, save_role):
    providers = list(dict.fromkeys([
        role["provider"], "native",
        *(name for name in model_catalog.PROVIDERS if shutil.which(name)),
        *custom_providers,
    ]))
    provider_index = 0
    while True:
        choice = choose(screen, f"{name} / Provider", providers, provider_index)
        if choice is None:
            return ""
        provider_index = choice
        provider = providers[choice]
        if provider in model_catalog.PROVIDERS and provider not in catalogs:
            screen.erase()
            screen.addnstr(0, 0, f"Loading {provider} models...", screen.getmaxyx()[1] - 1)
            screen.refresh()
            catalogs[provider] = model_catalog.discover(provider)

        catalog = catalogs.get(provider, {"source": "unavailable", "models": []})
        current_model = role["model"] or ""
        models = ["", *catalog["models"]]
        if provider == role["provider"] and current_model not in models:
            models.insert(1, current_model)
        labels = [model or "Provider default" for model in models] + ["Enter a model ID"]
        model_index = models.index(current_model) if provider == role["provider"] else 0
        while True:
            choice = choose(screen, f"{name} / {provider} / Model", labels, model_index,
                            catalog["source"])
            if choice is None:
                break
            model_index = choice
            if choice == len(models):
                screen.erase()
                screen.addnstr(0, 0, "Model ID (blank to go back): ", screen.getmaxyx()[1] - 1)
                curses.echo()
                try:
                    model = screen.getstr(1, 0, max(1, screen.getmaxyx()[1] - 1)).decode().strip()
                finally:
                    curses.noecho()
                if not model:
                    continue
            else:
                model = models[choice]

            confirmation = choose(
                screen, f"{name} / {provider} / {model or 'Provider default'}",
                ["Save selection", "Back to models"],
            )
            if confirmation == 0:
                save_role(name, {"provider": provider, "model": model})
                return f"Saved {name}"


def run(save_role):
    def menu(screen):
        curses.set_escdelay(50)
        catalogs = {}
        selected = 0
        status = ""
        while True:
            agents = common.load_config()["agents"]
            roles = list(agents["roles"])
            options = [
                f"{name}  {role['provider']} / {role['model'] or 'default'}"
                for name, role in agents["roles"].items()
            ]
            choice = choose(screen, "PR review models / Role", options + ["Exit"], selected, status)
            if choice is None or choice == len(roles):
                return
            selected = choice
            name = roles[choice]
            status = edit_role(screen, name, agents["roles"][name],
                               agents.get("custom_commands", {}), catalogs, save_role)

    curses.wrapper(menu)
