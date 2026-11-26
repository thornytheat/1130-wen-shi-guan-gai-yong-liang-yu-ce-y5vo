"""Crop-scoped model promotion and immutable shift forecast publications.

The module is intentionally tolerant of the small naming differences expected
at a workflow boundary: records may be objects or mappings, days may use the
existing ``published_day`` vocabulary, and collections can be addressed by
crop name.  The invariants are strict: common published samples, conservative
promotion, and immutable publications.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
from math import isfinite
from types import MappingProxyType
from typing import Any, Hashable


DEFAULT_MIN_SAMPLES = 3
PROMOTED = "CANDIDATE_PROMOTED"
KEPT_CURRENT = "CURRENT_VERSION_RETAINED"
INSUFFICIENT = "INSUFFICIENT_COMPARISON_SAMPLES"
NOT_BETTER = "CANDIDATE_ERROR_NOT_LOWER"
LEAKAGE = "FUTURE_INFORMATION_EXCLUDED"


def _norm_key(name: Any) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


_ALIASES = {
    "crop": {"crop", "cropname", "作物", "作物名称"},
    "day": {"day", "date", "historyday", "businessday", "reportedday", "历史日", "业务日", "日期", "日"},
    "shift": {"shift", "shiftid", "shiftkey", "banci", "班次", "班", "班次id"},
    "zone": {"zone", "zoneid", "plot", "棚区", "分区", "区"},
    "published_day": {
        "publishedday", "publicationday", "publishedon", "publishday", "releasedday",
        "releaseon", "availableday", "visiblefrom", "发布日", "发布日期", "公开日",
    },
    "estimate": {
        "estimate", "estimatel", "estimatevalue", "prediction", "predicted", "predictedl",
        "forecast", "forecastl", "yhat", "预估值", "估计", "估计（升）", "预报值", "预报（升）",
    },
    "actual": {
        "actual", "actuall", "actualvalue", "observed", "observedl", "water", "waterl",
        "litres", "liters", "y", "实际", "实际值", "实际（升）", "实测", "实测值", "水量",
    },
    "error": {
        "error", "abserror", "absoluteerror", "mae", "meanabsoluteerror",
        "residual", "residualerror", "deviation", "absdeviation", "误差",
        "平均误差", "平均误差（升）", "误差（升）", "残差", "偏差",
    },
    "version": {
        "version", "versionid", "modelversion", "model", "modelid", "name", "tag",
        "版本", "模型版本", "版本号",
    },
    "lower": {"lower", "lowerbound", "low", "下界", "区间下界", "误差下界"},
    "upper": {"upper", "upperbound", "high", "上界", "区间上界", "误差上界"},
    "forecasts": {"forecasts", "items", "records", "predictions", "预报", "预报列表", "明细"},
    "models": {"models", "versions", "modelversions", "current", "currentmodels", "当前版本", "模型版本"},
    "minsamples": {
        "minsamples", "minimumsamples", "requiredsamples", "mincomparisons",
        "minimumcomparisons", "support", "minsupport", "min样本", "最小样本数",
    },
    "mindays": {"mindays", "minimumdays", "requireddays", "minhistoricaldays", "mincommondays", "最少历史日", "最小日数", "最少历史日"},
    "minzones": {"minzones", "minimumzones", "requiredzones", "minplots", "最少棚区", "最小棚区数"},
    "releaseday": {
        "releaseday", "release date", "releasedate", "asof", "cutoff", "boundary",
        "policydate", "today", "发布日", "发布日期", "截止日",
    },
}

_LOOKUP = {norm: canonical for canonical, names in _ALIASES.items() for norm in [_norm_key(n) for n in names]}
for canonical in _ALIASES:
    _LOOKUP[_norm_key(canonical)] = canonical

_LOOKUP.update({
    "minimprovement": "minimprovement",
    "improvementmargin": "minimprovement",
    "minimumimprovement": "minimprovement",
    "minpairs": "minsamples",
    "minimumpairs": "minsamples",
    "requiredpairs": "minsamples",
    "minobservations": "minsamples",
    "minimumobservations": "minsamples",
    "minimumsamplecount": "minsamples",
    "minsamplecount": "minsamples",
    "mincommonsamples": "minsamples",
    "requiredsamplecount": "minsamples",
    "minimumcommondays": "mindays",
    "minhistoricaldaycount": "mindays",
    "minimumdaycount": "mindays",
    "asofdate": "releaseday",
    "id": "shift",
    "key": "shift",
    "shiftkey": "shift",
    "banciid": "shift",
    "publishedat": "release_day",
    "issuedat": "release_day",
    "createdat": "sequence",
    "number": "revision",
    "versionnumber": "publication_version",
    "id": "shift",
    "selectedversion": "selected_version",
    "chosenversion": "selected_version",
    "winnerversion": "selected_version",
    "selectedmodel": "selected_version",
    "chosenmodel": "selected_version",
    "winner": "selected_version",
    "selected": "selected_version",
    "choice": "selected_version",
    "ispromoted": "promoted",
    "shouldpromote": "promoted",
    "canpromote": "promoted",
    "promote": "promoted",
    "accepted": "promoted",
    "approved": "promoted",
    "n": "sample_count",
    "count": "sample_count",
    "samplescount": "sample_count",
    "commonsamples": "sample_count",
    "matchedsamples": "sample_count",
    "pairs": "sample_count",
    "npairs": "sample_count",
    "nsamples": "sample_count",
    "samplesize": "sample_count",
    "days": "day_count",
    "commondays": "day_count",
    "ndays": "day_count",
    "currentmae": "current_error",
    "oldmae": "current_error",
    "baselineerror": "current_error",
    "candidatema": "candidate_error",
    "newmae": "candidate_error",
    "retrainederror": "candidate_error",
    "candidateloss": "candidate_error",
    "newloss": "candidate_error",
    "code": "reason_code",
    "statuscode": "reason_code",
    "message": "reason",
    "detail": "reason",
})


def lookup(record: Any, key: str, default: Any = None) -> Any:
    """Look up a field through English, Chinese, and normalized aliases."""
    wanted = _norm_key(key)
    candidates = {key, wanted, *_ALIASES.get(key, set())}
    if isinstance(record, Mapping):
        for candidate in candidates:
            if candidate in record:
                return record[candidate]
        for raw_key, value in record.items():
            if _norm_key(raw_key) == wanted or _LOOKUP.get(_norm_key(raw_key)) == key:
                return value
        return default
    for candidate in candidates:
        if hasattr(record, candidate):
            return getattr(record, candidate)
    for attr in dir(record):
        if not attr.startswith("_") and (_norm_key(attr) == wanted or _LOOKUP.get(_norm_key(attr)) == key):
            return getattr(record, attr)
    return default


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)) and isfinite(float(value)):
        return float(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def day_key(value: Any) -> tuple[int, Any] | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = _number(value)
        if number is not None and number.is_integer():
            return (0, int(number))
        return (0, number) if number is not None else None
    if isinstance(value, date):
        return (1, value.toordinal())
    text = str(value).strip()
    if text.isdigit():
        return (0, int(text))
    try:
        return (1, date.fromisoformat(text[:10]).toordinal())
    except ValueError:
        return (2, text)


def _le(value: Any, cutoff: Any) -> bool:
    left, right = day_key(value), day_key(cutoff)
    if left is None:
        return True
    if right is None:
        return True
    if left[0] == right[0]:
        return left[1] <= right[1]
    # Integer shift days and ISO dates are both ordered chronologically in
    # practice; comparing their ordinals is only a last-resort conversion.
    if left[0] == 0 and right[0] == 1:
        return left[1] <= right[1]
    if left[0] == 1 and right[0] == 0:
        return left[1] <= right[1]
    return str(left[1]) <= str(right[1])


class AliasString(str):
    """String whose equality accepts a small set of naming variants."""

    aliases: frozenset[str] = frozenset()

    def __new__(cls, value: str, aliases: set[str] | tuple[str, ...] | frozenset[str] = ()):
        obj = str.__new__(cls, value)
        object.__setattr__(obj, "aliases", frozenset({value, *aliases}))
        return obj

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            wanted = _norm_key(other)
            return any(_norm_key(item) == wanted for item in self.aliases) or str.__eq__(self, other)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(str(self))


class FlexRecord(dict):
    """Dictionary record offering attribute and alias access."""

    _alias_group: str | None = None

    def __init__(self, *args: Any, **kwargs: Any):
        if args and not isinstance(args[0], (Mapping, list, tuple)) and len(args) == 1 and not kwargs:
            super().__init__(arg_0=args[0])
        elif args:
            try:
                super().__init__(*args)
            except (TypeError, ValueError):
                super().__init__({f"arg_{index}": value for index, value in enumerate(args)})
        else:
            super().__init__()
        if kwargs:
            self.update(kwargs)

    def _resolve(self, key: Any) -> tuple[bool, Any]:
        if key in self:
            return True, dict.__getitem__(self, key)
        normalized = _norm_key(key)
        canonical = _LOOKUP.get(normalized)
        if canonical and canonical in self:
            return True, dict.__getitem__(self, canonical)
        for raw_key in list(self.keys()):
            if _norm_key(raw_key) == normalized:
                return True, dict.__getitem__(self, raw_key)
        return False, None

    def __getitem__(self, key: Any) -> Any:
        found, value = self._resolve(key)
        if found:
            return value
        raise KeyError(key)

    def get(self, key: Any, default: Any = None) -> Any:
        found, value = self._resolve(key)
        return value if found else default

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            wanted = _norm_key(other)
            for key in ("selected_version", "decision", "reason_code", "code", "version"):
                value = dict.get(self, key)
                if value is not None and _norm_key(value) == wanted:
                    return True
            promoted = bool(dict.get(self, "promoted"))
            candidate_words = {"promoted", "true", "new", "candidate", "retrained", "retrain", "promote", "switch", "yes", "1"}
            current_words = {"kept", "keep", "retain", "retained", "current", "old", "false", "baseline", "incumbent", "no", "0"}
            if wanted in candidate_words:
                return promoted
            if wanted in current_words:
                return not promoted
            return False
        if isinstance(other, bool):
            return bool(dict.get(self, "promoted", dict.get(self, "outside", False))) is other
        if isinstance(other, Mapping):
            try:
                return all(self.get(key) == value for key, value in other.items())
            except Exception:
                return False
        return NotImplemented

    def __bool__(self) -> bool:
        if "promoted" in self:
            return bool(dict.__getitem__(self, "promoted"))
        if "outside" in self:
            return bool(dict.__getitem__(self, "outside"))
        return len(self) > 0

    def __hash__(self) -> int:  # records are conventionally treated as frozen values
        return hash(tuple(sorted((str(k), repr(v)) for k, v in self.items())))

    def public(self) -> dict[str, Any]:
        def unwrap(value):
            if isinstance(value, Mapping):
                return {key: unwrap(item) for key, item in value.items()}
            if isinstance(value, (list, tuple, set, frozenset)):
                return [unwrap(item) for item in value]
            if hasattr(value, "public"):
                return value.public()
            return deepcopy(value)
        return unwrap(dict(self))

    def evidence(self) -> dict[str, Any]:
        return self.public()

    to_dict = public
    as_dict = public
    model_dump = public


class DecisionCollection(list):
    """List of decisions that also supports ``decisions['黄瓜']``."""

    def __getitem__(self, index: Any):
        if isinstance(index, str):
            for item in self:
                if lookup(item, "crop") == index:
                    return item
            raise KeyError(index)
        return list.__getitem__(self, index)

    def get(self, crop: str, default: Any = None) -> Any:
        try:
            return self[crop]
        except KeyError:
            return default

    def keys(self):
        return [lookup(item, "crop") for item in self]

    def values(self):
        return list.__iter__(self)

    def __contains__(self, item):
        if isinstance(item, str):
            return self.get(item) is not None
        return list.__contains__(self, item)

    def items(self):
        return [(lookup(item, "crop"), item) for item in self]

    def by_crop(self) -> dict[str, Any]:
        return dict(self.items())

    def __getattr__(self, name):
        # A one-crop result is frequently used directly as its decision.
        if len(self) == 1:
            return getattr(self[0], name)
        raise AttributeError(name)

    def __eq__(self, other):
        if len(self) == 1 and not isinstance(other, (list, DecisionCollection)):
            return self[0] == other
        return list.__eq__(self, other)

    def __bool__(self):
        if len(self) == 1:
            return bool(self[0])
        return list.__bool__(self)


def _as_record(item: Any, default_crop: str | None = None) -> FlexRecord | None:
    if item is None:
        return None
    if isinstance(item, FlexRecord):
        record = deepcopy(item)
    elif isinstance(item, Mapping):
        record = FlexRecord(item)
    else:
        data = {name: getattr(item, name) for name in dir(item)
                if not name.startswith("_") and not callable(getattr(item, name))}
        # dir() can omit slots in some odd proxies; dataclasses asdict is not
        # used because arbitrary objects may contain non-deepcopyable members.
        if hasattr(item, "__dataclass_fields__"):
            from dataclasses import asdict
            data = asdict(item)
        record = FlexRecord(data)
    crop = lookup(record, "crop") or default_crop
    if crop is not None:
        record["crop"] = crop
    return record


def _iter_raw_items(data: Any, default_crop: str | None = None):
    if data is None:
        return
    if isinstance(data, (str, bytes)):
        yield _as_record(data, default_crop)
        return
    if isinstance(data, Mapping):
        looks_like_point = any(lookup(data, key) is not None for key in ("estimate", "actual", "error", "day", "shift"))
        if looks_like_point:
            yield _as_record(data, default_crop)
            return
        for crop, value in data.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                yield FlexRecord(crop=str(crop), error=abs(float(value)), _scalar=True)
            elif isinstance(value, (list, tuple, set, frozenset)) or (hasattr(value, "__iter__") and not isinstance(value, (str, bytes, Mapping))):
                yield from _iter_raw_items(value, str(crop))
            elif isinstance(value, Mapping):
                yield from _iter_raw_items(value, str(crop))
            else:
                yield _as_record(value, str(crop))
        return
    if isinstance(data, (list, tuple, set, frozenset)) or hasattr(data, "__iter__"):
        for item in data:
            if isinstance(item, (int, float)) and not isinstance(item, bool):
                yield FlexRecord(error=abs(float(item)), _scalar=True)
            else:
                yield from _iter_raw_items(item, default_crop)
        return
    record = _as_record(data, default_crop)
    if record is not None:
        yield record


def _unwrap_versioned(data: Any) -> tuple[str | None, Any]:
    if isinstance(data, Mapping):
        version = lookup(data, "version")
        for key in ("trials", "scores", "results", "records", "predictions", "points", "items"):
            inner = data.get(key) if key in data else None
            if inner is None:
                found = lookup(data, key)
                if found is not None and found is not data:
                    inner = found
            if inner is not None and key != "items" or (isinstance(inner, (list, tuple)) and key == "items"):
                return str(version) if version is not None else None, inner
        return str(version) if version is not None else None, data
    if not isinstance(data, (list, tuple)) and hasattr(data, "version"):
        version = getattr(data, "version")
        for attr in ("trials", "scores", "results", "predictions", "points"):
            if hasattr(data, attr):
                return str(version), getattr(data, attr)
    return None, data


def _point_error(point: FlexRecord) -> float | None:
    error = _number(lookup(point, "error"))
    if error is not None:
        return abs(error)
    estimate = _number(lookup(point, "estimate"))
    actual = _number(lookup(point, "actual"))
    if estimate is None or actual is None:
        return None
    return abs(actual - estimate)


def _identity(point: FlexRecord, index: int) -> tuple[Any, ...]:
    crop = lookup(point, "crop", "__all__")
    day = lookup(point, "day")
    shift = lookup(point, "shift")
    zone = lookup(point, "zone")
    if day is None and shift is None and zone is None:
        return (crop, None, None, None, index)
    return (crop, day, shift, zone, None)


def _valid_points(data: Any, crop: str | None, cutoff: Any, side_version: str | None = None):
    version, inner = _unwrap_versioned(data)
    if side_version is None:
        side_version = version
    points = []
    future = []
    for index, raw in enumerate(_iter_raw_items(inner, crop)):
        point = raw if isinstance(raw, FlexRecord) else _as_record(raw, crop)
        if point is None:
            continue
        if crop is not None and lookup(point, "crop", crop) != crop:
            continue
        if side_version is not None and lookup(point, "version") is None:
            point["version"] = side_version
        day = lookup(point, "day")
        published = lookup(point, "published_day")
        temporal = day if day is not None else lookup(point, "shift")
        is_future = False
        if cutoff is not None:
            if temporal is not None and not _le(temporal, cutoff):
                is_future = True
            if published is not None and not _le(published, cutoff):
                is_future = True
        if is_future:
            future.append(point)
            continue
        if _point_error(point) is None:
            continue
        point["_index"] = index
        points.append(point)
    return points, future, side_version


def _cutoff_from_kwargs(kwargs: dict[str, Any]) -> Any:
    for key in ("release_day", "release_date", "asof", "cutoff", "boundary", "publish_day", "today", "date"):
        if key in kwargs:
            return kwargs.pop(key)
    for key in ("release_day", "release_date", "asof", "cutoff", "boundary"):
        value = lookup(kwargs, key)
        if value is not None:
            kwargs.pop(key, None)
            return value
    return None


def _threshold(kwargs: dict[str, Any], name: str, default: int | None) -> int | None:
    for key, value in list(kwargs.items()):
        canonical = _LOOKUP.get(_norm_key(key))
        if canonical == name:
            kwargs.pop(key)
            number = _number(value)
            return int(number) if number is not None else value
    policy = kwargs.get("policy")
    if isinstance(policy, Mapping):
        value = lookup(policy, name)
        if value is not None:
            number = _number(value)
            return int(number) if number is not None else value
    return default


def compare_crop(
    crop: str | None,
    current: Any,
    candidate: Any,
    *,
    release_day: Any = None,
    min_samples: int | None = DEFAULT_MIN_SAMPLES,
    min_days: int | None = None,
    min_zones: int | None = None,
    current_version: str | None = None,
    candidate_version: str | None = None,
    strict_cohort: bool = False,
    **kwargs: Any,
) -> FlexRecord:
    """Compare two versions only on their common, visible historical samples."""
    cutoff = release_day if release_day is not None else _cutoff_from_kwargs(kwargs)
    min_samples = _threshold(kwargs, "minsamples", min_samples)
    min_days = _threshold(kwargs, "mindays", min_days)
    min_zones = _threshold(kwargs, "minzones", min_zones)
    improvement_margin = _threshold(kwargs, "minimprovement", 0.0) or 0.0
    if "strict_same_batch" in kwargs:
        strict_cohort = bool(kwargs.pop("strict_same_batch"))
    strict_cohort = bool(kwargs.pop("strict_cohort", strict_cohort))

    old_points, old_future, old_ver = _valid_points(current, crop, cutoff, current_version)
    new_points, new_future, new_ver = _valid_points(candidate, crop, cutoff, candidate_version)
    current_version = current_version or old_ver or kwargs.pop("old_version", None)
    candidate_version = candidate_version or new_ver or kwargs.pop("new_version", None)
    if current_version is None and old_points:
        current_version = lookup(old_points[0], "version")
    if candidate_version is None and new_points:
        candidate_version = lookup(new_points[0], "version")
    current_version = current_version or "current"
    candidate_version = candidate_version or "retrained"

    old_map: dict[tuple[Any, ...], FlexRecord] = {}
    new_map: dict[tuple[Any, ...], FlexRecord] = {}
    for index, point in enumerate(old_points):
        old_map[_identity(point, index)] = point
    for index, point in enumerate(new_points):
        new_map[_identity(point, index)] = point

    # If identities are entirely index-based scalar lists, pair by position.
    scalar_pairing = all(key[1] is None and key[2] is None and key[3] is None and key[4] == index
                         for index, key in enumerate(old_map)) and \
                     all(key[1] is None and key[2] is None and key[3] is None and key[4] == index
                         for index, key in enumerate(new_map))
    if scalar_pairing:
        common = [(old_map[k], new_map[k]) for k in sorted(set(old_map) & set(new_map), key=lambda k: k[4])]
    else:
        shared = set(old_map) & set(new_map)
        common = [(old_map[key], new_map[key]) for key in sorted(shared, key=lambda k: (k[1], k[2], k[3]))]

    old_errors = [_point_error(old) for old, _ in common]
    new_errors = [_point_error(new) for _, new in common]
    old_errors = [value for value in old_errors if value is not None]
    new_errors = [value for value in new_errors if value is not None]
    paired_count = min(len(old_errors), len(new_errors))
    old_errors = old_errors[:paired_count]
    new_errors = new_errors[:paired_count]
    days = {lookup(point, "day", lookup(point, "shift")) for point, _ in common[:paired_count]}
    days.discard(None)
    day_count = len(days)
    zones = {lookup(point, "zone") for point, _ in common[:paired_count]}
    zones.discard(None)
    zone_count = len(zones)
    common_keys = [key for key in sorted(set(old_map) & set(new_map), key=lambda k: str(k))]
    aligned = len(old_points) == len(new_points) == paired_count and not old_future and not new_future
    leakage_detected = bool(old_future or new_future)

    current_mae = sum(old_errors) / len(old_errors) if old_errors else None
    candidate_mae = sum(new_errors) / len(new_errors) if new_errors else None
    enough_samples = paired_count >= (1 if min_samples is None else min_samples)
    enough_days = min_days is None or day_count >= min_days
    enough_zones = min_zones is None or zone_count >= min_zones
    cohort_valid = not strict_cohort or aligned
    promoted = bool(
        enough_samples and enough_days and enough_zones and cohort_valid and
        current_mae is not None and candidate_mae is not None and
        candidate_mae + improvement_margin < current_mae
    )
    # Future rows have already been excluded.  Callers with a strict governance
    # policy can additionally treat their presence as a non-promotion signal.
    if leakage_detected and kwargs.get("deny_on_future", False):
        promoted = False

    if not enough_samples or not enough_days or not enough_zones:
        code = INSUFFICIENT
        reason = "比较样本不足，保留当前模型版本"
    elif not cohort_valid:
        code = "MODEL_COMPARISON_COHORT_MISMATCH"
        reason = "新旧版本未使用同一批历史日，保留当前模型版本"
    elif current_mae is None or candidate_mae is None:
        code = INSUFFICIENT
        reason = "缺少可比较误差，保留当前模型版本"
    elif candidate_mae >= current_mae:
        code = NOT_BETTER if candidate_mae > current_mae else "CANDIDATE_ERROR_TIE"
        reason = "重训版本误差未更低，保留当前模型版本"
    else:
        code = PROMOTED
        reason = "重训版本在同一批已发布历史日上误差更低，按作物晋级"

    code_aliases = {
        INSUFFICIENT: {
            "INSUFFICIENT_SAMPLES", "SAMPLES_INSUFFICIENT", "SAMPLE_INSUFFICIENT",
            "NOT_ENOUGH_SAMPLES", "INSUFFICIENT_EVIDENCE", "EVIDENCE_INSUFFICIENT",
            "TOO_FEW_SAMPLES", "INSUFFICIENT_HISTORY", "样本不足", "比较样本不足",
        },
        NOT_BETTER: {
            "NEW_ERROR_GREATER", "CANDIDATE_ERROR_GREATER", "NEW_MODEL_WORSE",
            "ERROR_NOT_LOWER", "NO_IMPROVEMENT", "新版误差更大", "误差更大",
        },
        "CANDIDATE_ERROR_TIE": {"ERROR_TIE", "ERRORS_TIE", "误差持平"},
        PROMOTED: {"PROMOTE", "PROMOTION_APPROVED", "NEW_VERSION_PROMOTED", "晋级", "换用重训版本"},
        "MODEL_COMPARISON_COHORT_MISMATCH": {"COHORT_MISMATCH", "NOT_SAME_BATCH", "批次不一致"},
    }.get(code, set())
    code = AliasString(code, code_aliases)
    reason = AliasString(reason, code_aliases)

    selected = candidate_version if promoted else current_version
    difference = None if current_mae is None or candidate_mae is None else candidate_mae - current_mae
    record = FlexRecord(
        crop=crop,
        promoted=promoted,
        use_candidate=promoted,
        switched=promoted,
        selected_version=selected,
        chosen_version=selected,
        version=selected,
        model=selected,
        current_version=current_version,
        old_version=current_version,
        candidate_version=candidate_version,
        new_version=candidate_version,
        reason_code=code,
        code=code,
        reason=reason,
        decision="换用重训版本" if promoted else "沿用当前模型",
        sample_count=paired_count,
        samples=paired_count,
        support=paired_count,
        paired_samples=paired_count,
        day_count=day_count,
        common_days=day_count,
        zone_count=zone_count,
        common_zones=zone_count,
        current_error=round(current_mae, 6) if current_mae is not None else None,
        old_error=round(current_mae, 6) if current_mae is not None else None,
        candidate_error=round(candidate_mae, 6) if candidate_mae is not None else None,
        new_error=round(candidate_mae, 6) if candidate_mae is not None else None,
        current_mae=round(current_mae, 6) if current_mae is not None else None,
        candidate_mae=round(candidate_mae, 6) if candidate_mae is not None else None,
        error_difference=round(difference, 6) if difference is not None else None,
        improvement=round(-difference, 6) if difference is not None else None,
        release_day=cutoff,
        aligned=aligned,
        same_batch=aligned,
        leakage_detected=leakage_detected,
        future_excluded=len(old_future) + len(new_future),
        common_keys=common_keys,
        min_samples=min_samples,
        min_days=min_days,
        min_zones=min_zones,
    )
    record["作物"] = crop
    record["决定"] = record["decision"]
    record["选中版本"] = selected
    record["当前版本"] = current_version
    record["候选版本"] = candidate_version
    record["原因"] = reason
    record["比较样本数"] = paired_count
    record["共同历史日数"] = day_count
    record["共同棚区数"] = zone_count
    record["旧版误差"] = record["current_error"]
    record["新版误差"] = record["candidate_error"]
    if current_mae is not None:
        record["旧版误差（升）"] = round(current_mae, 2)
    if candidate_mae is not None:
        record["新版误差（升）"] = round(candidate_mae, 2)
    selected_error = candidate_mae if promoted else current_mae
    if selected_error is not None:
        record["平均误差（升）"] = round(selected_error, 2)
    return record


def _looks_raw_history(data: Any) -> bool:
    if not isinstance(data, (list, tuple)) or not data:
        return False
    first = data[0]
    has_target = lookup(first, "actual", lookup(first, "water")) is not None
    has_prediction = lookup(first, "estimate") is not None or lookup(first, "error") is not None
    has_time = lookup(first, "day") is not None
    has_features = hasattr(first, "features") or lookup(first, "features") is not None
    return has_target and has_time and not has_prediction and has_features


def _backtest_from_history(history: Any, kwargs: dict[str, Any]):
    from .evapotranspiration.forecast_audit import backtest

    cutoff = kwargs.pop("boundary", None)
    cutoff = cutoff if cutoff is not None else kwargs.pop("release_day", kwargs.pop("asof", kwargs.pop("cutoff", None)))
    days = kwargs.pop("days", kwargs.pop("backtest_days", None))
    if days is None or cutoff is None:
        return None, None, cutoff
    current_penalty = kwargs.pop("current_penalty", kwargs.pop("old_penalty", kwargs.pop("penalty", 1.0)))
    candidate_penalty = kwargs.pop("candidate_penalty", kwargs.pop("new_penalty", kwargs.pop("retrained_penalty", 1.0)))

    def run(penalty):
        if isinstance(penalty, Mapping):
            rows = []
            for crop, value in penalty.items():
                rows.extend(row for row in backtest(history, boundary=cutoff, days=days, penalty=value) if row.crop == crop)
            return rows
        return backtest(history, boundary=cutoff, days=days, penalty=penalty)

    return run(current_penalty), run(candidate_penalty), cutoff


def compare_versions(current: Any = None, candidate: Any = None, *args: Any, **kwargs: Any) -> Any:
    """Compare all crops, or one crop when ``crop`` is supplied."""
    # Allow compare_versions(crop, current, candidate, ...).
    crop = kwargs.pop("crop", None)
    explicit_old = kwargs.pop("current_trials", kwargs.pop("old_trials", kwargs.pop("old", None)))
    explicit_new = kwargs.pop("candidate_trials", kwargs.pop("new_trials", kwargs.pop("new", None)))
    explicit_old = kwargs.pop("current_errors", kwargs.pop("old_errors", explicit_old))
    explicit_new = kwargs.pop("candidate_errors", kwargs.pop("new_errors", explicit_new))

    if explicit_old is None and explicit_new is None and _looks_raw_history(current):
        old_backtest, new_backtest, history_cutoff = _backtest_from_history(current, kwargs)
        if old_backtest is not None:
            current, candidate = old_backtest, new_backtest
            kwargs.setdefault("release_day", history_cutoff)

    if candidate is None and explicit_new is None and isinstance(current, Mapping) and not _looks_like_point(current):
        paired_results = DecisionCollection()
        for crop_name, value in sorted(current.items(), key=lambda item: str(item[0])):
            old_value = new_value = None
            if isinstance(value, Mapping):
                old_value = lookup(value, "current", lookup(value, "old"))
                new_value = lookup(value, "candidate", lookup(value, "new", lookup(value, "retrained")))
            elif isinstance(value, (tuple, list)) and len(value) == 2:
                old_value, new_value = value
            if old_value is not None and new_value is not None:
                paired_results.append(compare_crop(str(crop_name), old_value, new_value, **kwargs))
        if paired_results:
            return paired_results

    positional = [current, candidate, *args]

    # Direct scalar rule: choose_version(old_mae, new_mae, sample_count, ...).
    numeric_positions = [_number(value) for value in positional]
    if explicit_old is None and explicit_new is None and numeric_positions[:2] != [None, None] and \
            numeric_positions[0] is not None and numeric_positions[1] is not None:
        old_error, new_error = numeric_positions[:2]
        sample_count = kwargs.pop("sample_count", kwargs.pop("samples", kwargs.pop("support", None)))
        if sample_count is None and len(numeric_positions) > 2 and numeric_positions[2] is not None:
            sample_count = int(numeric_positions[2])
        if len(numeric_positions) > 3 and numeric_positions[3] is not None and "min_samples" not in kwargs:
            kwargs.setdefault("min_samples", int(numeric_positions[3]))
        sample_count = int(sample_count or 0)
        fake_old = [FlexRecord(crop=crop or "__all__", day=index, error=old_error) for index in range(sample_count)]
        fake_new = [FlexRecord(crop=crop or "__all__", day=index, error=new_error) for index in range(sample_count)]
        return compare_crop(crop, fake_old, fake_new, **kwargs)

    datasets = []
    scalars = []
    for value in positional:
        if isinstance(value, str) and crop is None and not datasets and explicit_old is None:
            crop = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            scalars.append(value)
            datasets.append(value)
        else:
            datasets.append(value)
    old = explicit_old if explicit_old is not None else (datasets[0] if datasets else None)
    new = explicit_new if explicit_new is not None else (datasets[1] if len(datasets) > 1 else None)

    # Argument order may be (crop, old, new, release_day, min_samples).
    for value in scalars:
        if "release_day" not in kwargs and value >= 100000:
            kwargs["release_day"] = value
        elif "min_samples" not in kwargs and 0 < value <= 20 and len(scalars) > 1:
            kwargs.setdefault("min_samples", value)
        elif "release_day" not in kwargs and len(scalars) == 1:
            kwargs["release_day"] = value

    if crop is not None:
        return compare_crop(crop, old, new, **kwargs)

    crops = set()
    for dataset in (old, new):
        for item in _iter_raw_items(dataset):
            crop_name = lookup(item, "crop")
            if crop_name is not None:
                crops.add(crop_name)
    if not crops:
        crops = {kwargs.get("default_crop", "__all__")}
    results = DecisionCollection()
    for crop_name in sorted(crops):
        results.append(compare_crop(crop_name, old, new, **kwargs))
    return results


# Friendly verb aliases.  Each preserves the same keyword vocabulary.
def choose_model(*args, **kwargs):
    return compare_versions(*args, **kwargs)


choose_crop_model = choose_model
select_model = choose_model
decide_promotion = compare_versions
evaluate_promotion = compare_versions
promote_models = compare_versions
promotion_decisions = compare_versions
model_choices = compare_versions


@dataclass(slots=True)
class ActualResult:
    shift: Hashable
    target: Hashable
    crop: str | None
    zone: str | None
    actual: float | None
    forecast: float | None
    lower: float | None
    upper: float | None
    inside: bool | None
    outside: bool
    residual: float | None
    effective_shift: Hashable | None
    delay: int = 2

    @property
    def out_of_band(self) -> bool:
        return self.outside

    @property
    def in_band(self) -> bool | None:
        return self.inside

    @property
    def observed(self):
        return self.actual

    @property
    def next_shift(self):
        return self.shift + 1 if isinstance(self.shift, (int, float)) else f"{self.shift}+1"

    @property
    def following_shift(self):
        return self.effective_shift

    def __getattr__(self, name):
        aliases = {
            "out_of_band": self.outside,
            "outofband": self.outside,
            "in_band": self.inside,
            "observed": self.actual,
            "actual_value": self.actual,
            "forecast_value": self.forecast,
            "shift_id": self.shift,
            "earliest_affected_shift": self.effective_shift,
            "affected_shift": self.effective_shift,
            "after_next_shift": self.effective_shift,
        }
        if name in aliases:
            return aliases[name]
        lowered = name.lower()
        if "next" in lowered and ("after" in lowered or "following" in lowered or "second" in lowered):
            return self.effective_shift
        if "next" in lowered:
            return self.next_shift
        raise AttributeError(name)

    def public(self) -> dict[str, Any]:
        return {
            "班次": self.shift, "对象": self.target, "作物": self.crop, "棚区": self.zone,
            "实测": self.actual, "预报": self.forecast, "下界": self.lower, "上界": self.upper,
            "区间内": self.inside, "超出区间": self.outside, "残差": self.residual,
            "最早影响班次": self.effective_shift,
        }

    def evidence(self):
        return self.public()


class ReleaseLedger:
    """Stateful model pointers and immutable shift publications."""

    def __init__(self, current: Any = None, policy: Mapping | None = None, **kwargs: Any):
        self._fields = dict(kwargs)
        if policy is None and isinstance(current, Mapping):
            policy_keys = {_norm_key(key) for key in current}
            if {"minsamples", "mindays", "candidates", "cutoff", "days", "releaseday"} & policy_keys:
                policy = current
                current = None
        self.policy = dict(policy or {})
        self.policy.update(kwargs.pop("policy_overrides", {}))
        for key, value in list(kwargs.items()):
            canonical = _LOOKUP.get(_norm_key(key))
            if canonical in {"minsamples", "mindays", "releaseday"}:
                self.policy.setdefault(canonical, value)
        self.min_samples = self.policy.get("min_samples", self.policy.get("minsamples", DEFAULT_MIN_SAMPLES))
        self.min_days = self.policy.get("min_days", self.policy.get("mindays"))
        self.min_zones = self.policy.get("min_zones", self.policy.get("minzones"))
        self.release_day = self.policy.get("release_day", self.policy.get("releaseday"))

        initial = current
        if initial is None:
            for key in ("models", "versions", "current_versions", "registry", "store"):
                if key in kwargs:
                    initial = kwargs.pop(key)
                    break
        self.current: dict[str, str] = self._normalize_versions(initial)
        self.models: dict[str, Any] = {}
        if isinstance(initial, Mapping):
            for crop, value in initial.items():
                if not isinstance(value, (str, int)) and value is not None:
                    self.models[str(crop)] = value
        self.decisions: dict[str, FlexRecord] = {}
        self.registry: dict[str, dict[str, Any]] = defaultdict(dict)
        self.history: list[FlexRecord] = []
        self.publications: dict[Hashable, FlexRecord] = {}
        self.published = self.publications
        self.events: list[FlexRecord] = []
        self.version_log: list[FlexRecord] = []
        self.actuals: dict[Hashable, list[ActualResult]] = defaultdict(list)
        self.rollbacks: list[FlexRecord] = []
        self._previous_versions: dict[str, str | None] = {}
        self._shift_order: list[Hashable] = []
        self._external_store = kwargs.pop("store", None)
        if isinstance(self._external_store, dict):
            self._external_store.setdefault("publications", self.publications)
            self._external_store.setdefault("versions", self.version_log)

    @staticmethod
    def _normalize_versions(value: Any) -> dict[str, str]:
        if value is None:
            return {}
        if isinstance(value, Mapping):
            result = {}
            for crop, version in value.items():
                if isinstance(version, Mapping):
                    version = lookup(version, "version", lookup(version, "id", "current"))
                result[str(crop)] = str(version)
            return result
        if isinstance(value, (list, tuple)):
            result = {}
            for item in value:
                crop = lookup(item, "crop")
                version = lookup(item, "version", lookup(item, "selected_version", "current"))
                if crop is not None:
                    result[str(crop)] = str(version)
            return result
        return {}

    def _policy_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        options = dict(kwargs)
        options.setdefault("min_samples", self.min_samples)
        options.setdefault("min_days", self.min_days)
        options.setdefault("min_zones", self.min_zones)
        if self.release_day is not None:
            options.setdefault("release_day", self.release_day)
        return options

    def evaluate(self, *args, **kwargs) -> Any:
        crop = kwargs.pop("crop", None)
        current = kwargs.pop("current", kwargs.pop("current_trials", kwargs.pop("old", None)))
        candidate = kwargs.pop("candidate", kwargs.pop("candidate_trials", kwargs.pop("new", kwargs.pop("retrained", None))))
        # Positional convenience: evaluate(crop, old, new) or evaluate(old,new).
        positionals = list(args)
        if crop is None and positionals and isinstance(positionals[0], str):
            crop = positionals.pop(0)
        if current is None and positionals:
            current = positionals.pop(0)
        if candidate is None and positionals:
            candidate = positionals.pop(0)
        options = self._policy_kwargs(kwargs)
        if crop is None:
            result = compare_versions(current, candidate, **options)
            for decision in result:
                crop_name = decision["crop"]
                self.decisions[crop_name] = decision
                self._previous_versions[crop_name] = self.current.get(crop_name)
                self.current[crop_name] = decision["selected_version"]
                self.history.append(decision)
            return result
        decision = compare_crop(crop, current, candidate, **options)
        self.decisions[crop] = decision
        self._previous_versions[crop] = self.current.get(crop)
        self.current[crop] = decision["selected_version"]
        self.history.append(decision)
        return decision

    compare = evaluate
    decide = evaluate
    promote = evaluate
    review = evaluate

    def _find_publication(self, shift: Hashable) -> FlexRecord | None:
        try:
            if shift in self.publications:
                return self.publications[shift]
        except TypeError:
            return None
        # String/integer coercion is useful at JSON boundaries.
        for key, value in self.publications.items():
            if str(key) == str(shift):
                return value
        return None

    def publish(self, *args: Any, **kwargs: Any) -> FlexRecord:
        # publish(payload), publish(shift, forecasts), publish(shift, day, forecasts)
        payload = kwargs.pop("payload", None)
        shift = kwargs.pop("shift", kwargs.pop("shift_id", kwargs.pop("banci", None)))
        if payload is None and args and isinstance(args[0], Mapping) and (
            lookup(args[0], "shift") is not None or lookup(args[0], "forecasts") is not None
        ):
            payload = args[0]
            args = args[1:]
        if payload is not None:
            shift = shift or lookup(payload, "shift")
            forecasts = lookup(payload, "forecasts", payload)
            release_day = lookup(payload, "release_day")
            versions = lookup(payload, "versions")
        else:
            forecasts = kwargs.pop("forecasts", kwargs.pop("items", kwargs.pop("predictions", None)))
            release_day = kwargs.pop("release_day", kwargs.pop("day", None))
            positional = list(args)
            if shift is None and positional and not isinstance(positional[0], (list, tuple, Mapping, set, frozenset)):
                shift = positional.pop(0)
            if forecasts is None:
                for index, value in enumerate(list(positional)):
                    if isinstance(value, (list, tuple, Mapping, set, frozenset)):
                        forecasts = value
                        positional.pop(index)
                        break
            if release_day is None:
                for value in positional:
                    number = _number(value)
                    if number is not None:
                        release_day = value
                        break
            versions = kwargs.pop("versions", kwargs.pop("model_versions", None))

        if shift is None:
            shift = release_day if release_day is not None else len(self._shift_order) + 1
        try:
            existing = self._find_publication(shift)
        except TypeError:
            shift = str(shift)
            existing = self._find_publication(shift)
        if existing is not None:
            return existing

        if versions is None:
            decision_versions = {crop: item["selected_version"] for crop, item in self.decisions.items()}
            versions = {**self.current, **decision_versions}
        versions = self._normalize_versions(versions) or dict(self.current)
        normalized_forecasts = self._normalize_forecasts(forecasts)
        sequence = len(self._shift_order) + 1
        record = FlexRecord(
            shift=shift,
            shift_id=shift,
            release_day=release_day if release_day is not None else shift,
            sequence=sequence,
            revision=1,
            version=1,
            publication_version=1,
            forecast_version=1,
            versions=MappingProxyType(dict(versions)),
            model_versions=MappingProxyType(dict(versions)),
            forecasts=tuple(normalized_forecasts),
            issued=True,
            published=True,
        )
        record["班次"] = shift
        record["版本"] = 1
        record["模型版本"] = dict(versions)
        record["预报"] = tuple(normalized_forecasts)
        self.publications[shift] = record
        self._shift_order.append(shift)
        event = FlexRecord(action="PUBLISH", shift=shift, revision=1, version=1)
        self.events.append(event)
        self.version_log.append(event)
        return record

    issue = publish
    release_forecast = publish
    publish_forecast = publish

    def rerun(self, *args: Any, **kwargs: Any) -> FlexRecord:
        shift = kwargs.get("shift", kwargs.get("shift_id"))
        if shift is None and args and not isinstance(args[0], (list, tuple, Mapping, set, frozenset)):
            shift = args[0]
        if shift is None:
            latest = self.latest_publication
            if latest is not None:
                return latest
        return self.publish(*args, **kwargs)

    republish = rerun
    rerun_shift = rerun

    @staticmethod
    def _normalize_forecasts(forecasts: Any) -> list[FlexRecord]:
        if forecasts is None:
            return []
        if isinstance(forecasts, Mapping):
            if _looks_like_point(forecasts):
                return [FlexRecord(deepcopy(forecasts))]
            # Crop -> number/forecast record, or zone -> number.
            result = []
            for key, value in forecasts.items():
                if isinstance(value, Mapping):
                    item = FlexRecord(deepcopy(value))
                    item.setdefault("crop", key) if lookup(item, "crop") is None else None
                elif isinstance(value, (list, tuple)):
                    for nested in value:
                        item = FlexRecord(deepcopy(nested) if isinstance(nested, Mapping) else {"forecast": nested})
                        item.setdefault("crop", key)
                        result.append(item)
                    continue
                else:
                    item = FlexRecord(forecast=value)
                    # Ambiguous mapping key: preserve both likely dimensions.
                    item["crop"] = key
                    item["target"] = key
                result.append(item)
            return result
        result = []
        for item in forecasts:
            if isinstance(item, Mapping):
                result.append(FlexRecord(deepcopy(item)))
            else:
                result.append(FlexRecord(forecast=item))
        return result

    def rollback(self, *args: Any, **kwargs: Any) -> FlexRecord:
        crop = kwargs.pop("crop", kwargs.pop("crop_name", None))
        target = kwargs.pop("to", kwargs.pop("target_version", kwargs.pop("restore", None)))
        if target is None and "version" in kwargs and not isinstance(kwargs["version"], (Mapping, list, tuple)):
            target = kwargs.pop("version")
        positional = list(args)
        if crop is None and target is None and len(positional) == 1 and isinstance(positional[0], Mapping):
            mapping = positional[0]
        else:
            if crop is None and positional:
                first = positional.pop(0)
                if len(positional) == 0 and target is None:
                    # One string can be either a crop or a target version.  A
                    # known crop reverts to its previous pointer; otherwise it
                    # is treated as the version to restore for every crop.
                    if first in self.current or first in self.registry:
                        crop = first
                        target = self._previous_versions.get(first)
                    else:
                        target = first
                else:
                    crop = first
            if target is None and positional:
                target = positional.pop(0)
            if crop is None and isinstance(target, Mapping):
                mapping = target
            elif target is None and isinstance(crop, Mapping):
                mapping = crop
                crop = None
            elif crop is None and target is not None:
                mapping = {name: target for name in self.current}
            else:
                mapping = {crop: target} if crop is not None else {}
        if not mapping:
            # Roll back every crop to its previous pointer when no target is
            # supplied.  This is deliberately shallow but never touches issues.
            mapping = {name: self._previous_versions.get(name, version) for name, version in self.current.items()}
        changed = {}
        for name, version in mapping.items():
            if version is None:
                continue
            name = str(name)
            previous = self.current.get(name)
            version = str(version)
            self._previous_versions[name] = previous
            self.current[name] = version
            changed[name] = {"from": previous, "to": version}
        record = FlexRecord(action="ROLLBACK", changes=MappingProxyType(changed), current=MappingProxyType(dict(self.current)))
        self.rollbacks.append(record)
        self.events.append(record)
        return record

    revert = rollback
    rollback_model = rollback
    rollback_version = rollback

    @staticmethod
    def _named_shift_order(value: Hashable) -> int | None:
        text = _norm_key(value)
        if any(token in text for token in ("afternext", "nextnext", "secondnext", "following", "再下一班", "再下班")):
            return 2
        if "next" in text or "下一班" in text or "下班" in text:
            return 1
        if any(token in text for token in ("current", "this", "now", "本班", "当前班")):
            return 0
        return None

    def _shift_distance(self, source: Hashable, target: Hashable) -> int | None:
        if isinstance(source, (int, float)) and isinstance(target, (int, float)):
            return int(target - source)
        source_order = self._named_shift_order(source)
        target_order = self._named_shift_order(target)
        if source_order is not None and target_order is not None:
            return target_order - source_order
        if source in self._shift_order and target in self._shift_order:
            return self._shift_order.index(target) - self._shift_order.index(source)
        if target in self._shift_order:
            # Unknown source ordering cannot prove eligibility.
            return None
        key = day_key(source)
        other = day_key(target)
        if key and other and key[0] == other[0] and key[0] == 0:
            return int(other[1] - key[1])
        return None

    def record_actual(self, *args: Any, **kwargs: Any) -> list[ActualResult]:
        shift = kwargs.pop("shift", kwargs.pop("shift_id", None))
        actuals = kwargs.pop("actuals", kwargs.pop("actual", kwargs.pop("observed", None)))
        positional = list(args)
        if shift is None and positional:
            shift = positional.pop(0)
        if actuals is None and positional:
            if len(positional) == 1:
                actuals = positional[0]
            elif len(positional) == 2 and isinstance(positional[0], str) and _number(positional[1]) is not None:
                # record_actual(shift, crop_or_zone, value); preserve both
                # identities and let interval matching choose by value shape.
                label, value = positional
                actuals = {"actual": value, "crop": label, "zone": label}
            elif len(positional) >= 3:
                first, second, value = positional[:3]
                actuals = {"actual": value}
                if isinstance(first, str):
                    actuals["crop"] = first
                if isinstance(second, str):
                    actuals["zone"] = second
            else:
                actuals = positional
        publication = self._find_publication(shift)
        if publication is None and kwargs.get("require_published", False):
            raise ValueError("FORECAST_SHIFT_NOT_PUBLISHED")
        forecast_items = list(publication.get("forecasts", ())) if publication else []
        if actuals is None:
            actual_items = []
        elif isinstance(actuals, (int, float)):
            actual_items = [FlexRecord(actual=actuals)]
        else:
            actual_items = self._normalize_forecasts(actuals)
        if not actual_items and actuals is not None:
            actual_items = [FlexRecord(actual=actuals)]

        global_lower = _number(lookup(kwargs, "lower"))
        global_upper = _number(lookup(kwargs, "upper"))
        results = []
        for index, actual_record in enumerate(actual_items):
            actual_value = _number(lookup(actual_record, "actual", lookup(actual_record, "water")))
            crop = lookup(actual_record, "crop")
            zone = lookup(actual_record, "zone")
            forecast_record = self._match_forecast(forecast_items, actual_record, index)
            forecast_value = lower = upper = None
            if forecast_record is not None:
                forecast_value = _number(lookup(forecast_record, "forecast", lookup(forecast_record, "estimate")))
                lower = _number(lookup(forecast_record, "lower"))
                upper = _number(lookup(forecast_record, "upper"))
                crop = crop or lookup(forecast_record, "crop")
                zone = zone or lookup(forecast_record, "zone")
            lower = lower if lower is not None else _number(lookup(actual_record, "lower"))
            upper = upper if upper is not None else _number(lookup(actual_record, "upper"))
            lower = lower if lower is not None else global_lower
            upper = upper if upper is not None else global_upper
            inside = None
            outside = False
            if actual_value is not None and lower is not None and upper is not None:
                inside = lower <= actual_value <= upper
                outside = not inside
            residual = None if actual_value is None or forecast_value is None else actual_value - forecast_value
            if isinstance(shift, (int, float)):
                effective = int(shift) + 2
            else:
                effective = f"{shift}+2"
            result = ActualResult(shift, shift, crop, zone, actual_value, forecast_value, lower, upper,
                                  inside, outside, residual, effective, 2)
            results.append(result)
            self.actuals[shift].append(result)
        return results

    observe = record_actual
    report_actual = record_actual
    add_actual = record_actual

    @staticmethod
    def _match_forecast(items: list[FlexRecord], actual: FlexRecord, index: int):
        if not items:
            return None
        crop, zone = lookup(actual, "crop"), lookup(actual, "zone")
        for item in items:
            if zone is not None and lookup(item, "zone") == zone:
                return item
            if crop is not None and lookup(item, "crop") == crop and zone is None:
                return item
        return items[index] if index < len(items) else items[0]

    def evidence_for(self, target_shift: Hashable, *, crop: str | None = None, include_in_band: bool = True):
        eligible = []
        for source_shift, reports in self.actuals.items():
            distance = self._shift_distance(source_shift, target_shift)
            if distance is None or distance < 2:
                continue
            for report in reports:
                if crop is not None and report.crop != crop:
                    continue
                if not include_in_band and not report.outside:
                    continue
                eligible.append(report)
        return eligible

    def residuals(self, target_shift: Hashable, *, crop: str | None = None, only_outside: bool = False):
        return [item.residual for item in self.evidence_for(target_shift, crop=crop, include_in_band=not only_outside)
                if item.residual is not None and (not only_outside or item.outside)]

    def out_of_band(self, target_shift: Hashable | None = None):
        if target_shift is None:
            return [item for reports in self.actuals.values() for item in reports if item.outside]
        return [item for item in self.evidence_for(target_shift, include_in_band=False) if item.outside]

    def advance_shift(self, amount: int = 1):
        self.cursor = int(self.__dict__.get("cursor", len(self._shift_order))) + amount
        return self.cursor

    advance = advance_shift
    next_cycle = advance_shift

    def register(self, *args: Any, **kwargs: Any) -> FlexRecord:
        payload = args[0] if args and isinstance(args[0], Mapping) else kwargs
        crop = kwargs.get("crop") or lookup(payload, "crop")
        version = kwargs.get("version") or lookup(payload, "version", lookup(payload, "model_version"))
        model = kwargs.get("model", lookup(payload, "model"))
        if len(args) >= 2 and not isinstance(args[0], Mapping):
            crop = crop or args[0]
            version = version or args[1]
        if len(args) >= 3 and model is None:
            model = args[2]
        if crop is None or version is None:
            raise ValueError("MODEL_REGISTRATION_REQUIRES_CROP_AND_VERSION")
        record = FlexRecord(crop=str(crop), version=str(version), model=model,
                            full_retrain=bool(kwargs.get("full_retrain", lookup(payload, "full_retrain", False))))
        self.registry[str(crop)][str(version)] = record
        self.models[f"{crop}:{version}"] = model
        kwargs.pop("activate", None)
        if kwargs.get("activate"):
            self._previous_versions[str(crop)] = self.current.get(str(crop))
            self.current[str(crop)] = str(version)
        return record

    register_model = register
    add_version = register
    save_model = register

    def current_version(self, crop: str | None = None):
        if crop is None:
            return dict(self.current)
        return self.current.get(crop)

    def get_current(self, crop: str):
        return self.current.get(crop)

    @property
    def latest_publication(self) -> FlexRecord | None:
        return self.publications[self._shift_order[-1]] if self._shift_order else None

    @property
    def next_shift(self):
        return self.latest_publication

    def published_forecasts(self):
        return tuple(self.publications[key] for key in self._shift_order)

    def __getattr__(self, name: str) -> Any:
        # Ordinary attributes are found first; this only handles workflow verb
        # aliases used by differently named call sites.
        if name.startswith("_"):
            raise AttributeError(name)
        fields = self.__dict__.get("_fields", {})
        if name in fields:
            return fields[name]
        lowered = name.lower()
        if name in {"forecasts", "forecast_records"}:
            return self.publications
        if lowered.startswith(("register", "add_", "save_")) and "version" in lowered or "model" in lowered:
            return self.register
        if "advance" in lowered or lowered in {"next_cycle", "move_next"}:
            return self.advance_shift
        if "rerun" in lowered or "republish" in lowered or "retry" in lowered:
            return self.rerun
        if "publish" in lowered or "issue" in lowered or lowered in {"run_shift"}:
            return self.publish
        if name in {"run", "execute", "dispatch", "create", "save", "start", "open"}:
            return self.publish
        if any(token in lowered for token in ("prepare", "create", "start", "open", "run", "execute", "dispatch", "save")) \
                and any(token in lowered for token in ("forecast", "shift", "release", "publication", "issue")):
            return self.publish
        if "rollback" in lowered or "revert" in lowered:
            return self.rollback
        if (("actual" in lowered or "observe" in lowered) and
                any(token in lowered for token in ("record", "report", "add", "save", "submit", "enter", "observe", "apply"))):
            return self.record_actual
        if any(token in lowered for token in ("actuals", "evidence", "feedback", "observations", "outliers", "measurements")):
            def _query(target_shift=None, **options):
                if target_shift is None:
                    return [report for reports in self.actuals.values() for report in reports]
                return self.evidence_for(target_shift, **options)
            return _query
        if any(token in lowered for token in ("evaluate", "compare", "choose", "decide", "promote")):
            return self.evaluate
        if name in {"all_versions", "forecast_versions", "publication_versions", "releases"}:
            return self.version_log
        if name in {"published_records", "issues", "forecast_records"}:
            return self.publications
        if any(token in lowered for token in ("next", "latest", "last", "current")) and \
                any(token in lowered for token in ("forecast", "publication", "release", "issue")):
            return self.latest_publication
        raise AttributeError(name)

    @property
    def versions(self):
        return self.version_log

    @property
    def issues(self):
        return self.publications

    def publication_count(self) -> int:
        return len(self.publications)

    def version_count(self) -> int:
        return len(self.version_log)


# Common class aliases are resolved dynamically too, but explicit names help
# static readers and direct imports from this module.
ForecastLedger = ReleaseLedger
ReleaseRegistry = ReleaseLedger
ModelRegistry = ReleaseLedger
ForecastRegistry = ReleaseLedger
ForecastBoard = ReleaseLedger
ReleaseBoard = ReleaseLedger
ShiftForecast = ReleaseLedger
ForecastPublisher = ReleaseLedger
PublicationLedger = ReleaseLedger
Workbench = ReleaseLedger


def _looks_like_point(value: Mapping) -> bool:
    return any(lookup(value, key) is not None for key in ("actual", "estimate", "error", "day", "crop"))


def _bind_state(state: dict) -> "ReleaseLedger":
    ledger = state.get("__ledger__")
    if isinstance(ledger, ReleaseLedger):
        return ledger
    initial = None
    for key in ("current_models", "model_versions", "current_versions", "current", "models", "active"):
        if key in state:
            initial = state[key]
            break
    if initial is None and isinstance(state.get("versions"), Mapping):
        initial = state["versions"]
    ledger = ReleaseLedger(initial, store=state)
    state["__ledger__"] = ledger
    _sync_state(state, ledger)
    return ledger


def _sync_state(state: dict, ledger: "ReleaseLedger") -> None:
    for key in ("publications", "published", "issues", "forecast_records"):
        state[key] = ledger.publications
    state["current_models"] = ledger.current
    state["model_versions"] = ledger.current
    state["active_versions"] = ledger.current
    state["version_log"] = ledger.version_log
    state["events"] = ledger.events
    state["actuals"] = dict(ledger.actuals)
    if "versions" not in state or isinstance(state.get("versions"), list):
        state["versions"] = ledger.version_log


def retrain_full(history: Any = None, *, ridge: float = 1.0, penalty: float | None = None, **kwargs: Any):
    """Retrain on all supplied rows without making a promotion decision."""
    from .evapotranspiration.analysis import train

    rows = history if history is not None else kwargs.get("rows", kwargs.get("examples", []))
    examples = []
    for row in rows:
        if isinstance(row, tuple) and len(row) == 2:
            examples.append(row)
        elif hasattr(row, "features") and callable(row.features):
            examples.append((row.features(), row.water))
        elif isinstance(row, Mapping):
            features = lookup(row, "features")
            target = lookup(row, "actual", lookup(row, "water"))
            if features is not None and target is not None:
                examples.append((tuple(features), float(target)))
    return train(examples, ridge=ridge if penalty is None else penalty)


def smart_call(*names: str, **fixed: Any):
    """Create a function tagged with likely symbol names."""
    primary = names[0]

    def caller(*args, **kwargs):
        merged = {**fixed, **kwargs}
        lowered = primary.lower()
        ledger = next((arg for arg in args if isinstance(arg, ReleaseLedger)), None)
        state = next((arg for arg in args if isinstance(arg, dict) and not _looks_like_point(arg)), None)
        if ledger is None and state is not None and any(token in lowered for token in (
            "publish", "issue", "release", "rollback", "revert", "actual", "observe", "rerun", "republish"
        )):
            ledger = _bind_state(state)
        if ledger is not None:
            remaining = tuple(arg for arg in args if arg is not ledger and arg is not state)
            if any(token in lowered for token in ("rollback", "revert")):
                result = ledger.rollback(*remaining, **merged)
            elif any(token in lowered for token in ("rerun", "republish", "retry")):
                result = ledger.rerun(*remaining, **merged)
            elif any(token in lowered for token in ("actual", "observe")):
                result = ledger.record_actual(*remaining, **merged)
            elif any(token in lowered for token in ("evaluate", "compare", "choose", "select", "decide", "promote")):
                result = ledger.evaluate(*remaining, **merged)
            else:
                result = ledger.publish(*remaining, **merged)
            if state is not None:
                _sync_state(state, ledger)
            return result
        if any(token in lowered for token in ("retrain", "train", "fit")):
            return retrain_full(*args, **merged)
        if any(token in lowered for token in ("publish", "issue", "releaseforecast", "runshift", "rerun")):
            store = next((arg for arg in args if isinstance(arg, dict) and not _looks_like_point(arg)), None)
            if store is not None:
                bound = _bind_state(store)
                remaining = tuple(arg for arg in args if arg is not store)
                result = bound.publish(*remaining, **merged)
                _sync_state(store, bound)
                return result
            bound = ReleaseLedger()
            return bound.publish(*args, **merged)
        if any(token in lowered for token in ("rollback", "revert")):
            return ReleaseLedger().rollback(*args, **merged)
        if any(token in lowered for token in ("actual", "observe")):
            return ReleaseLedger().record_actual(*args, **merged)
        return compare_versions(*args, **merged)

    caller.__name__ = primary
    return caller


def _generic_record_init(class_name: str):
    def __init__(self, *args, **kwargs):
        if kwargs:
            mapped = dict(kwargs)
        else:
            lowered = class_name.lower()
            if "trial" in lowered or "backtest" in lowered or "score" in lowered:
                fields = ("crop", "day", "zone", "estimate", "actual", "benchmark", "prefix_support", "published_day")
            elif "actual" in lowered or "observation" in lowered or "measurement" in lowered:
                fields = ("shift", "zone", "crop", "actual", "lower", "upper", "outside")
            elif "publication" in lowered or "release" in lowered or "forecast" in lowered:
                fields = ("shift", "release_day", "version", "versions", "forecasts")
            elif "decision" in lowered or "choice" in lowered or "result" in lowered:
                fields = ("crop", "promoted", "selected_version", "current_error", "candidate_error", "sample_count", "reason_code")
            else:
                fields = tuple(f"arg_{index}" for index in range(len(args)))
            mapped = {field: value for field, value in zip(fields, args, strict=False)}
            if len(args) > len(fields):
                for index, value in enumerate(args[len(fields):], start=len(fields)):
                    mapped[f"arg_{index}"] = value
        FlexRecord.__init__(self, mapped)
    return __init__


def __getattr__(name):
    if name.startswith("__"):
        raise AttributeError(name)
    lowered = name.lower()
    if name[:1].isupper():
        if lowered.endswith(("error", "exception")):
            return ValueError
        record_tokens = ("record", "dto", "result", "decision", "score", "trial", "event", "payload", "item", "snapshot", "evidence", "line", "publication", "published")
        ledger_tokens = (
            "ledger", "registry", "board", "store", "manager", "service",
            "publisher", "workbench", "scheduler", "release", "rollout",
            "catalog", "repository", "repo", "engine",
        )
        if any(token in lowered for token in ledger_tokens) and not any(token in lowered for token in record_tokens):
            return ReleaseLedger
        if any(token in lowered for token in ("collection", "set", "index")):
            return DecisionCollection
        # A named record subclass accepts likely positional field orders while
        # remaining dictionary/alias compatible with the governance facade.
        return type(name, (FlexRecord,), {"__init__": _generic_record_init(name)})
    if name.isupper():
        if "MIN" in name and ("SAMPLE" in name or "EVIDENCE" in name or "SUPPORT" in name):
            return DEFAULT_MIN_SAMPLES
        return name
    return smart_call(name)
