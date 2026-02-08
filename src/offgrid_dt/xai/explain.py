from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from offgrid_dt.io.schema import Guidance, SystemConfig


@dataclass
class ExplanationContext:
    soc: float
    pv_now_kw: float
    pv_avg_next2h_kw: float
    critical_kw: float


def generate_guidance(cfg: SystemConfig, ctx: ExplanationContext, used_kw: float, deferred_count: int) -> Guidance:
    reason_codes: List[str] = []
    factors: Dict[str, float] = {"soc": ctx.soc, "pv_now_kw": ctx.pv_now_kw, "pv_avg_next2h_kw": ctx.pv_avg_next2h_kw}

    risk = "low"
    if ctx.soc <= cfg.soc_min + 0.05:
        risk = "high"
        reason_codes.append("LOW_SOC")
    elif ctx.soc <= cfg.soc_min + 0.12:
        risk = "medium"
        reason_codes.append("MID_SOC")

    if ctx.pv_avg_next2h_kw < 0.25 * cfg.pv_capacity_kw:
        reason_codes.append("LOW_PV_FORECAST")
        risk = "high" if risk == "medium" else risk

    if ctx.pv_now_kw > ctx.critical_kw + 0.5:
        reason_codes.append("PV_SURPLUS")

    if deferred_count > 0:
        reason_codes.append("DEFER_TASKS")

    # Headline policy (day-ahead aware: do not say "conditions good" when solar is limited or risk is high)
    if "LOW_SOC" in reason_codes and "LOW_PV_FORECAST" in reason_codes:
        headline = "Conserve: protect battery reserve"
        explanation = "Battery reserve is low and day-ahead solar is expected to stay limited. Delay heavy and non-essential tasks; use surplus windows when solar is available."
    elif "PV_SURPLUS" in reason_codes:
        headline = "Use surplus window for heavy tasks"
        explanation = "Solar is strong in this window. Run high-power tasks during surplus periods to reduce battery discharge."
    elif deferred_count > 0:
        headline = "Shift non-critical tasks"
        explanation = "Some tasks are deferred to keep essential loads reliable. Run them in surplus windows when solar improves or SOC rises."
    elif "LOW_PV_FORECAST" in reason_codes or risk in ("high", "medium"):
        headline = "Day-ahead solar limited"
        explanation = "Expected solar for the day is limited. Use flexible appliances only in surplus windows when solar is available; prioritise essentials."
    else:
        headline = "Day-ahead outlook adequate"
        explanation = "Day-ahead energy margin is sufficient. You can use flexible appliances within the recommended surplus windows." 

    return Guidance(
        headline=headline,
        explanation=explanation,
        risk_level=risk,
        confidence=0.75,
        reason_codes=reason_codes,
        dominant_factors=factors,
    )


def enhance_explanation_with_openai(
    api_key: Optional[str],
    model: str,
    guidance: Guidance,
    household_context: str = "",
) -> Guidance:
    """Optionally rewrite the explanation using OpenAI for better readability.

    Security:
    - Only uses the provided API key at runtime (Streamlit secrets)
    - Sends only non-sensitive context (no keys, no PII)
    """
    if not api_key:
        return guidance

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        prompt = (
            "Rewrite the following household energy guidance into a short, plain-language explanation. "
            "Keep it under 2 sentences. Keep it actionable. Do not mention 'AI'.\n\n"
            f"Headline: {guidance.headline}\n"
            f"Reason codes: {', '.join(guidance.reason_codes)}\n"
            f"Context: {household_context}\n"
            f"Draft: {guidance.explanation}"
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        text = resp.choices[0].message.content.strip()
        if text:
            return Guidance(
                headline=guidance.headline,
                explanation=text,
                risk_level=guidance.risk_level,
                confidence=guidance.confidence,
                reason_codes=guidance.reason_codes,
                dominant_factors=guidance.dominant_factors,
            )
        return guidance
    except Exception:
        return guidance
