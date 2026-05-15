import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_time(value):
    return datetime.strptime(value, TIME_FORMAT)


def sliding_window_max(times, window_seconds):
    if not times:
        return 0, None, None, None, None
    times_sorted = sorted(times)
    max_count = 1
    max_start = times_sorted[0]
    max_end = times_sorted[0]
    max_left = 0
    max_right = 0
    left = 0
    for right, t in enumerate(times_sorted):
        while (t - times_sorted[left]).total_seconds() > window_seconds:
            left += 1
        count = right - left + 1
        if count > max_count:
            max_count = count
            max_start = times_sorted[left]
            max_end = t
            max_left = left
            max_right = right
    return max_count, max_start, max_end, max_left, max_right


def sliding_window_max_entries(entries, window_seconds):
    if not entries:
        return 0, None, None, []
    entries_sorted = sorted(entries, key=lambda e: e["time"])
    times = [e["time"] for e in entries_sorted]
    count, start, end, left, right = sliding_window_max(times, window_seconds)
    if left is None or right is None:
        return 0, None, None, []
    users = [e["name"] for e in entries_sorted[left : right + 1]]
    return count, start, end, users


def build_time_buckets(times, bucket_minutes):
    if not times:
        return []
    times_sorted = sorted(times)
    bucket_seconds = int(bucket_minutes * 60)
    start = times_sorted[0]
    end = times_sorted[-1]
    buckets = []
    current = start
    idx = 0
    while current <= end:
        bucket_end = current + timedelta(seconds=bucket_seconds)
        count = 0
        while idx < len(times_sorted) and times_sorted[idx] < bucket_end:
            count += 1
            idx += 1
        buckets.append({
            "start": current.strftime(TIME_FORMAT),
            "count": count,
        })
        current = bucket_end
    return buckets


def analyze_challenges(challenges, user_school_map, window_minutes, bucket_minutes, early_n):
    per_challenge = []
    unmatched_names = Counter()
    school_stats = defaultdict(lambda: {
        "total_solves": 0,
        "early_solves": 0,
        "rank_sum": 0,
        "rank_count": 0,
        "ranks": [],
        "unique_challenges": set(),
    })

    window_seconds = int(window_minutes * 60)

    for category, items in challenges.items():
        for challenge_id, info in items.items():
            solves = info.get("solves", [])
            solves_with_time = []
            solve_times = []
            solve_entries_by_school = defaultdict(list)
            solve_schools_in_order = []

            for solve in solves:
                name = solve.get("name", "")
                time_str = solve.get("date", "")
                if not name or not time_str:
                    continue
                try:
                    t = parse_time(time_str)
                except ValueError:
                    continue

                school = user_school_map.get(name)
                if school is None:
                    unmatched_names[name] += 1
                else:
                    solve_entries_by_school[school].append({
                        "time": t,
                        "name": name,
                    })

                solves_with_time.append({
                    "name": name,
                    "school": school,
                    "time": t,
                    "id": solve.get("id"),
                })
                solve_times.append(t)

            solves_with_time.sort(key=lambda s: s["time"])
            solve_times = [s["time"] for s in solves_with_time]
            solve_schools_in_order = [s["school"] for s in solves_with_time]

            total_solves = len(solves_with_time)
            first_solve_time = solve_times[0] if solve_times else None
            last_solve_time = solve_times[-1] if solve_times else None

            time_to_first_early = None
            if total_solves >= early_n:
                time_to_first_early = (solve_times[early_n - 1] - solve_times[0]).total_seconds()

            total_window_max, total_window_start, total_window_end, _, _ = sliding_window_max(
                solve_times, window_seconds
            )

            school_window_max = []
            for school, entries in solve_entries_by_school.items():
                count, start, end, users = sliding_window_max_entries(entries, window_seconds)
                school_window_max.append({
                    "school": school,
                    "count": count,
                    "start": start.strftime(TIME_FORMAT) if start else None,
                    "end": end.strftime(TIME_FORMAT) if end else None,
                    "users": users,
                })
            school_window_max.sort(key=lambda x: x["count"], reverse=True)

            early_school_counts = Counter(
                s for s in solve_schools_in_order[:early_n] if s is not None
            )
            early_school_top = [
                {"school": school, "count": count}
                for school, count in early_school_counts.most_common(10)
            ]

            buckets = build_time_buckets(solve_times, bucket_minutes)

            for rank, solve in enumerate(solves_with_time, start=1):
                school = solve["school"]
                if school is None:
                    continue
                school_stats[school]["total_solves"] += 1
                if rank <= early_n:
                    school_stats[school]["early_solves"] += 1
                school_stats[school]["rank_sum"] += rank
                school_stats[school]["rank_count"] += 1
                school_stats[school]["ranks"].append(rank)
                school_stats[school]["unique_challenges"].add(
                    f"{category}:{challenge_id}"
                )

            per_challenge.append({
                "category": category,
                "challenge_id": challenge_id,
                "challenge_name": info.get("name"),
                "total_solves": total_solves,
                "first_solve_time": first_solve_time.strftime(TIME_FORMAT) if first_solve_time else None,
                "last_solve_time": last_solve_time.strftime(TIME_FORMAT) if last_solve_time else None,
                "time_to_first_early_seconds": time_to_first_early,
                "overall_window_max": {
                    "count": total_window_max,
                    "start": total_window_start.strftime(TIME_FORMAT) if total_window_start else None,
                    "end": total_window_end.strftime(TIME_FORMAT) if total_window_end else None,
                },
                "school_window_max": school_window_max[:10],
                "early_school_top": early_school_top,
                "time_buckets": buckets,
            })

    return per_challenge, school_stats, unmatched_names


def finalize_school_stats(school_stats):
    results = []
    for school, stats in school_stats.items():
        ranks_sorted = sorted(stats["ranks"])
        rank_count = stats["rank_count"]
        avg_rank = stats["rank_sum"] / rank_count if rank_count else None
        median_rank = None
        if ranks_sorted:
            mid = len(ranks_sorted) // 2
            if len(ranks_sorted) % 2 == 1:
                median_rank = ranks_sorted[mid]
            else:
                median_rank = (ranks_sorted[mid - 1] + ranks_sorted[mid]) / 2

        results.append({
            "school": school,
            "total_solves": stats["total_solves"],
            "early_solves": stats["early_solves"],
            "average_rank": avg_rank,
            "median_rank": median_rank,
            "unique_challenges": len(stats["unique_challenges"]),
        })

    results.sort(key=lambda x: x["total_solves"], reverse=True)
    return results


def dataAnalysis():
    parser = argparse.ArgumentParser()
    parser.add_argument("--users", default="docs/data/iscc2026_users.json")
    parser.add_argument("--arena", default="docs/data/arena.json")
    parser.add_argument("--challenge", default="docs/data/challenge.json")
    parser.add_argument("--window-minutes", type=float, default=5)
    parser.add_argument("--bucket-minutes", type=float, default=1)
    parser.add_argument("--early-n", type=int, default=200)
    parser.add_argument("--out-dir", default="docs/analysis")
    args = parser.parse_args()

    user_rows = load_json(args.users)
    user_school_map = {row["username"]: row["school"] for row in user_rows}

    arena = load_json(args.arena)
    challenge = load_json(args.challenge)

    per_challenge_arena, school_stats_arena, unmatched_arena = analyze_challenges(
        arena, user_school_map, args.window_minutes, args.bucket_minutes, args.early_n
    )
    per_challenge_chal, school_stats_chal, unmatched_chal = analyze_challenges(
        challenge, user_school_map, args.window_minutes, args.bucket_minutes, args.early_n
    )

    all_school_stats = defaultdict(lambda: {
        "total_solves": 0,
        "early_solves": 0,
        "rank_sum": 0,
        "rank_count": 0,
        "ranks": [],
        "unique_challenges": set(),
    })

    for school, stats in school_stats_arena.items():
        all_school_stats[school]["total_solves"] += stats["total_solves"]
        all_school_stats[school]["early_solves"] += stats["early_solves"]
        all_school_stats[school]["rank_sum"] += stats["rank_sum"]
        all_school_stats[school]["rank_count"] += stats["rank_count"]
        all_school_stats[school]["ranks"].extend(stats["ranks"])
        all_school_stats[school]["unique_challenges"].update(stats["unique_challenges"])

    for school, stats in school_stats_chal.items():
        all_school_stats[school]["total_solves"] += stats["total_solves"]
        all_school_stats[school]["early_solves"] += stats["early_solves"]
        all_school_stats[school]["rank_sum"] += stats["rank_sum"]
        all_school_stats[school]["rank_count"] += stats["rank_count"]
        all_school_stats[school]["ranks"].extend(stats["ranks"])
        all_school_stats[school]["unique_challenges"].update(stats["unique_challenges"])

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "analysis_by_challenge_arena.json").write_text(
        json.dumps(per_challenge_arena, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "analysis_by_challenge_challenge.json").write_text(
        json.dumps(per_challenge_chal, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (out_dir / "analysis_by_school.json").write_text(
        json.dumps(finalize_school_stats(all_school_stats), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    unmatched = unmatched_arena + unmatched_chal
    unmatched_sorted = [
        {"name": name, "count": count}
        for name, count in unmatched.most_common()
    ]
    (out_dir / "unmatched_names.json").write_text(
        json.dumps(unmatched_sorted, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary = {
        "window_minutes": args.window_minutes,
        "bucket_minutes": args.bucket_minutes,
        "early_n": args.early_n,
        "arena_challenges": len(per_challenge_arena),
        "challenge_challenges": len(per_challenge_chal),
        "unmatched_names": len(unmatched_sorted),
    }

    (out_dir / "analysis_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Wrote analysis files to {out_dir}")


if __name__ == "__main__":
    dataAnalysis()
