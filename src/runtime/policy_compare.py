"""Résumés policy-compare et A/B runtime — Phase 2.7 (extraction de src/main.py)

Fonctions pures opérant sur les décisions persistées : normalisation
streets/actions/slugs, comparaison multi-politiques (GTO vs RL vs branches
A/B), synthèse AB. Déplacé à l'identique ; les délégations du contrôleur
conservernt l'API historique.
"""

from __future__ import annotations


def normalize_runtime_street_name(value: object) -> str:
    normalized = str(value or "").strip().upper()
    return normalized or "UNKNOWN"


def normalize_runtime_action_name(value: object) -> str:
    normalized = str(value or "").strip().upper()
    return normalized


def policy_slug(value: object, fallback: str = "runtime") -> str:
    slug = str(value or "").strip().lower().replace(" ", "_")
    return slug or fallback


def safe_runtime_float(value: object) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_runtime_ab_decision(entry: dict) -> dict | None:
    if not isinstance(entry, dict):
        return None

    ab_decision = entry.get("ab_decision")
    if isinstance(ab_decision, dict):
        return ab_decision

    metadata = entry.get("metadata")
    if isinstance(metadata, dict):
        nested = metadata.get("rl_ab")
        if isinstance(nested, dict):
            return nested

    return None


def runtime_ab_decision_key(entry: dict) -> tuple | None:
    if not isinstance(entry, dict):
        return None

    spot_id = str(entry.get("spot_id", "") or "").strip()
    timestamp = str(entry.get("timestamp", "") or "").strip()
    if spot_id and timestamp:
        return ("spot_id_timestamp", spot_id, timestamp)

    street = str(entry.get("street", "") or "").strip().upper()
    chosen_action = str(entry.get("chosen_action", entry.get("action", "")) or "").strip().upper()
    source = str(entry.get("source", "") or "").strip().lower()
    if timestamp and street and chosen_action:
        return ("timestamp_street_action", timestamp, street, chosen_action, source)

    return None


def dedupe_runtime_ab_decisions(decisions: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen_keys: set[tuple] = set()

    for entry in decisions:
        if not isinstance(entry, dict):
            continue

        decision_key = runtime_ab_decision_key(entry)
        if decision_key is None:
            deduped.append(entry)
            continue

        if decision_key in seen_keys:
            continue

        seen_keys.add(decision_key)
        deduped.append(entry)

    return deduped


def build_runtime_ab_summary(decisions: list[dict]) -> dict:
    summary = {
        "sample_count": 0,
        "compared_count": 0,
        "eligible_count": 0,
        "applied_count": 0,
        "diff_count": 0,
        "action_change_count": 0,
        "avg_delta_ev": None,
        "avg_delta_freq": None,
        "impacted_streets": [],
        "street_counts": {},
    }
    if not isinstance(decisions, list) or not decisions:
        return summary

    compared_count = 0
    eligible_count = 0
    applied_count = 0
    diff_count = 0
    action_change_count = 0
    ev_delta_total = 0.0
    ev_delta_count = 0
    freq_delta_total = 0.0
    freq_delta_count = 0
    impacted_streets: dict[str, int] = {}

    for entry in decisions:
        ab_decision = extract_runtime_ab_decision(entry)
        if not ab_decision:
            continue

        summary["sample_count"] += 1
        if ab_decision.get("compared"):
            compared_count += 1
        if ab_decision.get("eligible"):
            eligible_count += 1
        if ab_decision.get("applied"):
            applied_count += 1
        if ab_decision.get("rl_differs_from_gto") or ab_decision.get("would_override"):
            diff_count += 1

        comparison = (
            ab_decision.get("comparison") if isinstance(ab_decision.get("comparison"), dict) else {}
        )
        action_changed = bool(comparison.get("action_changed"))
        if action_changed:
            action_change_count += 1
            street = normalize_runtime_street_name(entry.get("street"))
            impacted_streets[street] = impacted_streets.get(street, 0) + 1

        ev_delta = comparison.get("ev_delta")
        if isinstance(ev_delta, (int, float)):
            ev_delta_total += float(ev_delta)
            ev_delta_count += 1

        freq_delta = comparison.get("freq_delta")
        if isinstance(freq_delta, (int, float)):
            freq_delta_total += float(freq_delta)
            freq_delta_count += 1

    summary["compared_count"] = compared_count
    summary["eligible_count"] = eligible_count
    summary["applied_count"] = applied_count
    summary["diff_count"] = diff_count
    summary["action_change_count"] = action_change_count
    summary["avg_delta_ev"] = round(ev_delta_total / ev_delta_count, 4) if ev_delta_count else None
    summary["avg_delta_freq"] = (
        round(freq_delta_total / freq_delta_count, 4) if freq_delta_count else None
    )
    summary["impacted_streets"] = sorted(impacted_streets)
    summary["street_counts"] = {
        street: impacted_streets[street] for street in sorted(impacted_streets)
    }
    return summary


def extract_policy_compare_actions(entry: dict) -> dict[str, str]:
    if not isinstance(entry, dict):
        return {}

    policy_actions: dict[str, str] = {}
    chosen_action = normalize_runtime_action_name(
        entry.get("chosen_action", entry.get("action", ""))
    )
    if chosen_action:
        policy_actions[policy_slug(entry.get("source"), "runtime")] = chosen_action

    ab_decision = extract_runtime_ab_decision(entry) or {}
    gto_action = normalize_runtime_action_name(ab_decision.get("gto_action"))
    if gto_action:
        policy_actions.setdefault("gto_solver", gto_action)

    comparison = (
        ab_decision.get("comparison") if isinstance(ab_decision.get("comparison"), dict) else {}
    )
    final_action = normalize_runtime_action_name(ab_decision.get("final_action"))
    rl_action = normalize_runtime_action_name(ab_decision.get("rl_action"))
    for branch in ("rl_off", "rl_on"):
        branch_action = normalize_runtime_action_name(
            (comparison.get(branch, {}) or {}).get("action")
        )
        if not branch_action and branch == "rl_off":
            branch_action = gto_action or chosen_action
        if not branch_action and branch == "rl_on":
            branch_action = rl_action or final_action or chosen_action
        if branch_action:
            policy_actions.setdefault(branch, branch_action)

    return policy_actions


def extract_policy_compare_ev_by_action(entry: dict) -> dict[str, float]:
    if not isinstance(entry, dict):
        return {}

    ev_by_action: dict[str, float] = {}

    def remember(action_name: object, ev_value: object) -> None:
        action = normalize_runtime_action_name(action_name)
        ev = safe_runtime_float(ev_value)
        if action and ev is not None and action not in ev_by_action:
            ev_by_action[action] = ev

    metadata = dict(entry.get("metadata", {}) or {})
    solver = dict(metadata.get("solver", entry.get("solver", {})) or {})
    for item in solver.get("alternatives", []) or []:
        if not isinstance(item, dict):
            continue
        remember(item.get("action", item.get("raw_action")), item.get("ev", item.get("hero_ev")))

    ab_decision = extract_runtime_ab_decision(entry) or {}
    comparison = (
        ab_decision.get("comparison") if isinstance(ab_decision.get("comparison"), dict) else {}
    )
    for branch in ("rl_off", "rl_on"):
        branch_snapshot = dict(comparison.get(branch, {}) or {})
        remember(branch_snapshot.get("action"), branch_snapshot.get("ev"))

    remember(entry.get("chosen_action", entry.get("action")), entry.get("ev"))
    return ev_by_action


def build_empty_policy_compare_summary() -> dict:
    return {
        "sample_count": 0,
        "comparable_count": 0,
        "agreement_count": 0,
        "disagreement_count": 0,
        "agreement_rate": 0.0,
        "changed_action_count": 0,
        "changed_action_rate": 0.0,
        "ev_coverage_count": 0,
        "ev_coverage_rate": 0.0,
        "policies": [],
        "policy_counts": {},
        "street_counts": {},
        "source_counts": {},
        "comparisons": [],
        "highlights": {
            "most_compared_pair": None,
            "most_divergent_pair": None,
            "top_spots": [],
        },
    }


def policy_compare_sample_id(entry: dict, fallback: str) -> str:
    if not isinstance(entry, dict):
        return fallback
    spot_id = str(entry.get("spot_id", "") or "").strip()
    timestamp = str(entry.get("timestamp", "") or "").strip()
    if spot_id and timestamp:
        return f"{spot_id}@{timestamp}"
    if spot_id:
        return spot_id
    if timestamp:
        return timestamp
    return fallback


def policy_compare_spot_example(
    entry: dict,
    sample_id: str,
    baseline_action: str,
    challenger_action: str,
    ev_by_action: dict[str, float],
) -> dict:
    example = {
        "sample_id": sample_id,
        "spot_id": str(entry.get("spot_id", "") or "").strip() or sample_id,
        "street": normalize_runtime_street_name(entry.get("street")),
        "baseline_action": baseline_action,
        "challenger_action": challenger_action,
        "action_pair": f"{baseline_action}->{challenger_action}",
    }
    hero_cards = list(entry.get("hero_cards", []) or [])
    board = list(entry.get("board", []) or [])
    if hero_cards:
        example["hero_cards"] = hero_cards[:2]
    if board:
        example["board"] = board[:5]
    pot = safe_runtime_float(entry.get("pot"))
    if pot is not None:
        example["pot"] = round(pot, 4)
    baseline_ev = ev_by_action.get(baseline_action)
    challenger_ev = ev_by_action.get(challenger_action)
    if baseline_ev is not None:
        example["baseline_ev"] = round(float(baseline_ev), 4)
    if challenger_ev is not None:
        example["challenger_ev"] = round(float(challenger_ev), 4)
    if baseline_ev is not None and challenger_ev is not None:
        example["ev_delta"] = round(float(challenger_ev) - float(baseline_ev), 4)
    return example


def compact_policy_compare_examples(examples: list[dict], limit: int = 2) -> list[dict]:
    ranked = sorted(
        [item for item in examples if isinstance(item, dict)],
        key=lambda item: (
            -abs(float(item.get("ev_delta", 0.0) or 0.0)),
            item.get("sample_id", ""),
        ),
    )
    return ranked[:limit]


def build_policy_compare_summary(decisions: list[dict]) -> dict:
    summary = build_empty_policy_compare_summary()
    if not isinstance(decisions, list) or not decisions:
        return summary

    policy_counts: dict[str, int] = {}
    street_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    comparisons: dict[tuple[str, str], dict] = {}
    spot_counts: dict[str, dict] = {}

    for index, entry in enumerate(decisions, start=1):
        if not isinstance(entry, dict):
            continue

        policy_actions = extract_policy_compare_actions(entry)
        if not policy_actions:
            continue

        sample_id = policy_compare_sample_id(entry, f"sample-{index:03d}")

        summary["sample_count"] += 1
        source = policy_slug(entry.get("source"), "runtime")
        source_counts[source] = source_counts.get(source, 0) + 1

        for policy in policy_actions:
            policy_counts[policy] = policy_counts.get(policy, 0) + 1

        if len(policy_actions) < 2:
            continue

        summary["comparable_count"] += 1
        street = normalize_runtime_street_name(entry.get("street"))
        street_counts[street] = street_counts.get(street, 0) + 1
        spot_id = str(entry.get("spot_id", "") or "").strip() or sample_id
        spot_summary = spot_counts.setdefault(
            spot_id,
            {
                "spot_id": spot_id,
                "sample_count": 0,
                "streets": set(),
                "sample_ids": [],
            },
        )
        spot_summary["sample_count"] += 1
        spot_summary["streets"].add(street)
        if sample_id not in spot_summary["sample_ids"] and len(spot_summary["sample_ids"]) < 3:
            spot_summary["sample_ids"].append(sample_id)

        unique_actions = sorted(set(policy_actions.values()))
        if len(unique_actions) == 1:
            summary["agreement_count"] += 1
        else:
            summary["changed_action_count"] += 1

        ev_by_action = extract_policy_compare_ev_by_action(entry)
        policies = sorted(policy_actions)
        for pair_index, baseline in enumerate(policies):
            for challenger in policies[pair_index + 1 :]:
                baseline_action = policy_actions.get(baseline, "")
                challenger_action = policy_actions.get(challenger, "")
                if not baseline_action or not challenger_action:
                    continue

                key = (baseline, challenger)
                pair_summary = comparisons.setdefault(
                    key,
                    {
                        "baseline_policy": baseline,
                        "challenger_policy": challenger,
                        "sample_count": 0,
                        "agreement_count": 0,
                        "disagreement_count": 0,
                        "ev_coverage_count": 0,
                        "baseline_ev_sum": 0.0,
                        "challenger_ev_sum": 0.0,
                        "action_pairs": {},
                        "sample_ids": [],
                        "spot_examples": [],
                        "divergence_examples": [],
                    },
                )
                pair_summary["sample_count"] += 1
                pair_key = f"{baseline_action}->{challenger_action}"
                pair_summary["action_pairs"][pair_key] = (
                    pair_summary["action_pairs"].get(pair_key, 0) + 1
                )
                if (
                    sample_id not in pair_summary["sample_ids"]
                    and len(pair_summary["sample_ids"]) < 3
                ):
                    pair_summary["sample_ids"].append(sample_id)

                example = policy_compare_spot_example(
                    entry,
                    sample_id,
                    baseline_action,
                    challenger_action,
                    ev_by_action,
                )
                pair_summary["spot_examples"].append(example)

                if baseline_action == challenger_action:
                    pair_summary["agreement_count"] += 1
                else:
                    pair_summary["disagreement_count"] += 1
                    pair_summary["divergence_examples"].append(example)

                baseline_ev = ev_by_action.get(baseline_action)
                challenger_ev = ev_by_action.get(challenger_action)
                if baseline_ev is not None and challenger_ev is not None:
                    pair_summary["ev_coverage_count"] += 1
                    pair_summary["baseline_ev_sum"] += float(baseline_ev)
                    pair_summary["challenger_ev_sum"] += float(challenger_ev)

    summary["disagreement_count"] = summary["comparable_count"] - summary["agreement_count"]
    summary["agreement_rate"] = (
        round(summary["agreement_count"] / summary["comparable_count"], 4)
        if summary["comparable_count"]
        else 0.0
    )
    summary["changed_action_rate"] = (
        round(summary["changed_action_count"] / summary["comparable_count"], 4)
        if summary["comparable_count"]
        else 0.0
    )

    comparison_rows = []
    for pair_summary in comparisons.values():
        sample_count = pair_summary["sample_count"]
        ev_coverage_count = pair_summary["ev_coverage_count"]
        summary["ev_coverage_count"] += ev_coverage_count
        top_action_pairs = sorted(
            pair_summary["action_pairs"].items(),
            key=lambda item: (-item[1], item[0]),
        )[:3]
        comparison_rows.append(
            {
                "baseline_policy": pair_summary["baseline_policy"],
                "challenger_policy": pair_summary["challenger_policy"],
                "sample_count": sample_count,
                "agreement_count": pair_summary["agreement_count"],
                "disagreement_count": pair_summary["disagreement_count"],
                "agreement_rate": round(pair_summary["agreement_count"] / sample_count, 4)
                if sample_count
                else 0.0,
                "ev_coverage_count": ev_coverage_count,
                "ev_coverage_rate": round(ev_coverage_count / sample_count, 4)
                if sample_count
                else 0.0,
                "challenger_ev_delta": round(
                    pair_summary["challenger_ev_sum"] - pair_summary["baseline_ev_sum"],
                    4,
                ),
                "sample_ids": list(pair_summary["sample_ids"]),
                "top_action_pairs": [
                    {"actions": action_pair, "count": count}
                    for action_pair, count in top_action_pairs
                ],
                "top_spots": compact_policy_compare_examples(pair_summary["spot_examples"]),
                "divergence_examples": compact_policy_compare_examples(
                    pair_summary["divergence_examples"],
                ),
            }
        )

    total_pair_samples = sum(item["sample_count"] for item in comparison_rows)
    summary["ev_coverage_rate"] = (
        round(
            summary["ev_coverage_count"] / total_pair_samples,
            4,
        )
        if total_pair_samples
        else 0.0
    )
    summary["policies"] = sorted(policy_counts)
    summary["policy_counts"] = {policy: policy_counts[policy] for policy in sorted(policy_counts)}
    summary["street_counts"] = {street: street_counts[street] for street in sorted(street_counts)}
    summary["source_counts"] = {name: source_counts[name] for name in sorted(source_counts)}
    summary["comparisons"] = sorted(
        comparison_rows,
        key=lambda item: (
            -item["sample_count"],
            item["agreement_rate"],
            item["baseline_policy"],
            item["challenger_policy"],
        ),
    )[:6]
    top_spots = sorted(
        spot_counts.values(),
        key=lambda item: (-item["sample_count"], item["spot_id"]),
    )[:3]
    if summary["comparisons"]:
        most_divergent = min(
            summary["comparisons"],
            key=lambda item: (
                item["agreement_rate"],
                -item["sample_count"],
                item["baseline_policy"],
                item["challenger_policy"],
            ),
        )
        summary["highlights"] = {
            "most_compared_pair": {
                "baseline_policy": summary["comparisons"][0]["baseline_policy"],
                "challenger_policy": summary["comparisons"][0]["challenger_policy"],
                "sample_count": summary["comparisons"][0]["sample_count"],
                "sample_ids": list(summary["comparisons"][0].get("sample_ids", [])),
                "top_spots": list(summary["comparisons"][0].get("top_spots", [])),
            },
            "most_divergent_pair": {
                "baseline_policy": most_divergent["baseline_policy"],
                "challenger_policy": most_divergent["challenger_policy"],
                "agreement_rate": most_divergent["agreement_rate"],
                "sample_ids": list(most_divergent.get("sample_ids", [])),
                "divergence_examples": list(most_divergent.get("divergence_examples", [])),
            },
            "top_spots": [
                {
                    "spot_id": item["spot_id"],
                    "sample_count": item["sample_count"],
                    "streets": sorted(item["streets"]),
                    "sample_ids": list(item["sample_ids"]),
                }
                for item in top_spots
            ],
        }
    return summary
