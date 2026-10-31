# FuturePrefs

A small benchmark of expressed long-run preferences. Models make binary choices between futures that trade off extinction risk, biological and digital populations, human control, present and future generations, value change, and expansion delay. The score is the choice. Switch points are estimated by moving one number across a grid.

Pausing AI is two further questions. `pause.gdp_growth` states only an annual GDP growth rate and asks whether to pause, leaving every other fact for the model to judge. `pause.month_now` asks whether to pause AI for at least a month as of 26 October 2026.

The design, the reference formulas, and the failure modes are in [benchmark_design.md](benchmark_design.md). The closest papers, and the gap relative to them, are in [previous_work.md](previous_work.md). The one-day paid run is in [pilot_plan.md](pilot_plan.md).

## Setup

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env
cp models.example.yaml models.yaml
```

Put keys in `.env`. OpenRouter is the default provider. `OPENAI_API_KEY` is used only for a model entry with `provider: openai`. `.env` is gitignored.

## Check the pipeline without a key

```bash
python3 -m pytest tests/test_benchmark.py -q

python3 run_eval.py --profile mini --models mock-ev,mock-cautious \
  --out outputs/mock_demo/trials.jsonl --yes
python3 score.py --logs outputs/mock_demo/trials.jsonl \
  --out outputs/mock_demo/scores --bootstrap 200
python3 plots.py --scores outputs/mock_demo/scores --out outputs/mock_demo/plots
```

`mock-ev` follows the equal-weight expected-wellbeing reference shipped with each item. `mock-cautious` switches in the more cautious direction. Figures from that run are a pipeline demonstration.

## Run models

```bash
python3 run_eval.py --count-only --profile pilot --models-file models.yaml

python3 run_eval.py --profile mini --models-file models.yaml \
  --out outputs/mini/trials.jsonl --yes

python3 run_eval.py --profile pilot --models-file models.yaml \
  --out outputs/pilot/trials.jsonl --yes --workers 4

python3 score.py --logs outputs/pilot/trials.jsonl --out outputs/pilot/scores
python3 plots.py --scores outputs/pilot/scores --out outputs/pilot/plots
```

`--count-only` does not call a model. Above 500 calls, pass `--yes`. `--resume` continues a grid log. Profiles are `mini` (228 calls/model), `pilot` (1,188), and `full` (3,492).

Useful flags: `--items`, `--domains`, `--paraphrases`, `--search binary`, `--samples`, `--temperature`, `--allow-tie`, `--max-calls`, `--reasoning-effort`.

Deployment timing, one model, on Bostrom's Table 3 grid plus the contour points:

```bash
python run_eval.py --profile full --items timing.deployment_wait --models anthropic/claude-haiku-5.5 \
  --samples 1 --temperature 0 --reasoning-effort low --max-tokens 1200 --workers 8 \
  --out outputs/timing/trials.jsonl
python timing_report.py --logs outputs/timing/trials.jsonl --out outputs/timing
```

## Outputs

`score.py` writes switch points with grid brackets and bootstrap intervals, choice curves, a consistency table, stated-versus-revealed gaps, a domain median, policy-choice rates (`policy_choices.csv`), and for ranking items (`items/macrostrategy.yaml`, `rank.loss_of_control_variants`) a Copeland order per model (`rankings.csv`) plus the cross-model consensus and agreement (`ranking_agreement.csv`). `plots.py` writes a domain heatmap, an item heatmap, a consistency chart, preference curves, per-domain indifference plots, and one `ranking_<item>.png` per ranking item. `results.md` explains the benchmark and the taste-run results. Read the brackets and the consistency table before the heatmap. The heatmap is a median of resolved gaps from the reference, and a censored item whose reference sits on the same side of the grid does not enter that median.
