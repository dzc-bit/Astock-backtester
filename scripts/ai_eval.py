"""Offline evaluation harness for the AI strategy generator.

Two modes:

1. Baseline (default): validates that every expected DSL expression in
   ``ai_eval_cases.json`` is accepted by ``condition_parser``.  This guards the
   eval set itself and documents the target grammar.
2. ``--use-llm``: reads the configured provider from 运行产物/AI配置, asks the
   model to translate each natural-language instruction into the DSL JSON
   shape the ``validate_strategy_conditions`` tool expects, then scores exact
   template acceptance locally.  Never runs in CI; requires a configured key.

Usage (repo root):

    python scripts/ai_eval.py
    python scripts/ai_eval.py --use-llm
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from astock_backtester.condition_parser import validate_condition_text, validate_exit_condition_text  # noqa: E402

CASES_PATH = Path(__file__).resolve().parent / "ai_eval_cases.json"

GENERATOR_INSTRUCTION = """你是 A 股策略条件翻译器。把用户指令翻译成本工作台的条件 DSL。
只输出 JSON：{{"entry_expressions": ["..."], "exit_expressions": ["..."]}}。
每条必须逐字符合以下模板之一：
入场：收盘价站上N日均线 / 量比N日介于A到B / 流通市值X到Y(万|亿) / 换手率A%到B% /
近N日涨幅介于A%到B% / 近N日涨幅小于X% / 近N日主力净流入大于X(万|亿) /
近N日主力净流出大于X(万|亿) / 突破N日新高 / MACD柱线大于X / 市场上涨家数占比大于N% /
收盘价跌破N日均线
离场：收盘价跌破N日均线 / 近N日涨幅小于X% / MACD死叉 / 资金流出 /
近N日主力净流出大于X(万|亿) / 跌破N日低点 / 创N日新低

用户指令：{instruction}"""


def load_cases() -> list[dict]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def expressions_valid(case: dict) -> list[str]:
    problems: list[str] = []
    for text in case.get("expected_entry", []):
        result = validate_condition_text(text)
        if not result.ok:
            problems.append(f"入场条件不可执行：{text}")
    for text in case.get("expected_exit", []):
        result = validate_exit_condition_text(text)
        if not result.ok:
            problems.append(f"离场条件不可执行：{text}")
    return problems


def translate_with_llm(instruction: str, cache_dir: str) -> dict:
    from astock_backtester.ai.config import AiConfigStore, ai_base_dir_from_cache_dir
    from astock_backtester.ai.llm_client import OpenAiCompatibleClient

    store = AiConfigStore(ai_base_dir_from_cache_dir(cache_dir))
    config = store.load()
    if not config.is_configured():
        raise SystemExit(
            "AI 未配置：默认读取 <仓库>/运行产物/AI配置/ai-config.json，"
            "可用 --cache-dir 指定数据仓目录，或先在桌面端设置里完成配置。"
        )
    client = OpenAiCompatibleClient(lambda: config)
    content = ""
    for event in client.chat(
        [
            {"role": "system", "content": "你是严格的 JSON 输出器，除 JSON 外不输出任何文字。"},
            {"role": "user", "content": GENERATOR_INSTRUCTION.format(instruction=instruction)},
        ],
        tools=None,
    ):
        if event[0] == "final":
            content = str(event[1].get("content") or "")
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        return json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return {}


def validate_generated(generated: dict) -> list[str]:
    problems: list[str] = []
    for text in generated.get("entry_expressions", []):
        result = validate_condition_text(str(text))
        if not result.ok:
            problems.append(f"生成的入场条件不可执行：{text}（{result.errors[0].message if result.errors else ''}）")
    for text in generated.get("exit_expressions", []):
        result = validate_exit_condition_text(str(text))
        if not result.ok:
            problems.append(f"生成的离场条件不可执行：{text}（{result.errors[0].message if result.errors else ''}）")
    if not generated.get("entry_expressions"):
        problems.append("模型没有生成任何入场条件")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="AI 策略生成评测")
    parser.add_argument("--use-llm", action="store_true", help="调用已配置的模型做 NL→DSL 翻译并评分（不进 CI）")
    parser.add_argument(
        "--cache-dir",
        default=str(Path(__file__).resolve().parents[1] / "运行产物" / "本地数据仓"),
        help="数据仓目录（AI 配置按其父目录解析），默认为仓库内的 运行产物/本地数据仓",
    )
    args = parser.parse_args()

    cases = load_cases()
    if not args.use_llm:
        failures = 0
        for case in cases:
            problems = expressions_valid(case)
            if problems:
                failures += 1
                print(f"[FAIL] {case['id']}: {problems}")
        print(f"基线校验：{len(cases) - failures}/{len(cases)} 条用例的期望 DSL 全部可执行。")
        return 1 if failures else 0

    passed = 0
    for case in cases:
        generated = translate_with_llm(case["instruction"], args.cache_dir)
        problems = validate_generated(generated)
        if problems:
            print(f"[FAIL] {case['id']}: {problems}")
        else:
            passed += 1
            print(f"[PASS] {case['id']}: {generated.get('entry_expressions')} / {generated.get('exit_expressions')}")
    print(f"LLM 评测：{passed}/{len(cases)} 条指令翻译为可执行 DSL。")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
