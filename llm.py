"""プロバイダ切り替えクライアント。

ai& は Anthropic 互換 API (https://api.aiand.com) なので、anthropic SDK の base_url を
差し替えるだけで Claude とオープンモデルを同じコードで呼べる。

model の指定形式:
  "anthropic:claude-opus-5-5"
  "aiand:zai-org/glm-5.3-flash"
  "mock:any"   ← APIキーなしでパイプライン確認用
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass

import anthropic
from dotenv import load_dotenv

load_dotenv()

# $ / 1M tokens (input, output)。ai& は GET https://api.aiand.com/v1/models の値 (2026-11-17 時点)
PRICES: dict[str, tuple[float, float]] = {
    "anthropic:claude-opus-5-5": (4.00, 20.00),
    "anthropic:claude-sonnet-5-5": (2.00, 10.00),
    "anthropic:claude-haiku-5-5": (0.10, 0.50),
    "aiand:moonshotai/kimi-k3.1-pro": (2.00, 10.00),
    "aiand:moonshotai/kimi-k3": (3.00, 12.50),
    "aiand:deepseek-ai/deepseek-v4-pro": (1.00, 2.50),
    "aiand:deepseek-ai/deepseek-v4.1-flash-1017": (0.30, 0.60),
    "aiand:zai-org/glm-5.3": (1.00, 4.00),
    "aiand:zai-org/glm-5.3-flash": (0.15, 0.50),
    "aiand:google/gemma-4-31b-it": (0.20, 0.50),
    "aiand:qwen/qwen3.8-27b": (0.40, 3.00),
    "aiand:openai/gpt-oss-120b": (0.15, 0.60),
}


@dataclass
class Result:
    text: str
    input_tokens: int
    output_tokens: int
    cost: float
    latency: float


_clients: dict[str, anthropic.Anthropic] = {}


def _client(provider: str) -> anthropic.Anthropic:
    if provider not in _clients:
        if provider == "aiand":
            _clients[provider] = anthropic.Anthropic(
                base_url="https://api.aiand.com",
                api_key=os.environ["AIAND_API_KEY"],
            )
        elif provider == "anthropic":
            _clients[provider] = anthropic.Anthropic()  # ANTHROPIC_API_KEY を使う
        else:
            raise ValueError(f"unknown provider: {provider}")
    return _clients[provider]


def call(model: str, system: str, user: str, max_tokens: int = 2048) -> Result:
    provider, name = model.split(":", 1)
    t0 = time.time()

    if provider == "mock":
        label = random.choice(["要返信", "返信不要"])
        text = f'{{"label": "{label}", "reason": "mock"}}'
        return Result(text, 0, 0, 0.0, time.time() - t0)

    kwargs: dict = dict(
        model=name,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    if provider == "anthropic":
        # Opus 5.5 は thinking を切れないので effort を下げて分類向けに軽くする
        kwargs["output_config"] = {"effort": "low"}

    resp = _client(provider).messages.create(**kwargs)
    text = "".join(b.text for b in resp.content if b.type == "text")
    inp, out = resp.usage.input_tokens, resp.usage.output_tokens
    pin, pout = PRICES.get(model, (0.0, 0.0))
    cost = (inp * pin + out * pout) / 1_000_000
    return Result(text, inp, out, cost, time.time() - t0)
