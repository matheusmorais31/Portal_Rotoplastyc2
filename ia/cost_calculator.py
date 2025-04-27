from decimal import Decimal
import logging

logger = logging.getLogger(__name__)

# ==============================================================================
# == PREÇOS DA API GEMINI (USD – Atualizado em 24/04/2025) ==
# ==============================================================================
# Valores oficiais/estimados por **MILHÃO** de tokens (Input / Output)
# Fonte: https://ai.google.dev/gemini-api/docs/pricing (24‑Abr‑2025)

# -----------------------------------------------------------------------------
# Preços por 1 M de Tokens (Input $, Output $)
# -----------------------------------------------------------------------------
GEMINI_PRICING_PER_MILLION_TOKENS = {
    # Gemini 1.5
    "models/gemini-1.5-pro-latest":       (Decimal("3.50"),  Decimal("10.50")),
    "models/gemini-1.5-flash-latest":     (Decimal("0.35"),  Decimal("1.05")),

    # Gemini 2.5 (preview)
    "models/gemini-2.5-pro-preview-03-25": (Decimal("10.00"), Decimal("30.00")),
    "models/gemini-2.5-flash-preview-04-17": (Decimal("0.15"), Decimal("3.50")),  # thinking price
    "models/gemini-2.5-flash": (Decimal("0.15"), Decimal("3.50")),  # alias (sem sufixo)

    # Gemini 2.0
    "models/gemini-2.0-flash-latest":      (Decimal("0.10"),  Decimal("0.40")),
    # Flash‑Lite
    "models/gemini-2.0-flash-lite-latest": (Decimal("0.075"), Decimal("0.30")),
    "models/gemini-2.0-flash-lite":        (Decimal("0.075"), Decimal("0.30")),

    # Legado / exemplo
    "models/gemini-1.0-pro":               (Decimal("0.50"),  Decimal("1.50")),
}

# -----------------------------------------------------------------------------
# Preços por Imagem (entrada) – somente modelos multimodais
# -----------------------------------------------------------------------------
GEMINI_PRICING_PER_IMAGE = {
    "models/gemini-1.5-pro-latest":        Decimal("0.0025"),
    "models/gemini-1.5-flash-latest":      Decimal("0.00025"),

    "models/gemini-2.5-pro-preview-03-25": Decimal("0.0030"),
    "models/gemini-2.5-flash-preview-04-17": Decimal("0.00025"),  # aproximado (igual Flash 2.0)
    "models/gemini-2.5-flash":             Decimal("0.00025"),

    "models/gemini-2.0-flash-latest":      Decimal("0.00025"),

    "models/gemini-2.0-flash-lite-latest": Decimal("0.00000"),
    "models/gemini-2.0-flash-lite":        Decimal("0.00000"),

    "models/gemini-1.0-pro":               Decimal("0.0025"),
}

# -----------------------------------------------------------------------------
DEFAULT_MODEL_FALLBACK = "models/gemini-1.5-flash-latest"


def _normalise_model_name(name: str) -> str | None:
    """Tentativa de encontrar um alias com/sem sufixo “-latest”."""
    if name.endswith("-latest"):
        alt = name.removesuffix("-latest")
    else:
        alt = f"{name}-latest"
    return alt if alt != name else None


def calculate_gemini_cost(model_name: str, input_tokens: int, output_tokens: int, image_count: int) -> Decimal:
    """Retorna o custo estimado (USD) para uma chamada Gemini."""
    million = Decimal("1000000")

    # -- Tokens ------------------------------------------------------
    alt_name = None  # garante existência
    token_prices = GEMINI_PRICING_PER_MILLION_TOKENS.get(model_name)
    if token_prices is None:
        alt_name = _normalise_model_name(model_name)
        if alt_name:
            token_prices = GEMINI_PRICING_PER_MILLION_TOKENS.get(alt_name)

    if token_prices is None:
        logger.warning("Preços de token não encontrados para '%s'. Usando fallback '%s'.", model_name, DEFAULT_MODEL_FALLBACK)
        token_prices = GEMINI_PRICING_PER_MILLION_TOKENS[DEFAULT_MODEL_FALLBACK]

    input_cost  = Decimal(input_tokens)  * (token_prices[0] / million)
    output_cost = Decimal(output_tokens) * (token_prices[1] / million)

    # -- Imagens -----------------------------------------------------
    image_unit_price = GEMINI_PRICING_PER_IMAGE.get(model_name)
    if image_unit_price is None and alt_name:
        image_unit_price = GEMINI_PRICING_PER_IMAGE.get(alt_name)
    if image_unit_price is None:
        image_unit_price = Decimal(0)

    image_cost = Decimal(image_count) * image_unit_price

    return input_cost + output_cost + image_cost
