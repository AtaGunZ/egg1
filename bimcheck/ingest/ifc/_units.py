"""Unit handling: everything the extractor emits is in metres / square metres / cubic metres."""
from __future__ import annotations

import ifcopenshell
import ifcopenshell.util.unit as uu

_LENGTH_MEASURES = {
    "IfcLengthMeasure", "IfcPositiveLengthMeasure", "IfcNonNegativeLengthMeasure",
}
_AREA_MEASURES = {"IfcAreaMeasure"}
_VOLUME_MEASURES = {"IfcVolumeMeasure"}


class Units:
    """Scale factors from project units to SI (m, m2, m3) plus a human readable length unit name."""

    def __init__(self, ifc: ifcopenshell.file, warnings: list[str]):
        self.length = 1.0
        self.area = 1.0
        self.volume = 1.0
        self.length_name = "METRE"
        self.assumed = False
        try:
            project = (ifc.by_type("IfcProject") or [None])[0]
            ua = project.UnitsInContext if project is not None else None
        except Exception:
            ua = None
        if ua is None:
            warnings.append("no IfcUnitAssignment found: assuming metres (length), square metres, cubic metres")
            self.assumed = True
            return
        have = {}
        for u in ua.Units or []:
            ut = getattr(u, "UnitType", None)
            if ut:
                have[ut] = u
        if "LENGTHUNIT" not in have:
            warnings.append("IfcUnitAssignment has no LENGTHUNIT: assuming metres")
            self.assumed = True
        else:
            try:
                self.length = float(uu.calculate_unit_scale(ifc, "LENGTHUNIT"))
            except Exception as e:  # pragma: no cover - defensive
                warnings.append(f"could not evaluate LENGTHUNIT ({e}): assuming metres")
                self.length = 1.0
                self.assumed = True
            self.length_name = _unit_name(have["LENGTHUNIT"])
        for key, attr in (("AREAUNIT", "area"), ("VOLUMEUNIT", "volume")):
            power = 2 if attr == "area" else 3
            if key in have:
                try:
                    setattr(self, attr, float(uu.calculate_unit_scale(ifc, key)))
                    continue
                except Exception:
                    pass
            # no explicit area/volume unit -> derived from the length unit
            setattr(self, attr, self.length ** power)
        if self.length <= 0:
            self.length = 1.0
        if abs(self.length - 1.0) > 1e-9:
            warnings.append(f"model length unit is {self.length_name} (scale {self.length:g} to m); converted to metres")

    # --- conversions ---------------------------------------------------------------------------
    def convert_measure(self, ifc_type: str | None, value, explicit_unit=None):
        """Convert a typed IFC measure value to SI. Non-dimensional types pass through."""
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            return value
        if explicit_unit is not None:
            try:
                s = float(uu.get_unit_scale(explicit_unit))
                ut = getattr(explicit_unit, "UnitType", None)
                if ut == "LENGTHUNIT" or ut == "AREAUNIT" or ut == "VOLUMEUNIT":
                    return value * s
            except Exception:
                pass
        if ifc_type in _LENGTH_MEASURES:
            return value * self.length
        if ifc_type in _AREA_MEASURES:
            return value * self.area
        if ifc_type in _VOLUME_MEASURES:
            return value * self.volume
        return value


def _unit_name(unit) -> str:
    try:
        if unit.is_a("IfcSIUnit"):
            prefix = (unit.Prefix or "").replace("_", "")
            return f"{prefix}{unit.Name}"
        if unit.is_a("IfcConversionBasedUnit"):
            return str(unit.Name)
        if unit.is_a("IfcDerivedUnit"):
            return "DERIVED"
    except Exception:
        pass
    return "UNKNOWN"
