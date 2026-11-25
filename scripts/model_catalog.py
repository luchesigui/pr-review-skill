"""List model choices from the selected review providers."""
import argparse
import json
import os
import re
import selectors
import shutil
import subprocess
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PROVIDERS = ("claude", "codex", "grok", "gemini", "agy")
TIMEOUT = 12


def cli_output(command, request=None):
    return subprocess.run(
        command, input=request or "", capture_output=True, text=True,
        timeout=TIMEOUT, check=True,
    ).stdout


def claude_models():
    request = {"type": "control_request", "request_id": "models",
               "request": {"subtype": "initialize"}}
    output = cli_output(
        ["claude", "-p", "--input-format", "stream-json", "--output-format",
         "stream-json", "--verbose", "--no-session-persistence", "--strict-mcp-config",
         "--disable-slash-commands"],
        json.dumps(request) + "\n",
    )
    for line in output.splitlines():
        message = json.loads(line)
        response = message.get("response", {})
        if response.get("request_id") == "models":
            return [item["value"] for item in response["response"]["models"]
                    if item["value"] != "default"]
    return []


def codex_models():
    # Keep stdin open until the asynchronous model/list reply arrives.
    with subprocess.Popen(
        ["codex", "app-server", "--listen", "stdio://"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    ) as process, selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + TIMEOUT
        pending = b""

        def send(message):
            process.stdin.write(json.dumps(message).encode() + b"\n")
            process.stdin.flush()

        def receive(request_id):
            nonlocal pending
            while time.monotonic() < deadline:
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    message = json.loads(line)
                    if message.get("id") == request_id:
                        return message["result"]
                if not selector.select(max(0, deadline - time.monotonic())):
                    break
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                pending += chunk
            raise TimeoutError("Codex catalog did not respond")

        try:
            send({"id": 0, "method": "initialize", "params": {
                "clientInfo": {"name": "review-pr", "version": "1.0"}}})
            receive(0)
            send({"method": "initialized"})
            models = []
            cursor = None
            request_id = 1
            while True:
                send({"id": request_id, "method": "model/list",
                      "params": {"cursor": cursor} if cursor else {}})
                page = receive(request_id)
                models.extend(item["model"] for item in page["data"])
                cursor = page.get("nextCursor")
                if not cursor:
                    return models
                request_id += 1
        finally:
            process.terminate()


def grok_models():
    output = cli_output(["grok", "models"])
    _, _, entries = output.partition("Available models:")
    return re.findall(r"^\s*[*-]\s+([\w.:-]+)", entries, re.MULTILINE)


def agy_models():
    return re.findall(r"^([\w.:-]+)\t[^\n]+$", cli_output(["agy", "models"]), re.MULTILINE)


def api_page(url, headers, params):
    request = Request(url + "?" + urlencode(params), headers=headers)
    with urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


def api_models(provider):
    if provider == "claude":
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return []
        page = api_page("https://api.anthropic.com/v1/models",
                        {"x-api-key": key, "anthropic-version": "2026-10-21"},
                        {"limit": 1000, "lifecycle": "active"})
        return [item["id"] for item in page["data"]]
    if provider == "grok":
        key = os.environ.get("XAI_API_KEY")
        if not key:
            return []
        page = api_page("https://api.x.ai/v1/language-models",
                        {"Authorization": f"Bearer {key}"}, {})
        return [item["id"] for item in page["models"]]
    if provider == "gemini":
        key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not key:
            return []
        models = []
        params = {"pageSize": 1000}
        while True:
            page = api_page("https://generativelanguage.googleapis.com/v1beta/models",
                            {"x-goog-api-key": key}, params)
            models.extend(item["name"].removeprefix("models/") for item in page["models"]
                          if "generateContent" in item.get("supportedGenerationMethods", []))
            token = page.get("nextPageToken")
            if not token:
                return models
            params["pageToken"] = token
    return []


def discover(provider):
    cli = {"claude": claude_models, "codex": codex_models, "grok": grok_models, "agy": agy_models}
    failures = (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError)
    if provider in cli:
        try:
            if models := cli[provider]():
                return {"source": "CLI catalog", "models": list(dict.fromkeys(models))}
        except failures:
            pass
    try:
        if models := api_models(provider):
            return {"source": "API-key catalog", "models": list(dict.fromkeys(models))}
    except failures:
        pass
    return {"source": "unavailable", "models": []}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--providers", action="store_true", help="List installed provider CLIs")
    mode.add_argument("--catalog", nargs="+", choices=PROVIDERS, metavar="PROVIDER")
    args = parser.parse_args()
    if args.providers:
        result = ["native", *(provider for provider in PROVIDERS if shutil.which(provider))]
    else:
        result = {provider: discover(provider) for provider in dict.fromkeys(args.catalog)}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
