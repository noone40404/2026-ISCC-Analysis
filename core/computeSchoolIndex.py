import argparse
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
THRESHOLD_MINUTES = 5
SMALL_ACCOUNT_MAX_SOLVES = 5
EPSILON = 0.01
TRIM_RATIO = 0.1


def load_json(path):
    try:
        with Path(path).open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def parse_time(value):
    return datetime.strptime(value, TIME_FORMAT)


def build_solve_counts(raw_data):
    counts = defaultdict(int)
    for _, items in (raw_data or {}).items():
        for _, info in (items or {}).items():
            for solve in info.get("solves", []):
                name = solve.get("name")
                if not name:
                    continue
                counts[name] += 1
    return counts


def weight_for_rank(rank, dataset_type):
    if dataset_type == "challenge":
        if rank <= 50:
            return 1.0
        if rank <= 100:
            return 0.59049
        if rank <= 150:
            return 0.59049
        if rank <= 300:
            return 0.32786
        if rank <= 600:
            return 0.16807
        if rank <= 1200:
            return 0.07776
        if rank <= 2000:
            return 0.03125
        return 0.01024
    if dataset_type == "arena":
        if rank <= 10:
            return 1.0
        if rank <= 100:
            return 0.59049
        return 0.32786
    return 1.0


def compute_school_collisions(raw_data, user_school_map, small_accounts, threshold_seconds, dataset_type):
    collisions = defaultdict(int)
    diff_seconds = defaultdict(float)
    intensity_sums = defaultdict(float)
    user_close_counts = defaultdict(lambda: defaultdict(int))

    for _, items in (raw_data or {}).items():
        for _, info in (items or {}).items():
            all_entries = []
            for solve in info.get("solves", []):
                name = solve.get("name")
                time_str = solve.get("date")
                if not name or not time_str:
                    continue
                school = user_school_map.get(name)
                if not school:
                    continue
                try:
                    time = parse_time(time_str)
                except ValueError:
                    continue
                all_entries.append({
                    "time": time,
                    "school": school,
                    "name": name,
                    "is_small": name in small_accounts,
                })

            all_entries.sort(key=lambda entry: entry["time"])
            for idx, entry in enumerate(all_entries):
                entry["rank"] = idx + 1

            entries_by_school = defaultdict(list)
            for entry in all_entries:
                if entry["is_small"]:
                    continue
                entries_by_school[entry["school"]].append(entry)

            for school, times in entries_by_school.items():
                for idx, current in enumerate(times):
                    nearest = None
                    if idx > 0:
                        prev_diff = (current["time"] - times[idx - 1]["time"]).total_seconds()
                        if prev_diff <= threshold_seconds:
                            nearest = prev_diff
                    if idx < len(times) - 1:
                        next_diff = (times[idx + 1]["time"] - current["time"]).total_seconds()
                        if next_diff <= threshold_seconds and (nearest is None or next_diff < nearest):
                            nearest = next_diff

                    if nearest is not None:
                        collisions[school] += 1
                        diff_seconds[school] += nearest
                        weight = weight_for_rank(current["rank"], dataset_type)
                        intensity_sums[school] += (weight ** 3) / ((nearest / 60) + EPSILON)
                        user_close_counts[school][current["name"]] += 1

    return collisions, diff_seconds, intensity_sums, user_close_counts


def computeSchoolIndex():
    parser = argparse.ArgumentParser()
    parser.add_argument("--users", default="docs/data/iscc2026_users.json")
    parser.add_argument("--arena", default="docs/data/arena.json")
    parser.add_argument("--challenge", default="docs/data/challenge.json")
    parser.add_argument("--out", default="docs/data/school.json")
    args = parser.parse_args()

    user_rows = load_json(args.users)
    arena = load_json(args.arena)
    challenge = load_json(args.challenge)

    user_school_map = {row.get("username"): row.get("school") for row in user_rows if row.get("username")}
    solve_counts = build_solve_counts(arena)
    for name, count in build_solve_counts(challenge).items():
        solve_counts[name] += count

    small_accounts = {
        name
        for name in user_school_map.keys()
        if solve_counts.get(name, 0) <= SMALL_ACCOUNT_MAX_SOLVES
    }

    school_users = defaultdict(set)
    for name, school in user_school_map.items():
        if not school:
            continue
        school_users[school].add(name)

    threshold_seconds = THRESHOLD_MINUTES * 60
    collisions_arena, diff_arena, intensity_arena, close_users_arena = compute_school_collisions(
        arena, user_school_map, small_accounts, threshold_seconds, "arena"
    )
    collisions_chal, diff_chal, intensity_chal, close_users_chal = compute_school_collisions(
        challenge, user_school_map, small_accounts, threshold_seconds, "challenge"
    )

    all_schools = set(school_users.keys())
    results = []

    intensity_ratios = []
    close_users = defaultdict(lambda: defaultdict(int))
    for school, counts in close_users_arena.items():
        for user, count in counts.items():
            close_users[school][user] += count
    for school, counts in close_users_chal.items():
        for user, count in counts.items():
            close_users[school][user] += count

    for school in all_schools:
        total_users = len(school_users[school])
        small_count = sum(1 for name in school_users[school] if name in small_accounts)
        effective_users = total_users - small_count
        total_collisions = collisions_arena.get(school, 0) + collisions_chal.get(school, 0)
        total_diff_seconds = diff_arena.get(school, 0.0) + diff_chal.get(school, 0.0)
        total_intensity = intensity_arena.get(school, 0.0) + intensity_chal.get(school, 0.0)
        suspected_py = sum(1 for count in close_users[school].values() if count >= 5)
        if effective_users > 0:
            intensity_ratios.append(total_intensity / effective_users)

        results.append({
            "school": school,
            "n_total": total_users,
            "n_small": small_count,
            "n_effective": effective_users,
            "c_total": total_collisions,
            "diff_seconds": total_diff_seconds,
            "intensity": total_intensity,
            "suspected_py": suspected_py,
        })

    intensity_ratios.sort()
    trim = int(len(intensity_ratios) * TRIM_RATIO)
    trimmed = intensity_ratios[trim:len(intensity_ratios) - trim] if len(intensity_ratios) - trim * 2 > 0 else intensity_ratios
    theta = sum(trimmed) / len(trimmed) if trimmed else 0.0

    for item in results:
        n_effective = item["n_effective"]
        c_total = item["c_total"]
        diff_seconds = item["diff_seconds"]
        expected = theta * n_effective
        intensity = item.get("intensity", 0.0)
        z_value = (intensity - expected) / (math.sqrt(expected) + EPSILON)
        t_avg_minutes = (diff_seconds / 60 / c_total) if c_total > 0 else None
        if n_effective > 0:
            alpha = suspected_py / n_effective
            k_benefit = alpha * math.log10(n_effective + 1)
        else:
            alpha = None
            k_benefit = None
        if k_benefit is None:
            final_score = None
        else:
            final_score = z_value * (1 + k_benefit)

        item.update({
            "theta": theta,
            "expected": expected,
            "z": z_value,
            "t_avg_minutes": t_avg_minutes,
            "alpha": alpha,
            "k_benefit": k_benefit,
            "final_score": final_score,
        })
        item.pop("diff_seconds", None)

    results.sort(key=lambda x: (x["final_score"] is not None, x["final_score"]), reverse=True)

    output = {
        "meta": {
            "threshold_minutes": THRESHOLD_MINUTES,
            "small_account_max": SMALL_ACCOUNT_MAX_SOLVES,
            "epsilon": EPSILON,
            "trim_ratio": TRIM_RATIO,
            "theta": theta,
        },
        "schools": results,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote school index to {out_path}")


if __name__ == "__main__":
    computeSchoolIndex()
