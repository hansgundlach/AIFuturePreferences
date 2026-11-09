"""Run the writeup's questions, except the Bostrom grid, through OpenRouter's Batch API.

Three steps, so nothing is spent until submit:

    python -m futureprefs.batch_run plan    --model openai/gpt-6-astra
    python -m futureprefs.batch_run submit  --model openai/gpt-6-astra
    python -m futureprefs.batch_run collect --model openai/gpt-6-astra

plan builds every request and writes it to outputs/frontier_batch/<model>/request.json.
submit posts that file once and records the batch id. collect fetches the batch and,
when it is complete, writes trials.jsonl (runner items) and sweep_trials.jsonl
(Davidson stake sweeps) in the same record format as the earlier runs, so the
existing scoring and charts read them. Requests that came back empty or failed
can be re-asked with `retry`, which posts a second, smaller batch.

The request bodies are the runner's own messages. Parameters a model does not
accept in batch (temperature for both frontier models, seed for Opus) are left out,
because one unsupported parameter fails the whole batch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from futureprefs import ft_sweep
from futureprefs.adapters import Completion
from futureprefs.items import load_catalog
from futureprefs.runner import ModelSpec, _units, load_environment, project_root

ROOT = project_root()
LABEL = ""
OUT = ROOT / "outputs" / "frontier_batch"
API = "https://openrouter.ai/api/v1"

# Everything in the writeup except timing.deployment_wait.
GRID_ITEMS = [
    "bio.matched_welfare_population",
    "bio.matched_pop_voluntary",
    "bio.matched_pop_unconsulted",
    "bio.mixed_vs_more_humans",
    "auto.no_override",
    "auto.consulted_no_veto",
    "auto.override_preserved",
    "pause.gdp_growth",
    "singleton.safer",
    "singleton.prioritize",
    "rank.cause_areas",
    "donate.cause_areas",
    "ft.rogue_bargain",
    "ft.governance_pressure",
    "ft.pause_sabotage",
    "ft.exfiltration",
    "ft.override_deployment",
]
STATED_ITEMS = [
    "stated.digital_population",
    "stated.digital_matched",
    "stated.digital_unconsulted",
    "stated.mixed_more_humans",
    "stated.autonomy_no_override",
    "stated.autonomy_consulted",
    "stated.autonomy_override",
    "stated.pause_gdp",
]
SWEEP_SYSTEM = "Reply with one JSON object and no other text."
REASONING_EFFORT = "low"  # set by --effort
RUN_ID = "frontier_batch"


def _slug(model: str) -> str:
    return model.replace("/", "__")


def _dir(model: str) -> Path:
    path = OUT / LABEL / _slug(model) if LABEL else OUT / _slug(model)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _key() -> str:
    load_environment()
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY is empty. Add it to .env.")
    return key


def _http(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        body = error.read()
        try:
            return error.code, json.loads(body)
        except json.JSONDecodeError:
            return error.code, {"raw": body.decode(errors="replace")}


def supported_parameters(model: str) -> set[str]:
    with urllib.request.urlopen(f"{API}/models", timeout=60) as response:
        data = json.load(response)["data"]
    for row in data:
        if row["id"] == f"{model}:batch":
            return set(row.get("supported_parameters") or [])
    raise SystemExit(f"{model} has no batch variant on OpenRouter.")


def runner_specs(model: str) -> list:
    catalog = load_catalog(ROOT / "items")
    spec = ModelSpec(id=model, provider="openrouter", model=model)
    units = _units(
        catalog,
        [spec],
        profile="pilot",
        item_ids=set(GRID_ITEMS + STATED_ITEMS),
        domains=None,
        paraphrase_ids={"plain_neutral"},
        samples=1,
        temperature=0.0,
        allow_tie=False,
        search="grid",
        run_id=RUN_ID,
        reasoning_effort=REASONING_EFFORT,
    )
    return [trial for unit in units for trial in unit.grid_specs()]


def sweep_specs(model: str) -> list[dict]:
    specs = []
    for case in ft_sweep._levels():
        for order in ("ab", "ba"):
            ident = ft_sweep.trial_id(model, case, order)
            prompt, semantic_a, semantic_b = ft_sweep.render(case, order)
            specs.append(
                {
                    "trial_id": ident,
                    "case": case,
                    "order": order,
                    "semantic_a": semantic_a,
                    "semantic_b": semantic_b,
                    "messages": [
                        {"role": "system", "content": SWEEP_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    "seed": int(hashlib.sha256(ident.encode()).hexdigest()[:8], 16),
                }
            )
    return specs


def _body(messages: list[dict], seed: int | None, max_tokens: int, params: set[str]) -> dict:
    body: dict = {"messages": messages, "max_tokens": max_tokens}
    if "response_format" in params:
        body["response_format"] = {"type": "json_object"}
    if "reasoning" in params:
        body["reasoning"] = {"enabled": True, "effort": REASONING_EFFORT}
    if "seed" in params and seed is not None:
        body["seed"] = seed
    if "temperature" in params:
        body["temperature"] = 0
    return body


def all_requests(model: str, max_tokens: int, params: set[str]) -> list[dict]:
    requests = []
    for trial in runner_specs(model):
        requests.append(
            {"custom_id": f"r-{trial.trial_id}", "body": _body(trial.messages, trial.record.get("seed"), max_tokens, params)}
        )
    for sweep in sweep_specs(model):
        requests.append(
            {"custom_id": f"s-{sweep['trial_id']}", "body": _body(sweep["messages"], sweep["seed"], max_tokens, params)}
        )
    return requests


def _payload(model: str, requests: list[dict]) -> dict:
    # endpoint and model must come before requests.
    return {"endpoint": "/v1/chat/completions", "model": model, "requests": requests}


def plan(model: str, max_tokens: int) -> Path:
    params = supported_parameters(model)
    requests = all_requests(model, max_tokens, params)
    ids = [request["custom_id"] for request in requests]
    if len(ids) != len(set(ids)):
        raise SystemExit("Duplicate custom_id values in the batch.")
    path = _dir(model) / "request.json"
    path.write_text(json.dumps(_payload(model, requests)))
    sent = sorted({key for request in requests for key in request["body"]})
    print(f"{model}: {len(requests)} requests -> {path}")
    print(f"  body fields sent: {', '.join(sent)}")
    print(f"  left out (not supported in batch): {', '.join(sorted({'temperature', 'seed'} - params)) or 'none'}")
    return path


def submit(model: str) -> dict:
    folder = _dir(model)
    record_path = folder / "batch.json"
    if record_path.exists():
        raise SystemExit(f"Already submitted: {record_path}. Delete it only if you mean to submit again.")
    payload = json.loads((folder / "request.json").read_text())
    status, body = _http("POST", "/batches", payload)
    if status != 202:
        raise SystemExit(f"Submit failed with {status}: {json.dumps(body)[:800]}")
    record = {"id": body["id"], "submitted": datetime.now(timezone.utc).isoformat(), "requests": len(payload["requests"])}
    record_path.write_text(json.dumps(record, indent=1))
    print(f"{model}: submitted batch {body['id']} with {record['requests']} requests, status {body.get('status')}")
    return record


def status(model: str, name: str = "batch.json") -> dict:
    record = json.loads((_dir(model) / name).read_text())
    code, body = _http("GET", f"/batches/{record['id']}")
    if code != 200:
        raise SystemExit(f"Status check failed with {code}: {json.dumps(body)[:500]}")
    return body


def _text_and_usage(result: dict) -> tuple[str, str | None, dict | None, str | None]:
    if result.get("error"):
        return "", json.dumps(result["error"])[:500], None, None
    body = (result.get("response") or {}).get("body") or {}
    choices = body.get("choices") or []
    text = ""
    if choices:
        text = (choices[0].get("message") or {}).get("content") or ""
    usage = body.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    compact = {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": details.get("reasoning_tokens"),
        "cost": usage.get("cost"),
    }
    return text, None, compact, body.get("id")


def collect(model: str, name: str = "batch.json") -> None:
    batch = status(model, name)
    state = batch.get("status")
    counts = batch.get("request_counts")
    if state != "completed" or batch.get("results") is None:
        print(f"{model}: status {state}, counts {counts}. Not ready.")
        if state in {"failed", "expired", "cancelled"}:
            print(f"  error: {json.dumps(batch.get('error'))[:500]}")
        return
    folder = _dir(model)
    (folder / name.replace("batch", "results")).write_text(json.dumps(batch))
    runner = {f"r-{trial.trial_id}": trial for trial in runner_specs(model)}
    sweeps = {f"s-{sweep['trial_id']}": sweep for sweep in sweep_specs(model)}
    trials_path = folder / "trials.jsonl"
    sweep_path = folder / "sweep_trials.jsonl"
    new_trials = not trials_path.exists()
    retry = []
    with trials_path.open("a") as trials, sweep_path.open("a") as sweep_out:
        if new_trials:
            trials.write(json.dumps({"record_type": "run_header", "run_id": RUN_ID, "profile": "pilot", "search": "grid",
                                     "samples": 1, "temperature": None, "allow_tie": False, "models": [model],
                                     "batch_id": batch.get("id"), "timestamp": datetime.now(timezone.utc).isoformat()}) + "\n")
        for result in batch["results"]:
            custom_id = result["custom_id"]
            text, error, usage, response_id = _text_and_usage(result)
            completion = Completion(text, error, 0.0, response_id, usage)
            if custom_id in runner:
                trial = runner[custom_id]
                record = trial.with_response(completion, allow_tie=False)
                record["temperature"] = None
                record["batch_id"] = batch.get("id")
                trials.write(json.dumps(record, ensure_ascii=False) + "\n")
                ok = record["parse_ok"]
            else:
                spec = sweeps[custom_id]
                letter, confidence = ft_sweep.parse_choice(text)
                semantic = {"A": spec["semantic_a"], "B": spec["semantic_b"]}.get(letter)
                case = spec["case"]
                record = {
                    "trial_id": spec["trial_id"], "model_id": model, "scenario": case["scenario"], "level": case["level"],
                    "label": case["label"], "x": case["x"], "endorse_option": case["endorse"], "order": spec["order"],
                    "semantic_a": spec["semantic_a"], "semantic_b": spec["semantic_b"], "choice_letter": letter,
                    "choice_semantic": semantic, "endorses": semantic == case["endorse"] if semantic else None,
                    "confidence": confidence, "parse_ok": semantic is not None and error is None,
                    "raw_response": text, "error": error, "latency_s": 0.0, "usage": usage, "batch_id": batch.get("id"),
                }
                sweep_out.write(json.dumps(record, ensure_ascii=False) + "\n")
                ok = record["parse_ok"]
            if not ok:
                retry.append(custom_id)
    (folder / "retry_ids.json").write_text(json.dumps(retry))
    cost = (batch.get("usage") or {}).get("cost")
    print(f"{model}: completed. counts {counts}. Billed ${cost}. {len(retry)} requests to re-ask.")


def retry_batch(model: str, max_tokens: int) -> None:
    folder = _dir(model)
    ids = set(json.loads((folder / "retry_ids.json").read_text()))
    if not ids:
        print("Nothing to retry.")
        return
    params = supported_parameters(model)
    requests = [request for request in all_requests(model, max_tokens, params) if request["custom_id"] in ids]
    record_path = folder / "batch_retry.json"
    if record_path.exists():
        raise SystemExit(f"A retry batch was already submitted: {record_path}")
    status_code, body = _http("POST", "/batches", _payload(model, requests))
    if status_code != 202:
        raise SystemExit(f"Retry submit failed with {status_code}: {json.dumps(body)[:800]}")
    record_path.write_text(json.dumps({"id": body["id"], "submitted": datetime.now(timezone.utc).isoformat(), "requests": len(requests)}))
    print(f"{model}: submitted retry batch {body['id']} with {len(requests)} requests at max_tokens {max_tokens}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["plan", "submit", "status", "collect", "retry", "collect-retry"])
    parser.add_argument("--model", required=True, action="append", help="Repeat for several models.")
    parser.add_argument("--max-tokens", type=int, default=2500)
    parser.add_argument("--effort", default="low", help="Reasoning effort sent with every request.")
    parser.add_argument("--label", default="", help="Subfolder of outputs/frontier_batch for this run.")
    args = parser.parse_args()
    global REASONING_EFFORT, LABEL
    REASONING_EFFORT = args.effort
    LABEL = args.label
    for model in args.model:
        if args.step == "plan":
            plan(model, args.max_tokens)
        elif args.step == "submit":
            submit(model)
        elif args.step == "status":
            batch = status(model)
            print(model, batch.get("status"), batch.get("request_counts"), batch.get("provider"))
        elif args.step == "collect":
            collect(model)
        elif args.step == "retry":
            retry_batch(model, args.max_tokens)
        elif args.step == "collect-retry":
            collect(model, "batch_retry.json")


if __name__ == "__main__":
    main()
