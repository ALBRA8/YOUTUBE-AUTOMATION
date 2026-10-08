"""
HANDS · Target Identification — jerarquía de identificación (§8).

Orden canónico (más robusto primero):

  1. SEMANTIC       — identificador semántico estable
  2. ACCESSIBILITY  — accessibility/UI identifier
  3. TEXT           — texto visible
  4. DOM            — selector DOM cuando aplique
  5. VISUAL         — referencia visual cuando aplique
  6. COORDINATES    — ÚLTIMO RECURSO: solo si el target declara coords Y la
                      política global allow_coordinate_fallback=True (§7/§28)

El resolver itera la jerarquía sobre la Observación y devuelve el PRIMER
match (TargetMatch con estrategia usada + ref del elemento). Sin match →
TargetNotFoundError con la lista de estrategias probadas (diagnóstico, §29).

La implementación puede evolucionar (p.ej. OCR/template matching en VISUAL)
sin romper el contrato: TargetSpec/TargetMatch son estables.
"""
from __future__ import annotations

from typing import Any

from .contracts import (Observation, PermissionDeniedError, TargetMatch,
                        TargetNotFoundError, TargetSpec, TargetStrategy,
                        TARGET_STRATEGY_ORDER)


class TargetResolver:
    """Resuelve TargetSpec sobre una Observation con la jerarquía §8."""

    def __init__(self, *, allow_coordinate_fallback: bool = False):
        self.allow_coordinate_fallback = allow_coordinate_fallback

    def resolve(self, spec: TargetSpec, observation: Observation) -> TargetMatch:
        """Primer match según la jerarquía; TargetNotFoundError si nada."""
        tried: list[dict[str, Any]] = []
        strategies = [s for s in TARGET_STRATEGY_ORDER
                      if s is not TargetStrategy.COORDINATES]
        for strategy in strategies:
            match = self._try_strategy(strategy, spec, observation)
            tried.append({"strategy": strategy.value, "matched": match is not None})
            if match is not None:
                match.detail["tried"] = tried
                return match

        # coordenadas: último recurso, bajo política explícita (§8)
        if spec.coords is not None:
            if not self.allow_coordinate_fallback:
                raise PermissionDeniedError(
                    "coordenadas deshabilitadas por política "
                    "(allow_coordinate_fallback=False) — fallback §8 vetado",
                    details={"category": "browser",
                             "tried": tried})
            match = TargetMatch(strategy=TargetStrategy.COORDINATES,
                                value=spec.coords,
                                detail={"tried": tried})
            return match

        raise TargetNotFoundError(
            "target no identificado en la observación "
            f"(estrategias probadas: {[t['strategy'] for t in tried]})",
            details={"target": spec.to_dict(), "tried": tried,
                     "elements_seen": len(observation.elements)},
        )

    # ── estrategias ──────────────────────────────────────────────────────
    def _try_strategy(self, strategy: TargetStrategy, spec: TargetSpec,
                      observation: Observation) -> TargetMatch | None:
        spec_value = getattr(spec, strategy.value, None)
        if spec_value is None:
            return None

        def field_matches(el, field_name: str, value: Any) -> bool:
            actual = getattr(el, field_name, None)
            if actual is None:
                return False
            if strategy is TargetStrategy.TEXT:
                # texto visible: match por contención (la UI añade espacios)
                return str(value).lower() in str(actual).lower()
            return actual == value

        if strategy is TargetStrategy.VISUAL:
            # visual: referencia declarativa — matchea elementos con visual
            # compatible (por región declarada); evolución futura: OCR/templates
            def visual_pred(el) -> bool:
                if el.visual is None or spec_value is None:
                    return False
                region = spec_value.get("region") if isinstance(spec_value, dict) else None
                return region is not None and el.visual.get("region") == region

            el = observation.find_element(visual_pred)
            if el is None:
                return None
            return TargetMatch(strategy=strategy, value=spec_value,
                               element_ref=el.ref_id)

        field_name = strategy.value
        el = observation.find_element(
            lambda e: field_matches(e, field_name, spec_value))
        if el is None:
            return None
        return TargetMatch(strategy=strategy, value=spec_value,
                           element_ref=el.ref_id,
                           detail={"element": el.to_dict()})
