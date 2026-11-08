"""Declarative specification of the Kayseri BB Imar Yonetmeligi rule catalogue (source of rules/kayseri.rules.json).

Limits are the CURRENT-in-force values (redline applied). Automation levels are assessed honestly against what the
BIMCheck models can deliver (CONTRACTS.md sections 1-3):
  auto   = the engine can decide pass/violation from measures it receives
  semi   = engine pre-screens; edge cases / missing context become 'review'
  manual = catalogued for the reviewer; no reliable data source in IFC/DWG/ProjectContext today
Run `python tools/regulation/build_rules.py` after editing.
"""
from .specdsl import ANY, M, M2, M3, R, aw, cu, eq, man, mn, mx, rng

RES = ["residential", "mixed"]
LIVING = ["living_room", "bedroom", "kitchen", "commercial"]          # 'iskan edilen' rooms (Madde 28(4))
WET_PASSAGE = ["bathroom", "wc", "storage", "corridor", "hall", "stair"]  # Madde 28(5) 2.20 m group
BM, PC, DM = "building_model", "parcel_context", "drawing_model"
PAIY = "Planlı Alanlar İmar Yönetmeliği (3/7/2017, RG 30113)"
YANGIN = "Binaların Yangından Korunması Hakkında Yönetmelik"
TS9111 = "TS 9111 (engellilerin kullanabileceği bina ve çevre standardı) / erişilebilirlik mevzuatı"
TSE_ASANSOR = "Asansör Yönetmeliği (2014/33/AB) ve TSE standartları"

RULES = []
add = RULES.append

# ============================================================================================ MADDE 6 - parcel sizes
_ZK = ["konut", "ticaret", "karma"]
_ZCTX = "ProjectContext zone_type / building_order / max_storeys / parcel_polygon (or drawing parcel)"
_PW = "Parsel genişliği"
add(R(6, 2, "a.1", tr=_PW + ": 4 kata kadar (4 dahil) konut-ticaret bölgeleri", en="Parcel width: up to 4 storeys, residential/commercial zones",
      cat="zoning", auto="semi", req=[PC], alt=[DM], when=aw(max_storeys=4, zone_type=_ZK),
      check=cu("parcel_dimensions", "parcel", 6.0, M, op=">=", extra={"part": "width", "storey_band": [1, 4],
               "formula": {"adjacent": "6.00", "block_end": "yan bahçe + 6.00", "detached": "yan bahçeler toplamı + 6.00"}},
               exceptions=["İmar planında farklı hüküm varsa plan geçerlidir (Madde 6(1))", "Köşe başı parsellerde yan bahçe yerine yol için tayin edilmiş ön bahçe alınır (6(2)(e))"]),
      notes="PDF text of 6(2)(a)(1) omits the '+' for block ends ('Yan bahçe mesafesi 6.00 metreden'); read as 'yan bahçe + 6.00' in line with items 2)-4). Width = parcel width on the road frontage (front edge from ProjectContext.front_edge_index).",
      needs="Parcel polygon + front edge + building order (ayrık/bitişik/blok) + storey count; setbacks for detached/block formulas.",
      deleg=[PAIY + " (parsel tanımları)"]))
add(R(6, 2, "a.2", tr=_PW + ": 6 kata kadar (6 dahil) konut-ticaret bölgeleri", en="Parcel width: up to 6 storeys, residential/commercial zones",
      cat="zoning", auto="semi", req=[PC], alt=[DM], when=aw(min_storeys=5, max_storeys=6, zone_type=_ZK),
      check=cu("parcel_dimensions", "parcel", 8.0, M, op=">=", extra={"part": "width", "storey_band": [5, 6],
               "formula": {"adjacent": "8.00", "block_end": "yan bahçe + 8.00", "detached": "yan bahçeler toplamı + 8.00"}},
               exceptions=["İmar planında farklı hüküm varsa plan geçerlidir"]),
      notes="Whole sub-item added by the 2022 amendment (red).", needs="As KBB-6-2-a-1.", deleg=[PAIY]))
add(R(6, 2, "a.3", tr=_PW + ": 9 kata kadar (9 dahil) konut-ticaret bölgeleri", en="Parcel width: up to 9 storeys, residential/commercial zones",
      cat="zoning", auto="semi", req=[PC], alt=[DM], when=aw(min_storeys=7, max_storeys=9, zone_type=_ZK),
      check=cu("parcel_dimensions", "parcel", 9.0, M, op=">=", extra={"part": "width", "storey_band": [7, 9],
               "formula": {"adjacent": "9.00", "block_end": "yan bahçeler toplamı + 9.00", "detached": "yan bahçeler toplamı + 9.00"}},
               exceptions=["İmar planında farklı hüküm varsa plan geçerlidir"]),
      notes="Band 7-9 storeys (item 3 numbering was renumbered by the amendment: old 2) -> 3).", needs="As KBB-6-2-a-1.", deleg=[PAIY]))
add(R(6, 2, "a.4", tr=_PW + ": 10 ve daha fazla katlı konut-ticaret bölgeleri", en="Parcel width: 10+ storeys, residential/commercial zones",
      cat="zoning", auto="semi", req=[PC], alt=[DM], when=aw(min_storeys=10, zone_type=_ZK),
      check=cu("parcel_dimensions", "parcel", 12.0, M, op=">=", extra={"part": "width", "storey_band": [10, None],
               "formula": {"adjacent": "12.00", "block_end": "yan bahçe + 12.00", "detached": "yan bahçeler toplamı + 12.00"}},
               exceptions=["İmar planında farklı hüküm varsa plan geçerlidir"]),
      needs="As KBB-6-2-a-1.", deleg=[PAIY]))
add(R(6, 2, "b", tr=_PW + ": yalnız 1 katlı dükkân yapılacak ticaret ve küçük sanayi bölgeleri", en="Parcel width: single-storey shops in commercial / small-industry zones",
      cat="zoning", auto="semi", req=[PC], alt=[DM], when=aw(max_storeys=1, zone_type=["ticaret"]),
      check=cu("parcel_dimensions", "parcel", 5.0, M, op=">=", extra={"part": "width", "storey_band": [1, 1],
               "formula": {"adjacent": "5.00", "block_end": "yan bahçe + 5.00", "detached": "yan bahçeler toplamı + 5.00"}}),
      notes="'Küçük sanayi' is not a ProjectContext.zone_type value: only the 'ticaret' branch can be pre-screened.", needs="As KBB-6-2-a-1.", deleg=[PAIY]))
add(R(6, 2, "c", tr=_PW + ": sanayi bölgeleri", en="Parcel width: industrial zones", cat="zoning", auto="semi", req=[PC], alt=[DM],
      when=aw(zone_type=["sanayi"]), check=cu("parcel_dimensions", "parcel", 30.0, M, op=">=", extra={"part": "width"}),
      needs="Parcel polygon + front edge; zone_type = sanayi.", deleg=[PAIY]))
add(R(6, 2, "cc", tr=_PW + ": akaryakıt istasyonları", en="Parcel width: fuel stations", cat="zoning", auto="manual", req=[PC],
      when=aw(), check=man("parcel", 40.0, M, op=">="),
      notes="ProjectContext.zone_type cannot express 'akaryakıt istasyonu' (proposal in CONTRACT_CHANGES.md).", needs="Land-use class from the plan.", deleg=[PAIY]))
add(R(6, 2, "d", tr=_PW + ": konut dışı kentsel çalışma ve kentsel servis alanları", en="Parcel width: non-residential urban work / urban service areas",
      cat="zoning", auto="manual", req=[PC], check=man("parcel", 30.0, M, op=">="),
      notes="Value 30.00 m replaced 40.00 m (2022 amendment). Land-use class not expressible in ProjectContext.", needs="Land-use class from the plan.", deleg=[PAIY]))
add(R(6, 2, "e", tr="Parsel genişliği: köşe başı parselde yan bahçe yerine ön bahçe alınır", en="Parcel width: corner parcels use front setback instead of side setback",
      cat="zoning", auto="manual", req=[PC], check=man("parcel"),
      notes="Modifier for KBB-6-2-a-*; needs identification of the road-side side edge.", needs="Corner parcel geometry with road edges tagged."))
_PD = "Parsel derinliği"
add(R(6, 3, "a", tr=_PD + ": konut ve ticaret bölgeleri", en="Parcel depth: residential and commercial zones", cat="zoning", auto="semi", req=[PC], alt=[DM],
      when=aw(zone_type=_ZK), check=cu("parcel_dimensions", "parcel", 13.0, M, op=">=", extra={"part": "depth",
               "formula": {"no_front_garden": "13.00", "front_garden": "ön bahçe + 13.00"}}),
      needs="Parcel polygon + front edge + front setback.", deleg=[PAIY]))
add(R(6, 3, "b", tr=_PD + ": ticaret bölgeleri, yalnız 1 katlı dükkân", en="Parcel depth: commercial zones, single-storey shops", cat="zoning", auto="semi", req=[PC], alt=[DM],
      when=aw(max_storeys=1, zone_type=["ticaret"]), check=cu("parcel_dimensions", "parcel", 5.0, M, op=">=", extra={"part": "depth",
               "formula": {"no_front_garden": "5.00", "front_garden": "ön bahçe + 5.00"}}),
      needs="As KBB-6-3-a.", deleg=[PAIY]))
add(R(6, 3, "c", tr=_PD + ": küçük sanayi bölgeleri", en="Parcel depth: small-industry zones", cat="zoning", auto="manual", req=[PC],
      check=man("parcel", 6.0, M, op=">="), notes="'Küçük sanayi' not expressible in ProjectContext.zone_type.", needs="Land-use class from the plan.", deleg=[PAIY]))
add(R(6, 3, "cc", tr=_PD + ": sanayi bölgeleri", en="Parcel depth: industrial zones", cat="zoning", auto="semi", req=[PC], alt=[DM],
      when=aw(zone_type=["sanayi"]), check=cu("parcel_dimensions", "parcel", 30.0, M, op=">=", extra={"part": "depth"}),
      needs="Parcel polygon + front edge; zone_type = sanayi.", deleg=[PAIY]))
add(R(6, 3, "d", tr=_PD + ": akaryakıt istasyonları", en="Parcel depth: fuel stations", cat="zoning", auto="manual", req=[PC],
      check=man("parcel", 40.0, M, op=">="), needs="Land-use class from the plan.", deleg=[PAIY]))
add(R(6, 3, "e", tr=_PD + ": konut dışı kentsel çalışma ve kentsel servis alanları", en="Parcel depth: non-residential urban work / urban service areas",
      cat="zoning", auto="manual", req=[PC], check=man("parcel", 30.0, M, op=">="),
      notes="30.00 m replaced 40.00 m (2022 amendment).", needs="Land-use class from the plan.", deleg=[PAIY]))
add(R(6, 4, None, tr="Parsel alanı: konut dışı kentsel çalışma ve kentsel servis alanları", en="Parcel area: non-residential urban work / urban service areas",
      cat="zoning", auto="manual", req=[PC], check=man("parcel", 1500.0, M2, op=">="),
      notes="Minimum parcel area 1500 m² (was 2000 m²; scope extended to 'kentsel servis alanları' by the 2022 amendment). ProjectContext.parcel_area exists but the land-use class does not.",
      needs="Parcel area (ProjectContext.parcel_area) + land-use class from the plan.", deleg=[PAIY]))
add(R(6, 5, None, tr="Parsel büyüklüğüne uymayan arsada ruhsat verilemez (istisna)", en="No permit on non-conforming parcels (exception for pre-existing subdivision)",
      cat="zoning", auto="manual", req=[PC], sev="warning", check=man("parcel"),
      notes="Legal judgement (exception for parcels created by prior zoning implementation).", needs="Legal/planning review."))

# ============================================================================================ MADDE 9 - storeys by road width
add(R(9, 1, "a", tr="Yol genişliğine göre en çok kat adedi (plan kat adedi/yüksekliği belirtmiyorsa)", en="Maximum storeys by road width (when the plan gives no storeys/height)",
      cat="zoning", auto="semi", sev="warning", req=[PC], alt=[BM], when=aw(),
      check=cu("max_storeys", "building", 15, "storeys", op="<=", tol=0, extra={"part": "road_width_table", "table_is_exclusive_to": "plans before 1/10/2017 without storeys/height",
               "table": [{"road_width_max": 7.0, "max_storeys": 2}, {"road_width_max": 10.0, "max_storeys": 3}, {"road_width_max": 12.0, "max_storeys": 4},
                         {"road_width_max": 15.0, "max_storeys": 5}, {"road_width_max": 20.0, "max_storeys": 6}, {"road_width_max": 25.0, "max_storeys": 8},
                         {"road_width_max": 35.0, "max_storeys": 10}, {"road_width_max": 50.0, "max_storeys": 14}, {"road_width_max": None, "max_storeys": 15}],
               "basement_excluded": True},
               exceptions=["Uygulama imar planında kat adedi veya bina yüksekliği belirtilmişse bu tablo uygulanmaz", "1/10/2017 sonrası planlarda geçersiz"]),
      rev="Last row (road width > 50.00 m): max storeys 18 -> 15; reference date changed from 'yönetmeliğin yürürlüğe girdiği tarih' to 1/10/2017.",
      notes="Only applies to old plans (before 1/10/2017) that state neither storeys nor height. Limit column holds the largest entry; engine selects the row from ProjectContext.road_width (or the plan value in max_storeys). Storeys counted without basements.",
      needs="ProjectContext.road_width (and a statement that the plan has no storey count) + building storey count.", deleg=[PAIY + " (kat adedi/yükseklik tanımları)"]))
add(R(9, 1, "b", tr="Yol genişliğinin tespiti", en="Determination of road width", cat="zoning", auto="manual", sev="info", req=[PC], check=man("parcel"),
      notes="Definition used by KBB-9-1-a (width of the road on the front facade excluding front garden, green strip, median...).", needs="Plan road section."))
add(R(9, 1, "c", tr="Kat adedinin kot noktasına göre hesabı; subasman kotu en fazla 1.20 m", en="Storey count measured from the datum point; plinth max 1.20 m above datum",
      cat="heights", auto="manual", sev="warning", req=[BM], check=man("building", 1.2, M, op="<="),
      needs="Terrain/road datum (not modelled).", deleg=["Kot verilmesine ilişkin esaslar (Madde 10-14)"]))

# ============================================================================================ MADDE 11-18 terrain & garden levelling (manual)
add(R(11, 5, None, tr="Zemin kat kotu 3.50 m'yi aştığında kademelendirme; her kademe en çok 3.50 m", en="Stepping of the building when ground floor rises above 3.50 m; each step max 3.50 m",
      cat="heights", auto="manual", sev="warning", req=[BM, PC], check=man("building", 3.5, M, op="<="), needs="Road/curb levels along the front facade + facade stepping.", deleg=["Planlı Alanlar İmar Yönetmeliği saçak/bina yüksekliği tanımları"]))
add(R(11, 6, None, tr="Kademe cephe boyu en az 4.50 m", en="Each step at least 4.50 m long along the facade", cat="heights", auto="manual", sev="warning", req=[BM, PC],
      check=man("building", 4.5, M, op=">="), needs="Facade geometry per step."))
add(R(12, 1, None, tr="Tabii zeminden kotlandırma koşulu (ön bahçe 10.00 m)", en="Levelling from natural ground (front garden 10.00 m)", cat="heights", auto="manual", sev="info",
      req=[PC], check=man("parcel", 10.0, M, op=">="), rev="Front garden threshold 12.00 -> 10.00 m when the natural ground is below the road; sentence on parcels with several road frontages added.",
      needs="Natural-ground survey, front setback."))
add(R(14, 3, None, tr="İki yol arası kot farkı >= 3.50 m ve parsel derinliği > 12.00 m: yakın yoldan kotlandırma", en="Two-road parcels: level difference >= 3.50 m and depth > 12.00 m -> level from the nearer road",
      cat="heights", auto="manual", sev="info", req=[PC], check=man("parcel", 3.5, M, op=">="), rev="Paragraphs (2)-(3) replace the old (2) (whole paragraph amended).", needs="Road levels."))
add(R(16, 1, "b", tr="% 15'ten eğimli yol önündeki ön bahçe: kademeler arası en çok 0.15 m", en="Front garden along roads steeper than 15 %: steps at most 0.15 m", cat="heights", auto="manual", sev="warning",
      req=[BM], check=man("parcel", 0.15, M, op="<="), needs="Site grading plan."))
add(R(16, 2, None, tr="Ön bahçe yola doğru en fazla % 2 meyilli", en="Front garden slopes to the road by at most 2 %", cat="heights", auto="manual", sev="warning",
      req=[BM], check=man("parcel", 2.0, "%", op="<="), needs="Site grading plan."))
add(R(16, 4, None, tr="Otopark giriş eğimi: parsel sınırından ilk 3.00 m en çok % 7", en="Parking ramp: first 3.00 m from the parcel boundary at most 7 % slope", cat="accessibility", auto="manual", sev="warning",
      req=[BM], check=man("building", 7.0, "%", op="<="), notes="Needs ramp elements (no 'ramp' kind in BuildingModel v1).", needs="Ramp slope + position relative to parcel boundary."))
add(R(16, 5, None, tr="Otopark rampası ön bahçe boyunca yola paralel; parsel sınırına 3 m'den fazla yaklaşmaz", en="Parking ramps parallel to the road inside the front garden, at least 3 m from the parcel boundary",
      cat="setbacks", auto="manual", sev="warning", req=[PC], check=man("building", 3.0, M, op=">="), rev="'yapılamaz' -> 'yapılabilir' with the 3 m condition (2022 amendment): now permitted.", needs="Ramp geometry + parcel boundary."))
add(R(18, 3, None, tr="Arka bahçede dolgu en çok 2.00 m ve ±0.00 kotunu geçemez", en="Back-garden fill at most 2.00 m and not above the ±0.00 datum", cat="heights", auto="manual", sev="warning",
      req=[BM], check=man("parcel", 2.0, M, op="<="), needs="Site sections."))

# ============================================================================================ MADDE 20-22 TAKS / KAKS
add(R(20, 1, None, tr="Taban alanı (TAKS) - Planlı Alanlar İmar Yönetmeliği m.20'ye göre", en="Ground coverage (TAKS) per Planlı Alanlar İmar Yönetmeliği art. 20",
      cat="zoning", auto="semi", req=[PC], alt=[BM, DM], when=aw(),
      check=cu("taks_kaks", "building", None, "ratio", op="<=", tol=0.001, extra={"part": "taks", "formula": "footprint_area / parcel_area <= context.taks",
               "footprint_sources": ["drawing_model.footprint", "building_model: ground-floor slab/space footprint"]}),
      notes="The Kayseri text only refers to PAİY art. 20; the actual TAKS limit comes from the plan (ProjectContext.taks). What counts as 'taban alanı' (projections, pergolas, canopies...) follows PAİY art. 20 and is only approximated -> semi.",
      needs="ProjectContext.taks + parcel_area, building footprint (DWG footprint or IFC ground slab).", deleg=[PAIY + " m.20 (taban alanı tanımı ve hesabı)"]))
add(R(21, 1, None, tr="Katlar alanı (KAKS/emsal) hesabı ve sınırı", en="Total floor area (KAKS / floor-area ratio) calculation and limit",
      cat="zoning", auto="semi", req=[PC], alt=[BM, DM], when=aw(),
      check=cu("taks_kaks", "building", None, "ratio", op="<=", tol=0.001, extra={"part": "kaks", "formula": "sum(storey areas incl. basement, mezzanine, attic, open/closed projections; minus Madde 22 exclusions) / parcel_area <= context.kaks"}),
      notes="Gross floor areas per storey can be summed from slabs/spaces, but the Madde 22 exclusions (shelter, shafts, parking, janitor flat up to 120 m², ...) need human confirmation -> semi, always 'review' when close to the limit.",
      needs="ProjectContext.kaks + parcel_area, storey areas from IFC (gross_floor_area) or DWG plans; list of excluded areas.", deleg=["Madde 22 (hesaba dahil edilmeyenler)", PAIY + " m.5, m.20"]))
add(R(21, 2, None, tr="Tamamen toprak altındaki alanların cephesi açığa çıkarılamaz", en="Fully buried (non-counted) floors must not be exposed by excavation", cat="zoning", auto="manual", sev="warning",
      req=[BM], check=man("building"), needs="Site sections vs. basement walls."))
add(R(21, 4, None, tr="Emsal verilmeyen planlarda katlar alanı = TAKS x kat adedi", en="Where the plan gives no floor-area ratio: total floor area = TAKS x storeys", cat="zoning", auto="semi", req=[PC],
      alt=[BM, DM], check=cu("taks_kaks", "building", None, "ratio", op="<=", tol=0.001, extra={"part": "kaks_derived", "formula": "kaks := taks * max_storeys when context.kaks is null"}),
      needs="ProjectContext.taks + max_storeys without kaks."))
add(R(22, 1, None, tr="Katlar alanı hesabına dahil edilmeyen kullanımlar (a)/(b)/(c) listeleri", en="Uses excluded from the floor-area calculation (lists a/b/c)",
      cat="zoning", auto="manual", sev="info", req=[BM], check=man("building"),
      notes="Key numeric caps (current values): janitor flat 120 m² total (was 70), caretaker mosque 150 m² housing / 300 m² non-housing, children's play 100 m², library 50 m², balconies/stair wells <= 20 % of unit net area, storage extras <= 50 % of unit net area, pergola/gazebo <= 20 % of garden area, shelter etc. Use as input to KBB-21-1.",
      rev="Many items added/changed by the 2022 amendment (janitor flat 70 -> 120 m²; new items (a)(6)-(9), (b)(6), (c)(12)-(13),(18),(20)-(21),(23)).",
      needs="Areas by use per storey.", deleg=["Madde 21", PAIY + " m.20(8)"]))

# ============================================================================================ MADDE 23 - setbacks
_SB = dict(req=[PC], alt=[BM, DM], cat="setbacks")
_SBNEED = "Parcel polygon (ProjectContext or DWG 'arsa' layer) + building footprint (DWG/IFC) + front edge index; plan-note setbacks (ProjectContext) override defaults."
_PLAN = "Uygulama imar planında aksine hüküm varsa plan geçerlidir"
add(R(23, 1, "a", tr="Ön bahçe ve yol/kamusal alana komşu bahçe mesafesi en az 5.00 m", en="Front / road-side / public-space-adjacent setback at least 5.00 m", auto="semi",
      check=cu("parcel_setbacks", "parcel", 5.0, M, op=">=", extra={"edge": "front", "context_key": "front_setback", "default": 5.0, "also_applies_to": "edges adjacent to public space"}, exceptions=[_PLAN]),
      notes="'Kamusal alana komşu' edges other than the front edge cannot be identified from the data -> review.", needs=_SBNEED, **_SB))
add(R(23, 1, "b", tr="Yan bahçe mesafesi en az 3.00 m", en="Side setback at least 3.00 m", auto="semi",
      check=cu("parcel_setbacks", "parcel", 3.0, M, op=">=", extra={"edge": "side", "context_key": "side_setback", "default": 3.0}, exceptions=[_PLAN, "Bitişik nizamda bitişik sınırda mesafe aranmaz"]),
      notes="Adjacent (bitişik) boundaries: no side setback. building_order from ProjectContext decides.", needs=_SBNEED, **_SB))
add(R(23, 1, "c", tr="Arka bahçe mesafesi en az 3.00 m", en="Rear setback at least 3.00 m", auto="semi",
      check=cu("parcel_setbacks", "parcel", 3.0, M, op=">=", extra={"edge": "rear", "context_key": "rear_setback", "default": 3.0}, exceptions=[_PLAN]),
      needs=_SBNEED, **_SB))
add(R(23, 1, "cc", tr="4 kat üzeri her kat için yan ve arka bahçe 0.50 m artırılır", en="Side and rear setbacks +0.50 m for every storey above 4", auto="semi",
      check=cu("parcel_setbacks", "parcel", 0.5, M, op=">=", extra={"part": "storey_increment", "per_storey_above": 4, "increment": 0.5, "edges": ["side", "rear"],
               "storey_count_method": "KBB-23-1-d", "not_applied_to": "edges adjacent to park areas"}, exceptions=["Park alanına komşu cephelerde uygulanmaz", _PLAN]),
      notes="Storeys counted per KBB-23-1-d (visible height / 3.00; remainder > 2.50 m counts as a storey), basements above ground included. Option KBB-23-1-f: may be evaluated storey by storey.",
      needs=_SBNEED + " Storey heights from the model.", **_SB))
add(R(23, 1, "d", tr="Bahçe mesafesinde kat adedi: görünen kat yüksekliği toplamı / 3; 2.50 m'yi aşan artık 1 kat", en="Storey count for setbacks: sum of visible storey heights / 3; remainder above 2.50 m counts as one storey",
      cat="setbacks", auto="manual", sev="info", req=[BM], check=man("building", 2.5, M, op=">"), notes="Calculation method implemented inside KBB-23-1-ç; kept as its own entry so a reviewer can see the text.", needs="Facade-wise buried/visible storey information."))
add(R(23, 1, "g", tr="Görünen yükseklik >= 60.50 m: ön/yan/arka sınırdan en az 15.00 m, sonraki her kat +0.50 m", en="Visible height >= 60.50 m: at least 15.00 m from front/side/rear boundaries, +0.50 m per additional storey",
      auto="semi", req=[PC], alt=[BM, DM], when=aw(),
      check=cu("parcel_setbacks", "parcel", 15.0, M, op=">=", extra={"part": "high_rise", "height_threshold": 60.5, "increment_per_storey": 0.5, "edges": ["front", "side", "rear"]}, exceptions=[_PLAN, "Madde 23(1)(ğ): ana kitle üzerinde yükselen bloklarda 10.00 m'ye düşürülebilir"]),
      needs=_SBNEED + " Building height from the model.", **{k: v for k, v in _SB.items() if k not in ("req", "alt")}))
add(R(23, 1, "gg", tr="Çok yüksek yapı az katlı ana kitle üzerindeyse mesafe düşürülebilir; kütleler arası mesafe", en="High-rise on a low podium: reduced setback; distance between towers",
      cat="setbacks", auto="manual", sev="warning", req=[PC], check=man("parcel", 20.0, M, op=">="), notes="Tower-to-tower 20.00 m (+0.50 m per 3.00 m above 60.50 m); podium max 5 storeys, setback 10.00 m down to the podium.", needs="Massing study."))
add(R(23, 2, None, tr="Zemin altı yapıların (depo, otopark, sığınak) bahçe mesafelerinde yapılması", en="Underground structures (tank, parking, shelter) inside setbacks", cat="setbacks", auto="manual", sev="warning", req=[BM, PC],
      check=man("parcel", 3.0, M, op=">="), notes="Front garden: only parking to half the front setback and not closer than 3.00 m to the boundary.", needs="Basement footprint vs setbacks."))
add(R(23, 3, None, tr="Ön bahçede açık otopark: ön bahçe 7.00 m, bina cephesinden 2.00 m dışında", en="Open parking in front garden: front setback 7.00 m, beyond 2.00 m from the facade", cat="setbacks", auto="manual", sev="warning",
      req=[PC], check=man("parcel", 7.0, M, op=">="), needs="Site plan parking layout."))
add(R(23, 4, None, tr="Bahçe mesafelerinde yapılabilecek açık yapılar (kameriye, pergola, süs havuzu...)", en="Open garden structures allowed in setbacks (gazebo, pergola, ornamental pool...)", cat="setbacks", auto="manual", sev="info", req=[BM],
      check=man("parcel"), notes="Permission list; structures must be open on all sides, single storey, not an independent unit.", needs="Site plan."))
add(R(23, 6, None, tr="Bahçede her 30.00 m² boş alan için bir ağaç", en="One tree per 30.00 m² of free garden area", cat="other", auto="manual", sev="warning", req=[PC],
      check=man("parcel", 30.0, M2), rev="'ve akaryakıt parsellerinde her 100.00 m² için' added by the 2022 amendment.", notes="Applies to residential, mixed, tourism, education, worship, health and sports parcels (+ fuel stations: 1 per 100 m²).", needs="Landscape plan with tree count and free garden area."))
add(R(23, 7, None, tr="Asansör ilavesi: bahçe mesafesi içinde parsel sınırına en az 1.50 m", en="Retrofit lift in setbacks: at least 1.50 m from the parcel boundary", cat="accessibility", auto="manual", sev="warning", req=[BM, PC],
      check=man("parcel", 1.5, M, op=">="), needs="Existing-building retrofit drawings."))
add(R(24, 2, None, tr="Aynı parselde birden fazla bina: binalar arası mesafe = ayrı ayrı yaklaşma mesafelerinin toplamı", en="Several buildings on one parcel: spacing = sum of each building's setbacks", cat="setbacks", auto="semi",
      req=[PC], alt=[BM, DM], check=cu("parcel_setbacks", "parcel", None, M, op=">=", extra={"part": "between_buildings", "rule": "distance >= setback(building A) + setback(building B)"}),
      needs="Footprints of all buildings + heights + parcel polygon."))

# ============================================================================================ MADDE 27 services
add(R(27, 1, "c", tr="Sobalı binalarda daire başına 5.00-10.00 m² odunluk/kömürlük/depo", en="Stove-heated buildings: 5.00-10.00 m² fuel/storage room per dwelling", cat="services", auto="manual", sev="warning", req=[BM],
      check=man("space", 5.0, M2, op=">=", limit_max=10.0, usage_in=["storage"]), needs="Heating type + dwelling count + storage rooms per dwelling (unit assignment not in IFC export).", deleg=["Madde 51(1)"]))
add(R(27, 1, "cc", tr="Yangın, sığınak, otopark, enerji performansı ve deprem yönetmeliklerince zorunlu birimler", en="Units mandatory under fire, shelter, parking, energy-performance and seismic regulations", cat="other", auto="manual", sev="info", req=[BM],
      check=man("building"), needs="Compliance with other regulations (not in this PDF).", deleg=[YANGIN, "Sığınak Yönetmeliği (RG 19910)", "Otopark Yönetmeliği (RG 30340)", "Binalarda Enerji Performansı Yönetmeliği (RG 27075)", "Türkiye Bina Deprem Yönetmeliği (RG 30364 mük.)"]))

# ============================================================================================ MADDE 28 heights
_H1 = "Kat yüksekliği (döşeme üstü - döşeme üstü) en çok"
_H1EX = ["Uygulama imar planında daha fazla kat yüksekliği belirlenmişse plan geçerlidir (28(1))"]
_HNEED = "Storey elevations/heights from the model + ProjectContext.zone_type (and building_use)."
_HNOTE = "Compares storeys[].height (floor-to-floor, top storey skipped) with the limit for that storey kind. 'Asma katlı zemin kat' (ground floor with mezzanine) limit was 5.50 m and is now 6.50 m (2022 amendment)."
add(R(28, 1, "a", tr=_H1 + ": ticaret bölgeleri", en="Maximum storey height: commercial zones", cat="heights", auto="semi", req=[BM, PC], when=aw(zone_type=["ticaret"]),
      check=cu("storey_height_max", "storey", 4.0, M, op="<=", extra={"zone_type": "ticaret", "ground": 4.5, "ground_with_mezzanine": 6.5, "upper": 4.0}, exceptions=_H1EX),
      notes=_HNOTE + " Limit field = upper-storey limit.", needs=_HNEED))
add(R(28, 1, "b", tr=_H1 + ": ticaretin de yapılabildiği karma alanlar", en="Maximum storey height: mixed areas allowing commerce", cat="heights", auto="semi", req=[BM, PC], when=aw(zone_type=["karma"]),
      check=cu("storey_height_max", "storey", 3.6, M, op="<=", extra={"zone_type": "karma", "ground": 4.5, "ground_with_mezzanine": 6.5, "upper_residential": 3.6, "upper_non_residential": 4.0}, exceptions=_H1EX),
      notes=_HNOTE + " Upper storeys: 3.60 m if residential, 4.00 m otherwise.", needs=_HNEED))
add(R(28, 1, "c", tr=_H1 + ": konut bölgeleri (zemin ve normal katlar 3.60 m)", en="Maximum storey height: residential zones (3.60 m)", cat="heights", auto="semi", req=[BM, PC], when=aw(zone_type=["konut"]),
      check=cu("storey_height_max", "storey", 3.6, M, op="<=", extra={"zone_type": "konut", "ground": 3.6, "upper": 3.6}, exceptions=_H1EX),
      notes="Ground floor of residential zones with commerce permitted: see KBB-28-1-ç.", needs=_HNEED))
add(R(28, 1, "cc", tr=_H1 + ": zemin katında ticaret yapılabilen konut bölgeleri", en="Maximum storey height: residential zones with ground-floor commerce", cat="heights", auto="semi", req=[BM, PC], when=aw(zone_type=["konut"], ground_floor_commerce=True),
      check=cu("storey_height_max", "storey", 3.6, M, op="<=", extra={"zone_type": "konut+ticaret_zemin", "ground": 4.5, "ground_with_mezzanine": 6.5, "upper": 3.6}, exceptions=_H1EX),
      notes=_HNOTE, needs=_HNEED + " Whether the ground floor houses commerce (ProjectContext.use = mixed)."))
add(R(28, 1, "d", tr="Geleneksel taş yığma konut yapılarında zemin ve normal kat 4.50 m kabul edilebilir", en="Traditional stone-masonry residential buildings (max 3 storeys): 4.50 m storey height accepted", cat="heights", auto="manual", sev="info", req=[BM],
      check=man("storey", 4.5, M, op="<="), needs="Structural system information (kesme taş yığma, <= 3 storeys incl. ground)."))
add(R(28, 2, None, tr="Kat yüksekliği dikkate alınmadan bina yüksekliği verilen planlarda hesap yöntemi", en="Plans giving only building height: calculation by storey count x storey heights", cat="heights", auto="manual", sev="info", req=[PC],
      check=man("building"), needs="Plan notes."))
add(R(28, 3, None, tr="Tesisat katı normal kat yüksekliğini aşamaz; 60.50 m üzeri binalarda 2.00 m'si sayılmaz", en="Service floor not higher than a normal storey; 2.00 m of it ignored above 60.50 m", cat="heights", auto="manual", sev="warning", req=[BM],
      check=man("storey", None, M, op="<="), needs="Identification of the service (tesisat) storey."))
add(R(28, 4, None, tr="İskân edilen katların iç yüksekliği en az 2.60 m", en="Clear height of occupied rooms at least 2.60 m", cat="heights", auto="auto", req=[BM],
      check=mn("space", "height", 2.60, usage_in=LIVING, exceptions=["Hava maniası olup planla kat adedi belirlenen parsellerde 2.40 m'ye düşürülebilir", "Asma katlarda aranmaz"]),
      notes="Applies to rooms for occupancy (living, bedroom, kitchen, commercial). Wet rooms/passages/storage are governed by KBB-28-5 (2.20 m). Mezzanine floors are excluded by the text: a low result on a mezzanine space is an edge case.",
      needs="space.height (clear floor-to-ceiling) with usage classification.", deleg=[]))
add(R(28, 5, None, tr="Islak hacim, kiler, geçit, merdiven altı vb.: iç yükseklik en az 2.20 m", en="Wet rooms, pantries, passages, under-stair areas: clear height at least 2.20 m", cat="heights", auto="auto", req=[BM],
      check=mn("space", "height", 2.20, usage_in=WET_PASSAGE, exceptions=["İskân edilmeyen bodrum katları ve müştemilat binaları için de 2.20 m"]),
      notes="'iç yükseklik 2.20 metreye kadar düşürülebilir' = lower bound 2.20 m. Non-inhabited basements and annex buildings also 2.20 m (not distinguishable from usage alone).", needs="space.height + usage."))
add(R(28, 6, None, tr="Garaj, kazan dairesi, odunluk, kömürlük, bodrum otopark: yükseklik idarece, en az 2.20 m", en="Garage, boiler room, fuel store, basement parking: height set by authority, never below 2.20 m", cat="heights", auto="semi", req=[BM], sev="warning",
      check=mn("space", "height", 2.20, usage_in=["garage", "technical"], exceptions=["Hizmetin gerektirdiği yükseklik idarece belirlenir"]),
      notes="2.20 m is a hard floor; the service-dependent height itself needs human review (e.g. vehicle clearance).", needs="space.height + usage."))
add(R(28, 7, None, tr="Eğitim, sağlık, sanayi, salon vb. özel yapılarda iç yükseklik mimari estetik komisyon kararıyla", en="Schools, hospitals, industry, halls etc.: clear height decided by the aesthetics commission", cat="heights", auto="manual", sev="info", req=[BM],
      check=man("space"), needs="Commission decision."))

# ============================================================================================ MADDE 29 rooms
add(R(29, 1, None, tr="Her müstakil konutta en az bulunacak piyesler: dar kenar ve net alan", en="Minimum rooms per dwelling: narrow side and net area (living 3.00/12.0, bedroom 2.50/9.00, kitchen 1.50/3.30, bath 1.50/3.00, WC 1.00/1.20)",
      cat="rooms", auto="semi", req=[BM], alt=[DM], when=aw(RES),
      check=cu("room_min_dims_area", "space", None, None, extra={"table": [
          {"piece": "1 oturma odası", "usage": "living_room", "min_width": 3.00, "min_area": 12.0},
          {"piece": "1 yatak odası", "usage": "bedroom", "min_width": 2.50, "min_area": 9.00},
          {"piece": "1 mutfak veya yemek pişirme yeri", "usage": "kitchen", "min_width": 1.50, "min_area": 3.30},
          {"piece": "1 banyo veya yıkanma yeri", "usage": "bathroom", "min_width": 1.50, "min_area": 3.00},
          {"piece": "1 tuvalet", "usage": "wc", "min_width": 1.00, "min_area": 1.20}],
          "semantics": "each dwelling must contain AT LEAST one room of each type meeting width+area; extra rooms are not bound by the table"},
          usage_in=["living_room", "bedroom", "kitchen", "bathroom", "wc"],
          exceptions=["3 veya daha az odalı konutlarda banyo ile tuvalet aynı yerde düzenlenebilir (29(2))", "Oda+banyo+tuvalet aynı mekânda ise alanlar toplanır (29(4))"]),
      notes="'En az bir' semantics: the engine can only pre-screen per space (a small living room may be a secondary one) -> never a hard violation unless no room of the type satisfies the table in the whole dwelling; dwelling grouping is not available in IFC, so the building/storey is used as the group (review).",
      needs="space.net_floor_area, space.min_width and usage for each space; dwelling grouping (IfcZone or storey) for 'one per dwelling'.", deleg=[]))
add(R(29, 2, None, tr="3 veya daha az odalı konutlarda banyo ve tuvalet aynı yerde olabilir", en="Dwellings with 3 rooms or fewer may combine bath and WC", cat="rooms", auto="manual", sev="info", req=[BM], check=man("space"), notes="Permission that relaxes KBB-29-1.", needs="Dwelling room count."))
add(R(29, 3, None, tr="Hol ve koridor genişliği en az 1.20 m", en="Hall and corridor width at least 1.20 m", cat="circulation", auto="auto", req=[BM], alt=[DM],
      check=mn("space", "min_width", 1.20, usage_in=["corridor", "hall"], exceptions=["Engelli erişilebilirlik standartları daha fazlasını gerektirebilir (29(5))"]),
      notes="Uses space.min_width (shorter side of the min-area rotated rectangle). L-shaped or very irregular corridors may under-report -> engine should downgrade to review when provenance is weak.", needs="space.min_width + usage (corridor/hall)."))
add(R(29, 4, None, tr="Birleşik mekânlarda (mutfak nişi, oda+banyo) alanlar toplanır", en="Combined spaces: required areas add up", cat="rooms", auto="manual", sev="info", req=[BM], check=man("space"), needs="Human judgement."))
add(R(29, 5, None, tr="Piyes ve koridor ölçüleri engelli erişilebilirlik standartlarına uygun olmalı", en="Room and corridor dimensions must comply with accessibility standards", cat="accessibility", auto="manual", sev="warning", req=[BM], check=man("space"),
      needs="TS 9111 clearances (1.50 m turning circle etc.).", deleg=[TS9111]))
add(R(29, 6, None, tr="Mutfak, oda, WC/banyo havalandırmaları aynı boşluğa açılamaz", en="Kitchen, room and WC/bath ventilation must not open to the same shaft", cat="services", auto="manual", sev="warning", req=[BM], check=man("space"),
      needs="Shaft/light-well to room relations (not modelled)."))
add(R(29, 7, None, tr="Su depoları ve ıslak hacimlerin altında enerji odası yapılamaz", en="No energy rooms below water tanks or wet rooms", cat="services", auto="manual", sev="warning", req=[BM], check=man("space"),
      notes="Could become semi with a space-above/below query on usage (technical vs bathroom/wc).", needs="Vertical adjacency of spaces."))

# ============================================================================================ MADDE 30 entrances / ramps
add(R(30, 1, None, tr="Bina giriş koridoru genişliği: umumi binada >= 2.20 m, diğerlerinde >= 1.50 m (dış kapı genişliğinden az olamaz)", en="Entrance corridor width: >= 2.20 m public buildings, >= 1.50 m others (and not less than the outer door)",
      cat="circulation", auto="semi", req=[BM], sev="error",
      check=cu("entrance_corridor_width", "space", 1.5, M, op=">=", usage_in=["corridor", "hall"], extra={"public_limit": 2.20, "other_limit": 1.50, "min_is_outer_door_width": True,
               "scope": "from the entrance door to the main stair / lift"}, exceptions=["Konut dışı 'umumi bina' ayrımı ProjectContext.use ile yapılır"]),
      notes="Entrance corridor = corridor/hall space adjacent to the door with is_entrance=true, measured up to the main stair or lift. Residential = 1.50 m, public buildings (use != residential) = 2.20 m.",
      needs="Entrance door (is_entrance), adjacent hall/corridor min_width, stair/lift position, building_use."))
add(R(30, 2, None, tr="Ön bahçe >= 10.00 m ise bordürden en fazla 2.00 m inilerek/çıkılarak giriş", en="Front garden >= 10.00 m: entrance at most 2.00 m above/below curb", cat="accessibility", auto="manual", sev="warning", req=[BM, PC],
      check=man("building", 2.0, M, op="<="), needs="Curb level vs entrance floor level."))
add(R(30, 3, None, tr="Yoldan yüz almayan cephelerden giriş: bordürden en fazla 2.00 m", en="Entrances on non-road facades: at most 2.00 m above/below curb", cat="accessibility", auto="manual", sev="warning", req=[BM, PC], check=man("building", 2.0, M, op="<="), needs="Curb level."))
add(R(30, 4, None, tr="Yoldan doğrudan girişte giriş bordür taşı üst seviyesinin altında olamaz", en="Direct road entrances must not be below the curb top level", cat="accessibility", auto="manual", sev="warning", req=[BM, PC], check=man("building"), needs="Curb level."))
add(R(30, 7, None, tr="Konut zemin kat dükkân girişleri yalnız yol cephesinden", en="Shop entrances in residential ground floors only from the road facade", cat="circulation", auto="manual", sev="warning", req=[BM, PC], check=man("door"), needs="Door position vs road facade."))
add(R(30, 8, None, tr="Döşeme kaplamaları kaymaz ve tekerlekli sandalyeye uygun olmalı", en="Non-slip floor finishes suitable for wheelchairs", cat="accessibility", auto="manual", sev="info", req=[BM], check=man("covering"), needs="Finish specifications.", deleg=[TS9111]))
add(R(30, 9, None, tr="Bina ve girişlerinde TS 9111 standardına uyulması zorunlu", en="Buildings and entrances must comply with TS 9111", cat="accessibility", auto="manual", sev="warning", req=[BM], check=man("building"),
      needs="Complete TS 9111 checklist.", deleg=[TS9111]))
add(R(30, 10, None, tr="Rampa kenar koruma, genişlik, sahanlık, korkuluk, küpeşte TS 9111'e uygun", en="Ramp edges, widths, landings, rails comply with TS 9111", cat="accessibility", auto="manual", sev="warning", req=[BM], check=man("other"),
      notes="IfcRamp has no BuildingModel kind in contract v1 (see CONTRACT_CHANGES.md).", needs="Ramp geometry.", deleg=[TS9111]))
add(R(30, 11, None, tr="Giriş rampası veya engelli asansörü/platformu: dar kenar >= 0.90 m, alan >= 1.20 m²", en="Entrance ramp or disabled lift/platform: narrow side >= 0.90 m, area >= 1.20 m²", cat="accessibility", auto="manual", sev="warning", req=[BM],
      check=man("other", 1.2, M2, op=">="), needs="Ramp / platform elements.", deleg=["Aile ve Sosyal Politikalar Bakanlığı görüşü (farklı uygulama için)"]))
add(R(30, 12, None, tr="Rampa eğimleri: <=15 cm 1:12 (% 8); 16-50 cm 1:14 (% 7); 51-100 cm 1:16 (% 6); >100 cm 1:20 (% 5)", en="Ramp slopes by rise: <=15 cm 1:12 (8 %); 16-50 cm 1:14 (7 %); 51-100 cm 1:16 (6 %); >100 cm 1:20 (5 %)",
      cat="accessibility", auto="manual", sev="error", req=[BM], check=man("other", 8.0, "%", op="<=", extra={"table": [{"max_rise_m": 0.15, "max_slope_percent": 8}, {"max_rise_m": 0.50, "max_slope_percent": 7},
               {"max_rise_m": 1.00, "max_slope_percent": 6}, {"max_rise_m": None, "max_slope_percent": 5}]}),
      notes="Becomes auto once BuildingModel exposes ramps (kind 'ramp' with measures slope, rise, width).", needs="Ramp slope and rise."))
add(R(30, 13, None, tr="Rampa ve sahanlıklarda 0.90 m (1. düzey) ve 0.70 m (2. düzey) yükseklikte 32-45 mm küpeşte", en="Ramps/landings: continuous handrails at 0.90 m and 0.70 m, diameter 32-45 mm", cat="accessibility", auto="manual", sev="warning", req=[BM],
      check=man("railing", 0.9, M, op="=="), needs="Handrail elements with role + diameter.", deleg=[TS9111]))

# ============================================================================================ MADDE 31 stairs
add(R(31, 1, "a", tr="Merdiven kolu ve sahanlık genişliği (konut >= 1.20 m, diğer >= 1.50 m, daire içi >= 1.00 m, küçük ticarethane >= 1.20 m)", en="Stair flight and landing width (residential common 1.20 m, other 1.50 m, in-dwelling 1.00 m, small shops 1.20 m)",
      cat="stairs", auto="semi", req=[BM], when=aw(),
      check=cu("stair_width", "stair", 1.2, M, op=">=", extra={"residential_common": 1.20, "other_buildings": 1.50, "in_dwelling": 1.00, "shops_below_100m2": 1.20, "min_is_escape_width": True}, exceptions=["Yangın yönetmeliğine göre hesaplanan kaçış genişliği daha büyükse o geçerlidir", "Çatı arası piyeslerine çıkan iç merdivenlerde aranmaz (31(3))"]),
      rev="'yapı inşaat alanı 100 m²'den küçük ticarethanelerde 1.20 metreden' added (2022 amendment).",
      notes="stair.width gives the flight width; landing width is not modelled. Distinguishing common vs in-dwelling stairs needs the stair's host space/storey context (building_use). Escape width calculation belongs to the fire regulation.",
      needs="stair.width, building_use, stair context (common vs private).", deleg=[YANGIN + " (kaçış genişliği)"]))
add(R(31, 1, "b", tr="Merdiven evi cepheden/çatıdan/ışıklıktan doğrudan ışık almalı", en="Stair enclosure must get daylight directly (facade, roof, light well)", cat="stairs", auto="semi", req=[BM], sev="warning",
      check=eq("space", "has_exterior_window", True, usage_in=["stair"], exceptions=["Çatıdan veya ışıklıktan ışık alınıyorsa pencere aranmaz"]),
      notes="has_exterior_window=false on a stair space becomes 'review' (roof light / light well not detectable). Also requires stairs to reach roof and basement (not checked).", needs="space.has_exterior_window on stair spaces."))
add(R(31, 1, "c", tr="TSE merdiven ölçüleri bu maddedeki ölçülerden küçükse bu madde geçerli", en="Where TSE stair dimensions are smaller than this article, this article governs", cat="stairs", auto="manual", sev="info", req=[BM], check=man("stair"), needs="-", deleg=["TSE merdiven standartları"]))
add(R(31, 1, "cc", tr="Merdivenin iki tarafında engelli erişilebilirliğine uygun korkuluk ve küpeşte", en="Accessible guard and handrail on both sides of stairs", cat="accessibility", auto="manual", sev="warning", req=[BM], check=man("railing"), needs="Handrail elements per stair side.", deleg=[TS9111]))
add(R(31, 1, "d", tr="Merdiven kovası (aydınlık boşluğu) eni en az 0.30 m", en="Stair well (void) width at least 0.30 m", cat="stairs", auto="manual", sev="warning", req=[BM], check=man("stair", 0.30, M, op=">="), rev="Added by the 2022 amendment.", needs="Void width between flights (not a stair measure)."))
add(R(31, 2, "a", tr="Basamak yüksekliği: asansörsüz <= 0.16 m, asansörlü <= 0.18 m, dış merdiven <= 0.15 m", en="Riser height: <= 0.16 m without lift, <= 0.18 m with lift, <= 0.15 m for external stairs", cat="stairs", auto="auto", req=[BM],
      check=cu("stair_riser_vs_elevator", "stair", 0.16, M, op="<=", extra={"limit_without_elevator": 0.16, "limit_with_elevator": 0.18, "limit_external": 0.15, "elevator_source": "ProjectContext.has_elevator or an elevator element in the model"}),
      rev="'ve dış merdivenlerde 0.15 metreden' added (2022 amendment).",
      notes="Limit depends on whether the building has a lift (ProjectContext.has_elevator, or detected). If unknown -> review with the stricter limit pre-computed. External stairs (0.15 m) need an exterior flag on the stair.", needs="stair.riser_height + lift presence + external flag."))
add(R(31, 2, "b", tr="Basamak genişliği 2a+b = 60..64 cm ve en az 0.27 m", en="Tread by formula 2a+b = 60..64 cm and at least 0.27 m", cat="stairs", auto="auto", req=[BM],
      check=cu("stair_tread_formula", "stair", 0.27, M, op=">=", extra={"formula": "2*riser + tread in [0.60, 0.64] m", "formula_min": 0.60, "formula_max": 0.64, "min_tread": 0.27}, exceptions=["Balansmanlı (dengelenmiş) merdivenlerde 31(2)(c)", "Çatı arası iç merdivenlerinde aranmaz"]),
      notes="a = riser height, b = tread depth. Needs both stair.riser_height and stair.tread_depth.", needs="stair.riser_height + stair.tread_depth."))
add(R(31, 2, "c", tr="Balansmanlı merdivende basamak en dar kenarda >= 0.10 m, ortada >= 0.27 m", en="Winder stairs: tread >= 0.10 m at the narrow end, >= 0.27 m mid-tread", cat="stairs", auto="manual", sev="warning", req=[BM], check=man("stair", 0.27, M, op=">="), needs="Winder geometry."))
add(R(31, 2, "cc", tr="Basamak uçları çıkıntısız (damlalıksız) olmalı", en="Stair nosings must not project (no drip nosing)", cat="stairs", auto="manual", sev="info", req=[BM], check=man("stair"), needs="Detail drawings."))
add(R(31, 3, None, tr="Çatı arası iç merdivenlerinde (1)-(2) şartları aranmaz; yangın yönetmeliği geçerli", en="Attic stairs to top-floor dwellings are exempt from (1)-(2); fire regulation applies", cat="stairs", auto="manual", sev="info", req=[BM], check=man("stair"),
      rev="Last sentence (fire regulation applies) added by the 2022 amendment.", deleg=[YANGIN], needs="-"))
add(R(31, 5, None, tr="Karma kullanımda her kullanım için ayrı merdiven evi", en="Separate stair core for each use in mixed-use buildings", cat="stairs", auto="manual", sev="warning", req=[BM], check=man("stair"), needs="Stair-to-use assignment."))
add(R(31, 6, None, tr="Yüksekliği 1.80 m'den az olan merdiven altları kapatılır", en="Stair undersides lower than 1.80 m must be enclosed", cat="safety", auto="manual", sev="warning", req=[BM], check=man("stair", 1.8, M, op="<"), needs="Under-stair clear height + enclosure."))

# ============================================================================================ MADDE 32 light wells
add(R(32, 1, None, tr="En az 1 oturma odası ve yatak odaları doğrudan hariçten ışık ve hava almalı", en="At least one living room and all bedrooms must get light/air directly from outside", cat="openings", auto="auto", req=[BM], when=aw(RES),
      check=cu("living_room_exterior_light", "space", None, None, usage_in=["living_room", "bedroom"], extra={"rule": "each dwelling: >=1 living room and every bedroom with has_exterior_window == true", "light_well_does_not_count": True},
               exceptions=["Mutfaklar ve diğer odalar ışıklıktan, ıslak hacimler ışıklık/hava bacasından yararlanabilir"]),
      notes="Window to a light well (ışıklık) does not count as 'hariç'. has_exterior_window=null -> review. Also: WC/bath and rooms may not open to the same light well (not checked).", needs="space.has_exterior_window + usage; dwelling grouping for the 'at least one living room' part."))
add(R(32, 2, "a", tr="Işıklık: 1-6 katlı binalarda dar kenar >= 1.50 m, alan >= 4.50 m²", en="Light well in 1-6 storey buildings: narrow side >= 1.50 m, area >= 4.50 m²", cat="openings", auto="semi", req=[BM], when=aw(max_storeys=6),
      check=cu("light_well_size", "space", 1.5, M, op=">=", extra={"part": "light_well", "min_width": 1.50, "min_area": 4.50, "storey_band": [1, 6], "identify": "space usage 'technical' named ışıklık / aydınlık / light well, or void"}),
      notes="Light wells are only checkable when exported as spaces/voids with a recognisable name; engine reports review otherwise.", needs="Light-well space with min_width and net_floor_area."))
add(R(32, 2, "b", tr="Işıklık: 7 ve daha fazla katlı binalarda dar kenar >= 2.00 m, alan >= 9.00 m²", en="Light well in 7+ storey buildings: narrow side >= 2.00 m, area >= 9.00 m²", cat="openings", auto="semi", req=[BM], when=aw(min_storeys=7),
      check=cu("light_well_size", "space", 2.0, M, op=">=", extra={"part": "light_well", "min_width": 2.00, "min_area": 9.00, "storey_band": [7, None]}), needs="As KBB-32-2-a."))
add(R(32, 3, None, tr="Hava bacası asgari 0.60 x 0.60 m", en="Ventilation shaft at least 0.60 x 0.60 m", cat="openings", auto="semi", req=[BM],
      check=cu("light_well_size", "space", 0.6, M, op=">=", extra={"part": "shaft", "min_width": 0.60, "min_area": 0.36}, exceptions=["Hiçbir yapı elemanı (baca, kiriş) bu alanı daraltamaz"]),
      needs="Shaft spaces with min_width."))
add(R(32, 5, None, tr="Asgari ışıklık/hava bacasından her katta en çok 4 piyes yararlanabilir", en="A minimum-size light well / shaft may serve at most 4 rooms per storey", cat="openings", auto="manual", sev="warning", req=[BM], check=man("space", 4, "rooms", op="<="), needs="Room-to-light-well relations."))
add(R(32, 6, None, tr="Işıklık/hava bacası kendi parselinde olmalı; komşu parseldekinden yararlanılamaz", en="Light wells / shafts must be on the own parcel", cat="openings", auto="manual", sev="warning", req=[BM, PC], check=man("space"), needs="Light-well position vs parcel boundary."))
add(R(32, 9, None, tr="Banyo, tuvalet vb. alanlar hava bacası veya mekanik havalandırma ile havalandırılmalı", en="Bathrooms/WCs must be ventilated by a shaft or mechanically", cat="services", auto="manual", sev="warning", req=[BM], check=man("space", usage_in=["bathroom", "wc"]),
      notes="Partially pre-screenable via KBB-39-6 (ventilation window sizes).", needs="Ventilation system data."))

# ============================================================================================ MADDE 33 flues (manual)
add(R(33, 1, None, tr="Kaloriferli/sobalı binalarda duman bacası zorunlu", en="Smoke flue mandatory in centrally/stove-heated buildings", cat="services", auto="manual", sev="warning", req=[BM], check=man("building"), needs="Flue/shaft inventory; heating type."))
add(R(33, 6, None, tr="Kapıcı dairesi zorunlu konut binalarında atık ayrıştırma bacası", en="Waste-separation shaft in buildings requiring a janitor flat", cat="services", auto="manual", sev="info", req=[BM], check=man("building"), needs="Shaft inventory."))
add(R(33, 9, None, tr="Doğalgaz bölgesinde 5 katlı binalarda her cihaz için müstakil baca", en="Gas areas, buildings up to 5 storeys: separate flue per appliance", cat="services", auto="manual", sev="warning", req=[BM], check=man("building"), needs="Flue inventory."))
add(R(33, 11, None, tr="Kat kaloriferi kazan mahalli en az 6 m³, dış cepheden havalandırmalı, müstakil bacalı", en="Floor boiler room at least 6 m³, ventilated from the outside, own flue", cat="services", auto="manual", sev="warning", req=[BM], check=man("space", 6.0, M3, op=">=", usage_in=["technical"]),
      notes="Space volume (area x height) is derivable but the room cannot be identified as a boiler room reliably.", needs="Boiler room identification + volume."))

# ============================================================================================ MADDE 34 elevators
add(R(34, 1, None, tr="3 katlı binalarda asansör yeri, 4 ve daha fazla katlı binalarda asansör zorunlu", en="Lift space for 3-storey buildings; lift mandatory from 4 storeys (basements with dwellings/units count)", cat="circulation", auto="semi", req=[BM],
      when=aw(), check=cu("elevator_required", "building", 4, "storeys", op=">=", tol=0, extra={"storeys_for_lift_space": 3, "storeys_for_lift": 4, "count_habitable_basements": True, "exempt": "tek bağımsız bölümlü konutlar"}, exceptions=["Tek bağımsız bölümlü konutlar hariç", "Daha az katlı yapılarda da asansör yapılabilir"]),
      notes="Storey count from BuildingModel (basements included when habitable / containing units) or ProjectContext.max_storeys. Lift presence is detected from IfcTransportElement / names; a model that omits the lift yields 'review', not a violation.",
      needs="Storey count, number of units (single-dwelling exemption), lift element or shaft in the model, ProjectContext.has_elevator.", deleg=[TSE_ASANSOR]))
add(R(34, 2, None, tr="Asansör kabini dar kenar >= 1.20 m, alan >= 1.80 m², kapı net >= 0.90 m; sahanlık 1.20/1.50 m", en="Lift car narrow side >= 1.20 m, area >= 1.80 m², door >= 0.90 m; landing 1.20 m (sliding) / 1.50 m (swing)", cat="accessibility", auto="manual", sev="error", req=[BM],
      check=man("other", 1.2, M, op=">=", extra={"car_area_min": 1.80, "door_min": 0.90, "landing_sliding": 1.20, "landing_swing": 1.50}),
      notes="IFC lift car/shaft dimensions are rarely modelled; needs element kind 'elevator' (see CONTRACT_CHANGES.md). Half of the lifts (rounded down) must meet these dimensions.", needs="Lift car + door dimensions.", deleg=[TSE_ASANSOR, "TS EN 81-70"]))
add(R(34, 4, None, tr="Büyük umumi binalar ve yüksek yapılarda en az 2 asansör; biri yangına dayanıklı", en="Large public / tall buildings: at least 2 lifts; one fire-resistant", cat="circulation", auto="semi", req=[BM], when=aw(),
      check=cu("elevator_required", "building", 2, "lifts", op=">=", tol=0, extra={"part": "count", "min_count": 2, "triggers": ["public building: floor area > 800 m² and > 3 storeys", ">= 10 storeys", "> 20 units above the entrance floor"]}),
      rev="'zemin kat' -> 'bina giriş katı'; 'konut kullanımlı' bağımsız bölüm removed (any unit counts); lift supply 'kesintisiz güç kaynağından' -> 'jeneratörden' (2022 amendment).",
      notes="Lift count from lift elements; the fire-resistance/generator requirement cannot be verified.", needs="Lift count, storeys, floor area, unit count.", deleg=[YANGIN]))
add(R(34, 5, None, tr="10 kat ve üzeri binalarda yük/sedye asansörü: dar kenar >= 1.20 m, alan >= 2.52 m², kapı >= 1.10 m", en="10+ storeys: freight/stretcher lift narrow side >= 1.20 m, area >= 2.52 m², door >= 1.10 m", cat="accessibility", auto="manual", sev="error", req=[BM],
      check=man("other", 2.52, M2, op=">=", extra={"narrow_side": 1.20, "door": 1.10}), needs="Lift car dimensions."))
add(R(34, 8, None, tr="Asansörler bodrum katlar dahil tüm katlara hizmet vermeli", en="Lifts must serve all storeys including basements", cat="circulation", auto="manual", sev="warning", req=[BM],
      check=man("building"), rev="Basements without units/habitable area: 'zorunlu değildir' -> 'en az bir asansörün ulaştırılması zorunludur' (now mandatory).", needs="Lift stops per storey (not in BuildingModel v1)."))
add(R(34, 9, None, tr="Bina girişinden asansöre engelsiz erişim", en="Barrier-free route from the entrance to the lifts", cat="accessibility", auto="manual", sev="warning", req=[BM], check=man("building"), needs="Route analysis.", deleg=[TS9111]))

# ============================================================================================ MADDE 35-37 misc
add(R(35, 2, None, tr="Akaryakıt istasyonlarında yapı yüksekliği en çok 2 kat", en="Fuel stations: building height at most 2 storeys", cat="zoning", auto="manual", sev="warning", req=[BM], check=man("building", 2, "storeys", op="<="), needs="Land-use class + storey count."))
add(R(36, 1, None, tr="Su deposu asgari hacimleri (çok yüksek 30 m³, umumi/yüksek 15 m³, <=10 daire 3 m³, diğer 5 m³, bağ evi 1 m³)", en="Minimum water tank volume (30/15/3/5/1 m³ by building class)", cat="services", auto="manual", sev="warning", req=[BM],
      check=man("space", 3.0, M3, op=">=", extra={"table": {"çok yüksek yapı": 30, "umumi ve yüksek katlı": 15, "konut <= 10 bağımsız bölüm": 3, "diğer": 5, "bağ ve sayfiye evi": 1}}),
      rev="Item (d) bağ ve sayfiye evi 1 m³ added (2022 amendment).", needs="Tank volume.", deleg=[YANGIN]))
add(R(36, 2, None, tr="10 bağımsız bölümden sonra her daire için su deposu +0.50 m³", en="Water tank +0.50 m³ per dwelling beyond 10", cat="services", auto="manual", sev="warning", req=[BM], check=man("space", 0.5, M3), needs="Dwelling count + tank volume."))
add(R(37, 1, None, tr="Pis su kuyusu/fosseptik komşu sınırına 5.00 m'den fazla yaklaştırılmaz", en="Septic tanks must not be closer than 5.00 m to neighbouring boundaries (wording: 'not nearer than 5.00 m')", cat="setbacks", auto="manual", sev="warning", req=[PC],
      check=man("parcel", 5.0, M, op=">="), notes="Text: 'komşu hudutlarına 5.00 metreden fazla yaklaştırılmaz'.", needs="Site plan with tank location."))

# ============================================================================================ MADDE 38 guards
add(R(38, 1, "railing", tr="Korkuluk yüksekliği döşeme kotundan en az 1.10 m", en="Guard height at least 1.10 m above floor level", cat="safety", auto="semi", req=[BM],
      check=mn("railing", "height", 1.10, exceptions=["Merdiven/rampa küpeşteleri (0.90 m / 0.70 m) korkuluk değildir", "Pencere boşluğu korkulukları için KBB-38-1-window"]),
      notes="Applies to balconies, terraces, gallery voids, open stairs, ramps, retaining wall tops, garden walls below 1.10 m, window openings with sill < 0.90 m. IfcRailing also models handrails (0.90 m) -> engine must send handrail-like railings (stair/ramp hosted, height ~0.9) to review.",
      needs="railing.height + railing role (guard vs handrail).", deleg=["TS EN 1991 / TS 12576 (korkuluk yükleri)"]))
add(R(38, 1, "window", tr="Taban döşemesinden itibaren denizliği < 0.90 m olan pencerelerde 1.10 m korkuluk", en="Windows with sill below 0.90 m need a guard up to 1.10 m", cat="safety", auto="semi", req=[BM],
      check=cu("window_sill_guard", "window", 0.9, M, op="<", extra={"sill_threshold": 0.90, "guard_height": 1.10}, exceptions=["Sabit/dönmez camlı ve parapetli boşluklarda korkuluk yerine parapet kabul edilebilir (yorum)"]),
      notes="window.sill_height < 0.90 m requires a railing/parapet >= 1.10 m at the opening. Detecting the guard geometrically near the window is semi: absent railing -> violation candidate, 'review' when a high sill-less glazing or French door is detected.", needs="window.sill_height + nearby railing elements."))
add(R(38, 3, None, tr="Korkuluklar kırılmaz veya dağılmayan malzemeden, tasarım yüklerini karşılayacak şekilde", en="Guards of non-shattering material and designed for load", cat="safety", auto="manual", sev="info", req=[BM], check=man("railing"), needs="Material / structural data."))
add(R(38, 4, None, tr="Korkuluk boşluklarından en fazla 0.10 m çapında geçişe izin", en="Guard openings must not allow passage of more than a 0.10 m diameter", cat="safety", auto="manual", sev="warning", req=[BM], check=man("railing", 0.10, M, op="<="), needs="Baluster spacing (detail geometry)."))

# ============================================================================================ MADDE 39 doors & windows
add(R(39, 1, "a", tr="Kapı yüksekliği en az 2.10 m", en="Door height at least 2.10 m", cat="openings", auto="auto", req=[BM], check=mn("door", "height", 2.10, exceptions=["Teknik kapaklar/revizyon kapıları (yorum)"]),
      notes="'Bütün yapılarda' - all doors; service hatches modelled as doors cause false positives (review hint).", needs="door.height."))
add(R(39, 1, "b", tr="Bina giriş kapısı net genişliği en az 1.50 m (çift kanatlıda kanat >= 1.00 m)", en="Building entrance door clear width at least 1.50 m (each leaf of a double door >= 1.00 m)", cat="openings", auto="semi", req=[BM],
      check=mn("door", "width", 1.50, where={"is_entrance": True, "is_external": True}, exceptions=["Çift kanatlı kapılarda bir kanat >= 1.00 m yeterli sayılır (toplam >= 2.00 m)"]),
      notes="door.is_entrance identifies the main building entrance; leaf count is not modelled so a width < 1.50 m is reported as review when it may be a double door.", needs="door.width (clear), is_entrance, is_external."))
add(R(39, 1, "c", tr="Bağımsız bölüm giriş kapısı >= 1.00 m, diğer kapılar >= 0.90 m (balkon ve tuvalet 0.80 m)", en="Dwelling entrance door >= 1.00 m, other doors >= 0.90 m (balcony and WC doors 0.80 m)", cat="openings", auto="semi", req=[BM],
      check=cu("door_dimensions", "door", 0.90, M, op=">=", extra={"unit_entrance": 1.00, "other": 0.90, "balcony_wc": 0.80, "scope": "width", "building_entrance_rule": "KBB-39-1-b"}, exceptions=["Balkon ve tuvalet kapıları 0.80 m'ye düşürülebilir"]),
      notes="Door classification (dwelling entrance / balcony / WC) is derived from the spaces the door connects (door.space_guids + usage). Unclassifiable doors -> review at 0.90 m. Door heights are handled by KBB-39-1-a.", needs="door.width, door.space_guids with space usage, door.is_entrance."))
add(R(39, 1, "cc", tr="Döner kapılar belirtilen ölçülerde normal kapının yanında ilave olabilir", en="Revolving doors allowed in addition to a normal-size door", cat="openings", auto="manual", sev="info", req=[BM], check=man("door"), needs="-"))
add(R(39, 2, None, tr="Kapılarda eşik yapılamaz (zorunluysa engelli ve yangın çıkışını engellememeli)", en="No door thresholds (if unavoidable, must not hinder disabled access/fire exits)", cat="accessibility", auto="manual", sev="warning", req=[BM], check=man("door"), needs="Detail drawings."))
add(R(39, 3, None, tr="Pencerelerde BEP yönetmeliği ve TSE standartlarına uyulması", en="Windows must comply with the energy-performance regulation and TSE standards", cat="openings", auto="manual", sev="info", req=[BM], check=man("window"), needs="U-values etc.", deleg=["Binalarda Enerji Performansı Yönetmeliği", "TSE pencere standartları"]))
add(R(39, 4, None, tr="Bitişik/blok nizamda komşu parsel sınırındaki bitişik duvarda pencere ve kapı açılamaz", en="No windows/doors in party walls on the neighbour boundary (attached/block order)", cat="openings", auto="manual", sev="error", req=[BM, PC], when=aw(building_order=["adjacent", "block"]),
      check=man("window"), notes="Could become semi: exterior wall within ~0.1 m of the parcel edge with building_order adjacent/block and openings in it.", needs="Wall position vs parcel boundary + openings."))
add(R(39, 5, None, tr="3 kattan fazla, 10 kattan az binalarda her bağımsız bölümün en az bir balkon kapısı net >= 0.90 m", en="Buildings with 4-9 storeys: at least one balcony door per dwelling at least 0.90 m clear (lift transport of goods)", cat="openings", auto="semi", req=[BM], when=aw(min_storeys=4, max_storeys=9),
      check=cu("door_dimensions", "door", 0.90, M, op=">=", usage_in=["balcony"], extra={"scope": "balcony_door", "min_width": 0.90, "per": "dwelling"}, exceptions=["Her bağımsız bölümde en az bir balkon kapısı yeterli"]),
      notes="Balcony doors identified through the adjacent balcony space (usage 'balcony'). Needs dwelling grouping to apply 'at least one per dwelling'.", needs="door.width, adjacent balcony spaces, dwelling grouping."))
add(R(39, 6, "width", tr="Islak hacim havalandırma penceresi en az 0.30 m genişlik (mekanik havalandırma yoksa)", en="Wet-room ventilation window at least 0.30 m wide (when no mechanical ventilation)", cat="openings", auto="semi", req=[BM], sev="warning",
      check=mn("window", "width", 0.30, usage_in=["bathroom", "wc"], exceptions=["Mekanik havalandırma varsa aranmaz"]),
      notes="usage_in on a window target means the usage of the space that lists the window in window_guids. Mechanical ventilation cannot be detected -> engine reports review below the limit.", needs="window.width + host space usage."))
add(R(39, 6, "height", tr="Islak hacim havalandırma penceresi en az 0.30 m yükseklik (mekanik havalandırma yoksa)", en="Wet-room ventilation window at least 0.30 m high (when no mechanical ventilation)", cat="openings", auto="semi", req=[BM], sev="warning",
      check=mn("window", "height", 0.30, usage_in=["bathroom", "wc"], exceptions=["Mekanik havalandırma varsa aranmaz"]), needs="window.height + host space usage."))
add(R(39, 7, None, tr="Atrium/galeri/iç bahçeye bakan camlar kırıldığında dağılmayan özellikte", en="Glazing facing atria/galleries/courtyards must be non-shattering", cat="safety", auto="manual", sev="warning", req=[BM], check=man("window"), needs="Glazing specification."))
add(R(39, 8, None, tr="Bodrum pencereleri zemin seviyesinden en az 0.10 m yukarıdan başlamalı; sel önlemi", en="Basement windows must start at least 0.10 m above ground and be flood-protected", cat="openings", auto="manual", sev="warning", req=[BM, PC],
      check=man("window", 0.10, M, op=">="), notes="window.sill_height is relative to the storey floor, not to the outside ground -> not derivable.", needs="External ground level at the window."))

# ============================================================================================ MADDE 40 roofs
add(R(40, 4, None, tr="Mahya yüksekliği en çok 5.00 m (varsayılan beşik çatı)", en="Ridge height at most 5.00 m (assumed pitched roof)", cat="heights", auto="manual", sev="warning", req=[BM],
      check=man("roof", 5.0, M, op="<="), notes="Ridge relative to the top slab: roof.max_height_z minus top storey elevation + slab; needs a custom check not in the fixed list -> manual for now.", needs="Top slab level + roof.max_height_z."))
add(R(40, 5, None, tr="Merdiven evi, ışıklık, baca vb. çatı örtüsü düzlemini en fazla 0.60 m aşabilir", en="Stair cores, light wells, chimneys may exceed the roof plane by at most 0.60 m", cat="heights", auto="manual", sev="warning", req=[BM], check=man("building", 0.60, M, op="<="), needs="Roof/core geometry."))
add(R(40, 6, None, tr="Teras çatıda 1.10 m parapet veya korkuluk (kullanıma açıksa zorunlu)", en="Terrace roofs: 1.10 m parapet or guard (mandatory when accessible)", cat="safety", auto="manual", req=[BM], sev="error",
      check=man("railing", 1.10, M, op=">="), notes="Handled by the generic KBB-38-1-railing; roof-edge identification is not in the contract so this entry stays informational (manual) and defers to Madde 38.", needs="Roof-edge railings."))
add(R(40, 12, None, tr="Çatıda birden fazla bağımsız bölüme ait terasların arası en az 3.00 m", en="Roof terraces of different units at least 3.00 m apart", cat="other", auto="manual", sev="warning", req=[BM], check=man("slab", 3.0, M, op=">="), needs="Terrace geometry."))
add(R(40, 14, None, tr="Çatı bahçesi: 0.50 m toprak dolgu; kapalı mekân <= %10 ve 20 m², <= 3.00 m yüksekliğinde", en="Roof garden: 0.50 m soil fill ignored; enclosed space <= 10 % and 20 m², height <= 3.00 m", cat="other", auto="manual", sev="warning", req=[BM],
      check=man("building", 20.0, M2, op="<=", extra={"share": 0.10, "height": 3.0, "setback_from_facade": 3.0}), needs="Roof terrace plan."))

# ============================================================================================ MADDE 41 projections
add(R(41, 1, "a.1", tr="Kapalı çıkma: yol cephesinde yaklaşma sınırından en fazla 1.50 m", en="Closed projection on the road facade: at most 1.50 m beyond the building line", cat="setbacks", auto="manual", sev="error", req=[BM, PC],
      check=man("building", 1.5, M, op="<="), notes="Projection geometry vs setback line is not extractable (needs slab/wall classification as 'çıkma').", needs="Projection geometry vs building line."))
add(R(41, 1, "a.2", tr="Kapalı çıkma: arka/yan bahçede parsel sınırına >= 3.00 m kalmak kaydıyla 1.50 m", en="Closed projection in side/rear garden: 1.50 m, keeping >= 3.00 m to the boundary", cat="setbacks", auto="manual", sev="error", req=[BM, PC], check=man("building", 1.5, M, op="<="), needs="As KBB-41-1-a-1."))
add(R(41, 1, "b.1", tr="Açık çıkma: yol cephesinde yaklaşma sınırından en fazla 1.50 m", en="Open projection on the road facade: at most 1.50 m beyond the building line", cat="setbacks", auto="manual", sev="error", req=[BM, PC], check=man("building", 1.5, M, op="<="), needs="As KBB-41-1-a-1."))
add(R(41, 1, "b.2", tr="Açık çıkma: arka/yan bahçede parsel sınırına >= 3.00 m kalmak kaydıyla 1.50 m", en="Open projection in side/rear garden: 1.50 m, keeping >= 3.00 m to the boundary", cat="setbacks", auto="manual", sev="error", req=[BM, PC], check=man("building", 1.5, M, op="<="), needs="As KBB-41-1-a-1."))
add(R(41, 1, "b.4", tr="Bitişik nizamda açık çıkma komşu sınırına 2.00 m'den fazla yaklaşamaz", en="Open projections in attached order must keep 2.00 m from the neighbour boundary", cat="setbacks", auto="manual", sev="error", req=[BM, PC], when=aw(building_order=["adjacent"]),
      check=man("building", 2.0, M, op=">="), needs="Projection geometry vs boundary."))
add(R(41, 2, None, tr="Çıkma altı düşey mesafe en az 2.40 m", en="Clearance under projections at least 2.40 m", cat="safety", auto="manual", sev="error", req=[BM],
      check=man("building", 2.40, M, op=">="), notes="Needs ground level below the projection (site/terrain not modelled).", needs="Terrain + projection soffit levels."))
add(R(41, 3, None, tr="Motif çıkma <= 0.20 m; giriş saçağı genişliği <= 2.50 m, tretuar kotundan >= 2.50 m yukarıda", en="Decorative projection <= 0.20 m; entrance canopy width <= 2.50 m and >= 2.50 m above pavement", cat="setbacks", auto="manual", sev="warning", req=[BM],
      check=man("building", 0.20, M, op="<="), rev="'ısı yalıtımı haricinde' added (2022 amendment).", needs="Facade detail."))
add(R(41, 4, None, tr="Güneş kırıcı en fazla 0.50 m, hafif malzemeden, parsel sınırına taşmaz", en="Sun breakers at most 0.50 m, lightweight, not beyond the parcel boundary", cat="setbacks", auto="manual", sev="warning", req=[BM], check=man("building", 0.50, M, op="<="), needs="Facade detail."))

# ============================================================================================ MADDE 42-43 eaves & garden walls
add(R(42, 1, None, tr="Saçak genişliği en çok 1.00 m (planda belirlenmemişse)", en="Eaves at most 1.00 m (unless fixed by the plan)", cat="setbacks", auto="manual", sev="warning", req=[BM], check=man("roof", 1.0, M, op="<="),
      notes="Roof overhang beyond the facade is not a contract measure; could use roof footprint vs wall footprint.", needs="Roof overhang."))
add(R(42, 2, None, tr="Saçaklar parsel sınırlarını aşamaz", en="Eaves must not exceed parcel boundaries", cat="setbacks", auto="manual", sev="error", req=[PC], check=man("parcel"), needs="Roof outline vs parcel polygon."))
add(R(42, 3, None, tr="Çıkma varsa saçak çıkmadan itibaren en çok 0.50 m", en="With a projection, eaves extend at most 0.50 m beyond it", cat="setbacks", auto="manual", sev="warning", req=[BM], check=man("roof", 0.5, M, op="<="), needs="Roof/projection geometry."))
add(R(43, 1, None, tr="Bahçe duvarı: yol cephesinde <= 0.50 m, cephe gerisinde <= 1.50 m; üzerine <= 1.00 m parmaklık", en="Garden wall: <= 0.50 m on the road side, <= 1.50 m behind the facade line; fence on top <= 1.00 m", cat="safety", auto="semi", req=[BM, PC],
      check=cu("garden_wall_height", "wall", 0.5, M, op="<=", extra={"road_side_max": 0.50, "behind_facade_max": 1.50, "fence_on_top_max": 1.00, "datum_road_side": "curb top (yoldan kotlandırma) / natural ground at road boundary (tabii zemin)", "stepped_when_above_curb": 1.50},
               exceptions=["Güvenlik/gizlilik gerektiren tesislerde, okul, hastane, cezaevi, ibadet yeri, elçilik, sanayi bölgelerinde bu madde uygulanmaz (43(3))", "Bağ-sayfiye ve villa alanlarında 2.00 m'ye kadar (43(4))"]),
      notes="Garden walls are IfcWall(Standard) outside the building: identification by name ('bahçe duvarı') / no storey / site walls. wall.height vs the limit by position relative to the road facade line; needs the parcel and front edge.", needs="Garden-wall elements (wall.height) + parcel polygon + front edge + curb/natural ground level."))
add(R(43, 2, None, tr="Duvar üst kotu tretuvardan 1.50 m'den fazla yükselen eğimli yollarda duvar üstten kademelendirilir", en="On slopes where the wall top rises more than 1.50 m above the pavement, the wall is stepped", cat="safety", auto="manual", sev="info", req=[BM], check=man("wall", 1.5, M, op="<="), needs="Site grading + wall profile."))
add(R(43, 4, None, tr="Bağ-sayfiye parselleri ve tek bağımsız bölümlü (villa) alanlarda yola bakan cephede 2.00 m'ye kadar duvar", en="Villa / weekend-house zones: street-side wall up to 2.00 m", cat="safety", auto="semi", req=[BM, PC],
      check=cu("garden_wall_height", "wall", 2.0, M, op="<=", extra={"part": "villa", "max": 2.0}, exceptions=["Yalnız bağ-sayfiye parselleri ve tek bağımsız bölümlü konut alanlarında"]), rev="Added by the 2022 amendment (new paragraph).",
      notes="Applies instead of KBB-43-1 where ProjectContext.is_single_dwelling is true.", needs="As KBB-43-1 + ProjectContext.is_single_dwelling."))
add(R(43, 5, None, tr="Zemin/bodrumda dükkân olan yapılarda yola bakan bahçede bahçe duvarı yapılamaz", en="No garden wall / pedestrian obstacles on the road side where ground/basement shops are allowed", cat="safety", auto="manual", sev="warning", req=[BM, PC], check=man("wall"), rev="Added by the 2022 amendment (new paragraph).", needs="Site elements + use."))

# ============================================================================================ MADDE 44-47
add(R(44, 1, "a", tr="Kapıcı dairesi: katı yakıtlı binalarda > 40 konut için bir adet (> 80: iki; blok başı > 60: ayrı)", en="Janitor flat: solid-fuel buildings with > 40 dwellings need one (> 80: two; > 60 per block: each)", cat="services", auto="manual", sev="warning", req=[BM],
      check=man("building", 40, "units", op=">"), needs="Dwelling count + heating type + janitor flat presence."))
add(R(44, 1, "b", tr="Kapıcı dairesi: diğer ısıtmada > 30 bağımsız bölüm için bir, > 150 için iki; her ilave 150 daire için bir", en="Janitor flat: other heating, > 30 units one, > 150 two, +1 per further 150", cat="services", auto="manual", sev="warning", req=[BM],
      check=man("building", 30, "units", op=">"), rev="Threshold 60 -> 30 units; per-block calculation sentence added (2022 amendment).", needs="Dwelling count + janitor flat presence."))
add(R(44, 1, "cc", tr="İşyeri/büro binalarında yapı inşaat alanı > 2000 m² ise bekçi odası", en="Offices/commercial buildings > 2000 m²: guard room", cat="services", auto="manual", sev="warning", req=[BM], check=man("building", 2000, M2, op=">"), needs="Gross area + guard room presence."))
add(R(44, 2, "b", tr="Kapıcı dairesi kapı/pencere alt seviyesi taşkın seviyesinin en az 1.50 m üstünde", en="Janitor flat openings at least 1.50 m above flood level (flood-risk areas)", cat="safety", auto="manual", sev="warning", req=[BM, PC], check=man("window", 1.5, M, op=">="), needs="Flood level."))
add(R(44, 2, "c", tr="Toprağa gömülü kapıcı dairesi duvarlarında pencere denizliği zeminden en az 0.90 m", en="Buried janitor flat: window sill at least 0.90 m above ground", cat="openings", auto="manual", sev="warning", req=[BM], check=man("window", 0.90, M, op=">="), needs="External ground level."))
add(R(44, 2, "cc", tr="Bina içi kapıcı dairesi brüt >= 50 m²; 2 yatak odası (>= 9 m², dar kenar >= 2.50 m), oturma >= 12 m², mutfak >= 3.3 m²", en="Indoor janitor flat gross >= 50 m²: 2 bedrooms (>= 9 m², narrow side >= 2.50 m), living >= 12 m², kitchen >= 3.3 m², bath, WC", cat="rooms", auto="manual", sev="warning", req=[BM],
      check=man("space", 50.0, M2, op=">="), notes="Spaces of the janitor flat cannot be identified in IFC without naming conventions.", needs="Janitor flat space group."))
add(R(44, 2, "d", tr="Bina dışı kapıcı dairesi en fazla brüt 40 m²", en="Detached janitor flat at most 40 m² gross", cat="rooms", auto="manual", sev="warning", req=[BM], check=man("building", 40.0, M2, op="<="), needs="Janitor flat area."))
add(R(44, 3, None, tr="Bekçi odası en az 4 m² ve içinde en az 1.5 m² tuvalet", en="Guard room at least 4 m² with a WC of at least 1.5 m²", cat="rooms", auto="manual", sev="warning", req=[BM], check=man("space", 4.0, M2, op=">="), needs="Guard room identification."))
add(R(44, 4, "b", tr="Kontrol kulübesi en fazla 9 m²", en="Control booth at most 9 m²", cat="rooms", auto="manual", sev="warning", req=[BM], check=man("building", 9.0, M2, op="<="), needs="Booth element."))
add(R(44, 4, "c", tr="Kontrol kulübesi yüksekliği en fazla 4.00 m", en="Control booth height at most 4.00 m", cat="heights", auto="manual", sev="warning", req=[BM], check=man("building", 4.0, M, op="<="), needs="Booth element."))
add(R(44, 4, "cc", tr="Kontrol kulübesi ile esas bina arası en az 2.00 m", en="Control booth at least 2.00 m from the main building", cat="setbacks", auto="manual", sev="warning", req=[BM, PC], check=man("building", 2.0, M, op=">="), needs="Site plan."))
add(R(45, 2, None, tr="Portik yüksekliği 3.50 m, derinliği 4.00 m", en="Portico height 3.50 m, depth 4.00 m", cat="circulation", auto="manual", sev="warning", req=[BM, PC], check=man("building", 3.5, M, op="=="),
      notes="Only where the plan requires porticos along a street.", needs="Plan decision + portico geometry."))
add(R(47, 1, "a", tr="Pasaj: tavan yüksekliği >= 3.50 m, uzunluk >= 30.00 m", en="Arcade (pasaj): clear height >= 3.50 m, length >= 30.00 m", cat="circulation", auto="manual", sev="warning", req=[BM], check=man("space", 3.5, M, op=">=", extra={"min_length": 30.0}),
      needs="Arcade space identification.", notes="Would be semi with a usage value for 'arcade'."))
add(R(47, 1, "b", tr="Pasajda her biri >= 1.50 m en az 2 giriş-çıkış kapısı", en="Arcade: at least 2 entrance/exit doors, each >= 1.50 m wide", cat="circulation", auto="manual", sev="warning", req=[BM], check=man("door", 1.5, M, op=">="), needs="Arcade doors."))
add(R(47, 1, "d", tr="Pasajda çarşı bütününde >= 30 m² mescit; çocuk oyun, WC, bebek bakım, ilk yardım alanı", en="Arcade: prayer room >= 30 m², play area, WCs, baby care, first aid", cat="services", auto="manual", sev="warning", req=[BM], check=man("space", 30.0, M2, op=">="), needs="Space programme."))

# ============================================================================================ MADDE 48-49 WCs, tea kitchens
add(R(48, 1, None, tr="Her 25 kişi (resmî/umumî binalarda 50 kişi) için en az birer WC; engelli WC", en="One WC per 25 persons (per 50 in public/official buildings), half women/half men, accessible WC", cat="services", auto="manual", sev="warning", req=[BM],
      check=man("space", 25, "persons", op="<=", usage_in=["wc"]), needs="Occupant load + WC count by gender.", deleg=[TS9111]))
add(R(48, 5, None, tr="Umumî binalarda kapasiteye göre erişilebilirlik standardına uygun engelli tuvaleti", en="Public buildings: accessible WC sized by capacity", cat="accessibility", auto="manual", sev="warning", req=[BM], check=man("space", usage_in=["wc"]), needs="Occupant load.", deleg=[TS9111]))
add(R(49, 1, None, tr="Çay ocağı: kullanma alanı >= 3 m², 0.45 x 0.45 m hava bacası, ateş bacası", en="Tea kitchen: usable area >= 3 m², 0.45 x 0.45 m ventilation shaft, flue", cat="rooms", auto="manual", sev="warning", req=[BM], check=man("space", 3.0, M2, op=">="),
      needs="Tea-kitchen identification (no usage value)."))

# ============================================================================================ MADDE 51-52 basements, annexes
add(R(51, 1, None, tr="Sobalı binalarda daire başına 5-10 m² odunluk/kömürlük/depo (yükseklik <= 2.20 m)", en="Stove-heated buildings: 5-10 m² fuel store per dwelling (height <= 2.20 m if in the garden)", cat="services", auto="manual", sev="warning", req=[BM], check=man("space", 5.0, M2, op=">=", limit_max=10.0, usage_in=["storage"]),
      needs="Heating type + dwelling count.", deleg=["Madde 27(1)(c)"]))
add(R(51, 2, None, tr="Ön bahçesiz binalarda yol cephesinde bodrum girişi yapılamaz", en="Buildings without front garden: no basement entrance on the road facade", cat="circulation", auto="manual", sev="warning", req=[BM, PC], check=man("door"), needs="Door position vs road facade."))
add(R(51, 3, None, tr="Toprağa dayalı bodrumdaki konutlarda oturma odası ve bir yatak odası zemine gömülü olamaz; pencereli", en="Dwellings in earth-retaining basements: living room and one bedroom must not be buried and need windows", cat="openings", auto="manual", sev="error", req=[BM],
      check=man("space", usage_in=["living_room", "bedroom"]), notes="Could become semi with space floor level vs outside ground level.", needs="Ground level vs space floor level."))
add(R(51, 4, None, tr="Ticari bodrumlarda suni havalandırma ve erişilebilir rampa/yürüyen bant", en="Commercial basements: artificial ventilation and accessible ramp/travelator", cat="accessibility", auto="manual", sev="info", req=[BM], check=man("space"), needs="MEP + circulation data."))
add(R(51, 6, None, tr="Toprağa dayalı bodrumlarda ısı ve su yalıtımı zorunlu", en="Thermal and waterproof insulation mandatory in earth-retaining basements", cat="safety", auto="manual", sev="info", req=[BM], check=man("wall"), needs="Wall layer data."))
add(R(51, 7, None, tr="Bina etrafında mütemadi kuranglez yapılamaz; kuranglezden giriş-çıkış yapılamaz", en="No continuous light-well trench around the building; no entrances from it", cat="safety", auto="manual", sev="warning", req=[BM], check=man("space"), needs="Site sections."))
add(R(52, 3, "a", tr="Müştemilat dar kenarı <= 4.00 m, en yüksek noktası tabii zeminden <= 2.50 m", en="Annex building: narrow side <= 4.00 m, top at most 2.50 m above natural ground", cat="heights", auto="manual", sev="warning", req=[BM],
      check=man("building", 4.0, M, op="<=", extra={"max_height": 2.50}), notes="Annexes are not distinguishable from the main building in IFC without naming.", needs="Annex elements + terrain."))
add(R(52, 3, "c", tr="Müştemilat yapı cinsi ahşap olamaz", en="Annex buildings may not be of timber", cat="safety", auto="manual", sev="warning", req=[BM], check=man("building"), needs="Material data."))
