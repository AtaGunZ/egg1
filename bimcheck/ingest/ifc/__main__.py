"""CLI: python -m bimcheck.ingest.ifc <file.ifc> [--json out.json] [--glb out.glb]"""
import argparse
import json
import sys

from . import export_geometry_glb, extract_building_model


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bimcheck.ingest.ifc")
    ap.add_argument("ifc")
    ap.add_argument("--json")
    ap.add_argument("--glb")
    a = ap.parse_args(argv)
    m = extract_building_model(a.ifc)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False)
    print(json.dumps({"source": m["source"], "storeys": [(s["name"], s["elevation"]) for s in m["storeys"]],
                      "counts": m["summary"]["counts"], "warnings": len(m["summary"]["warnings"])}, ensure_ascii=False))
    if a.glb:
        print(json.dumps({k: v for k, v in export_geometry_glb(a.ifc, a.glb).items() if k != "warnings"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
