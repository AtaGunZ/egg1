"""Property-set / quantity-set reading with unit conversion and JSON-safe values."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from ._units import Units

# Attributes of IfcDoor/WindowLiningProperties / PanelProperties that are lengths (others are ratios).
_LINING_LENGTH_ATTRS = {
    "LiningDepth", "LiningThickness", "ThresholdDepth", "ThresholdThickness", "TransomThickness",
    "MullionThickness", "CasingThickness", "CasingDepth", "LiningOffset", "LiningToPanelOffsetX",
    "LiningToPanelOffsetY", "PanelDepth", "FrameDepth", "FrameThickness", "TransomOffset",
}
_SKIP_ATTRS = {"GlobalId", "OwnerHistory", "Name", "Description", "ShapeAspectStyle", "id"}


def norm_key(s: str) -> str:
    """Case/space/underscore/diacritic-insensitive key for property-name matching."""
    s = s.replace("ß", "ss").replace("ı", "i")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.lower())


@dataclass
class PropBag:
    psets: dict = field(default_factory=dict)    # name -> {prop: value}
    qtos: dict = field(default_factory=dict)     # name -> {quantity: value}
    flat: dict = field(default_factory=dict)     # flattened psets, last wins

    # ---- lookup helpers -------------------------------------------------------------------
    @staticmethod
    def _prio_q(name: str) -> int:
        n = name.lower()
        if n.startswith("qto_") or n == "basequantities":
            return 0
        return 1

    @staticmethod
    def _prio_p(name: str) -> int:
        n = name.lower()
        if n.startswith("pset_"):
            return 0
        return 1

    def find_quantity(self, keys, positive=True):
        """First numeric quantity whose normalised name equals one of ``keys`` (ordered by key preference)."""
        nkeys = [norm_key(k) for k in keys]
        sets = sorted(self.qtos.items(), key=lambda kv: self._prio_q(kv[0]))
        for nk in nkeys:
            for sname, d in sets:
                for k, v in d.items():
                    if norm_key(k) == nk and _is_num(v) and (not positive or v > 0):
                        return float(v), f"{sname}.{k}"
        return None, None

    def find_property(self, keys, positive=True, numeric=True):
        nkeys = [norm_key(k) for k in keys]
        sets = sorted(self.psets.items(), key=lambda kv: self._prio_p(kv[0]))
        for nk in nkeys:
            for sname, d in sets:
                for k, v in d.items():
                    if norm_key(k) != nk:
                        continue
                    if numeric:
                        if _is_num(v) and (not positive or v > 0):
                            return float(v), f"{sname}.{k}"
                    elif v not in (None, ""):
                        return v, f"{sname}.{k}"
        return None, None

    def find_bool(self, keys):
        nkeys = [norm_key(k) for k in keys]
        sets = sorted(self.psets.items(), key=lambda kv: self._prio_p(kv[0]))
        for nk in nkeys:
            for sname, d in sets:
                for k, v in d.items():
                    if norm_key(k) == nk:
                        b = to_bool(v)
                        if b is not None:
                            return b, f"{sname}.{k}"
        return None, None


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def to_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and v in (0, 1):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "yes", "ja", "evet", "1", "wahr", "t", ".t."):
            return True
        if s in ("false", "no", "nein", "hayir", "hayır", "0", "falsch", "f", ".f."):
            return False
    return None


def parse_size_string(s):
    """Parse '0,78x1,96' style strings into (w, h) floats (metres assumed) or None."""
    if not isinstance(s, str):
        return None
    m = re.match(r"^\s*([0-9]+[.,]?[0-9]*)\s*[xX*×]\s*([0-9]+[.,]?[0-9]*)\s*$", s)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
    except ValueError:
        return None


# ---------------------------------------------------------------------------------------------
def _wrapped(v):
    """Unwrap an IFC value (IfcLabel(..) etc.) to (python value, ifc type name)."""
    if v is None:
        return None, None
    if hasattr(v, "is_a") and hasattr(v, "wrappedValue"):
        return v.wrappedValue, v.is_a()
    if hasattr(v, "is_a"):  # a real entity reference -> not a plain value
        return None, None
    return v, None


def _safe(v):
    if isinstance(v, (str, int, float, bool)) or v is None:
        if isinstance(v, float) and v != v:
            return None
        return v
    return str(v)


def _prop_value(p, units: Units):
    c = p.is_a()
    try:
        if c == "IfcPropertySingleValue":
            val, t = _wrapped(p.NominalValue)
            return _safe(units.convert_measure(t, val, getattr(p, "Unit", None)))
        if c == "IfcPropertyEnumeratedValue":
            vals = [_wrapped(x)[0] for x in (p.EnumerationValues or [])]
            vals = [x for x in vals if x is not None]
            return _safe(vals[0]) if len(vals) == 1 else ([_safe(x) for x in vals] or None)
        if c == "IfcPropertyListValue":
            out = []
            for x in p.ListValues or []:
                val, t = _wrapped(x)
                out.append(_safe(units.convert_measure(t, val, getattr(p, "Unit", None))))
            return out or None
        if c == "IfcPropertyBoundedValue":
            for attr in ("SetPointValue", "UpperBoundValue", "LowerBoundValue"):
                val, t = _wrapped(getattr(p, attr, None))
                if val is not None:
                    return _safe(units.convert_measure(t, val, getattr(p, "Unit", None)))
            return None
        if c == "IfcPropertyReferenceValue":
            return None
    except Exception:
        return None
    return None


def _quantity_value(q, units: Units):
    c = q.is_a()
    try:
        if c == "IfcQuantityLength":
            return q.LengthValue * units.length
        if c == "IfcQuantityArea":
            return q.AreaValue * units.area
        if c == "IfcQuantityVolume":
            return q.VolumeValue * units.volume
        if c == "IfcQuantityCount":
            return q.CountValue
        if c == "IfcQuantityWeight":
            return q.WeightValue
        if c == "IfcQuantityTime":
            return q.TimeValue
    except Exception:
        return None
    return None


def _read_definition(pdef, units: Units, bag: PropBag):
    name = pdef.Name if getattr(pdef, "Name", None) else pdef.is_a()
    try:
        if pdef.is_a("IfcPropertySet"):
            d = {}
            for p in pdef.HasProperties or []:
                v = _prop_value(p, units)
                if v is not None:
                    d[p.Name] = v
            bag.psets.setdefault(name, {}).update(d)
        elif pdef.is_a("IfcElementQuantity"):
            d = {}
            for q in pdef.Quantities or []:
                v = _quantity_value(q, units)
                if v is not None:
                    d[q.Name] = v
            bag.qtos.setdefault(name, {}).update(d)
        elif pdef.is_a("IfcDoorLiningProperties") or pdef.is_a("IfcWindowLiningProperties") \
                or pdef.is_a("IfcDoorPanelProperties") or pdef.is_a("IfcWindowPanelProperties"):
            d = {}
            info = pdef.get_info(recursive=False)
            for k, v in info.items():
                if k in _SKIP_ATTRS or k == "type" or v is None:
                    continue
                if isinstance(v, float):
                    if k in _LINING_LENGTH_ATTRS:
                        v = v * units.length
                    d[k] = v
                elif isinstance(v, (str, int, bool)):
                    d[k] = v
            bag.psets.setdefault(name, {}).update(d)
    except Exception:
        pass


def read_properties(el, units: Units) -> PropBag:
    """Read psets + quantity sets of an element, type-level first so occurrence values override."""
    bag = PropBag()
    defs = []
    try:
        typ = None
        for rel in getattr(el, "IsTypedBy", None) or []:
            typ = rel.RelatingType
        if typ is None:  # IFC2X3: IsDefinedBy holds IfcRelDefinesByType
            for rel in getattr(el, "IsDefinedBy", None) or []:
                if rel.is_a("IfcRelDefinesByType"):
                    typ = rel.RelatingType
        if typ is not None:
            defs.extend(getattr(typ, "HasPropertySets", None) or [])
    except Exception:
        pass
    try:
        for rel in getattr(el, "IsDefinedBy", None) or []:
            if rel.is_a("IfcRelDefinesByProperties"):
                pd = rel.RelatingPropertyDefinition
                if pd is None:
                    continue
                if pd.is_a("IfcPropertySetDefinitionSet"):
                    defs.extend(pd.PropertySetDefinitions)
                else:
                    defs.append(pd)
    except Exception:
        pass
    for d in defs:
        _read_definition(d, units, bag)
    for sname, d in bag.psets.items():
        for k, v in d.items():
            bag.flat[k] = v
    return bag
