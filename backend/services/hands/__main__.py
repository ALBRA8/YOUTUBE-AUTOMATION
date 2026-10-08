#!/usr/bin/env python3
"""CLI de HANDS — python3 -m services.hands <modo>

Modos:
  info       — estado de la capa (versión, integración NOT CONNECTED, módulos)
  selfaudit  — auditoría automática §40 (informe completo)
  cleanroom  — validación clean-room §42 (guion completo con mocks)

Uso (desde la raíz del repo o con backend en sys.path):
  cd yt_automation_v2 && python3 -m services.hands selfaudit
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.hands import HANDS_VERSION, INTEGRATION_STATUS           # noqa: E402
from services.hands import cleanroom as _cleanroom                     # noqa: E402
from services.hands import selfaudit as _selfaudit                     # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(prog="services.hands",
                                     description="HANDS V1.0 (capa aislada)")
    parser.add_argument("mode", choices=["info", "selfaudit", "cleanroom"])
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    if args.mode == "info":
        info = {
            "name": "HANDS",
            "version": HANDS_VERSION,
            "integration_status": INTEGRATION_STATUS,
            "maturity": {
                "contracts/permissions/workspace/evidence/sessions/locks/"
                "killswitch/waits/verification/recovery/identify/engine": "TESTED",
                "desktop_operator(mock)": "TESTED",
                "flow_operator(mock)": "TESTED",
                "bridge_adapter(contrato real)": "TESTED (HTTP simulado) · "
                                                 "REAL: NOT_VERIFIED",
                "desktop_físico": "NOT_VERIFIED (requiere PC real + consentimiento)",
            },
        }
        if args.as_json:
            print(json.dumps(info, indent=1, ensure_ascii=False))
        else:
            for key, value in info.items():
                print(f"{key}: {value}")
        return 0

    if args.mode == "selfaudit":
        report = _selfaudit.run_selfaudit()
        if args.as_json:
            print(json.dumps(report, indent=1, ensure_ascii=False))
            return 0 if report["ok"] else 1
        return _selfaudit.print_selfaudit(report)

    # cleanroom
    report = _cleanroom.run_cleanroom(verbose=not args.as_json)
    if args.as_json:
        print(json.dumps(report, indent=1, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
