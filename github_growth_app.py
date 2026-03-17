#!/usr/bin/env python3
import argparse
import csv
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, request
from urllib.parse import parse_qs, urlparse

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
GITHUB_REST_URL = "https://api.github.com"
DEFAULTS: Dict[str, Any] = {
    "mode": "growth",
    "min_stars": 500,
    "min_forks": 0,
    "min_watchers": 0,
    "min_network": 0,
    "max_repos": 30,
    "min_weekly_stars": 20,
    "period": "week",
    "window_days": None,
    "sort_by": "delta",
    "top": 15,
    "max_star_pages": 20,
    "json": False,
    "csv": None,
}


@dataclass
class RepoGrowth:
    name_with_owner: str
    url: str
    stars: int
    forks: int
    watchers: int
    network: int
    weekly_stars: int
    previous_week_stars: int
    delta: int
    growth_rate: float
    language: str
    description: str


@dataclass
class RankResult:
    items: List[RepoGrowth]
    skipped_api_errors: int


def load_env_file(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("\"'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        # Ignore .env read errors; system environment variables may still be available.
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Find public GitHub repositories above a star threshold and rank weekly star growth."
        )
    )
    parser.add_argument(
        "--mode",
        choices=["growth", "top"],
        default="growth",
        help="growth: rank by star growth, top: rank by total stars",
    )
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"), help="GitHub token (or GITHUB_TOKEN env)")
    parser.add_argument("--min-stars", type=int, default=500, help="Minimum total star count")
    parser.add_argument("--min-forks", type=int, default=0, help="Minimum fork count")
    parser.add_argument("--min-watchers", type=int, default=0, help="Minimum watcher count")
    parser.add_argument("--min-network", type=int, default=0, help="Minimum network count")
    parser.add_argument("--max-repos", type=int, default=30, help="Maximum repositories to analyze")
    parser.add_argument(
        "--min-weekly-stars",
        type=int,
        default=20,
        help="Minimum stars in the latest analysis window",
    )
    parser.add_argument(
        "--period",
        choices=["week", "month"],
        default="week",
        help="Analysis window preset: week=7 days, month=30 days",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=None,
        help="Custom analysis window in days (overrides --period)",
    )
    parser.add_argument(
        "--sort-by",
        choices=["delta", "weekly_stars", "growth_rate", "stars", "forks", "watchers", "network"],
        default="delta",
        help="Result sorting metric (growth mode or top mode)",
    )
    parser.add_argument("--top", type=int, default=15, help="Number of results to display")
    parser.add_argument("--config", type=str, default=None, help="Path to JSON/YAML config file")
    parser.add_argument("--csv", type=str, default=None, help="Write output rows to CSV file")
    parser.add_argument(
        "--max-star-pages",
        type=int,
        default=20,
        help="Max stargazer pages per repo (100 records/page)",
    )
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    return parser.parse_args()


def load_config_file(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    if path.endswith(".json"):
        data = json.loads(raw)
    elif path.endswith(".yaml") or path.endswith(".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "YAML config requires PyYAML. Install with: pip install pyyaml"
            ) from exc
        data = yaml.safe_load(raw)
    else:
        raise RuntimeError("Unsupported config format. Use .json, .yaml, or .yml")
    if not isinstance(data, dict):
        raise RuntimeError("Config file must contain a JSON/YAML object at top level.")
    return data


def apply_config_defaults(args: argparse.Namespace, config: Dict[str, Any]) -> argparse.Namespace:
    for key, default_value in DEFAULTS.items():
        if key not in config:
            continue
        if not hasattr(args, key):
            continue
        current_value = getattr(args, key)
        if current_value == default_value:
            setattr(args, key, config[key])
    return args


def resolve_window_days(period: str, window_days: Optional[int]) -> int:
    if window_days is not None:
        return int(window_days)
    return 7 if period == "week" else 30


def github_json_request(
    token: str,
    url: str,
    *,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    accept: str = "application/vnd.github+json",
    retries: int = 3,
) -> Tuple[Any, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", accept)
    req.add_header("User-Agent", "github-growth-app")
    if payload is not None:
        req.add_header("Content-Type", "application/json")

    last_error: Optional[Exception] = None
    for attempt in range(retries):
        try:
            with request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body), resp.headers
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            transient = exc.code in (500, 502, 503, 504)
            last_error = RuntimeError(f"GitHub API HTTP {exc.code}: {detail}")
            if transient and attempt < retries - 1:
                time.sleep(0.8 * (attempt + 1))
                continue
            raise last_error from exc
        except error.URLError as exc:
            last_error = RuntimeError(f"Cannot connect to GitHub API: {exc}")
            if attempt < retries - 1:
                time.sleep(0.8 * (attempt + 1))
                continue
            raise last_error from exc

    if last_error:
        raise last_error
    raise RuntimeError("Unable to call GitHub API.")


def github_graphql(token: str, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
    data, _ = github_json_request(
        token,
        GITHUB_GRAPHQL_URL,
        method="POST",
        payload={"query": query, "variables": variables},
        accept="application/json",
    )

    if "errors" in data:
        raise RuntimeError(f"GitHub GraphQL returned errors: {data['errors']}")
    return data["data"]


def fetch_repositories(token: str, min_stars: int, max_repos: int) -> List[Dict[str, Any]]:
    query = """
    query ($queryString: String!, $cursor: String) {
      search(query: $queryString, type: REPOSITORY, first: 50, after: $cursor) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          ... on Repository {
            name
            owner {
              login
            }
            nameWithOwner
            url
            stargazerCount
            forkCount
            watchers {
              totalCount
            }
            description
            primaryLanguage {
              name
            }
          }
        }
      }
    }
    """

    query_string = f"stars:>={min_stars} is:public archived:false fork:false sort:stars-desc"
    repos: List[Dict[str, Any]] = []
    cursor: Optional[str] = None

    while len(repos) < max_repos:
        data = github_graphql(token, query, {"queryString": query_string, "cursor": cursor})
        search = data["search"]
        nodes = search.get("nodes", [])

        for node in nodes:
            if not node:
                continue
            repos.append(node)
            if len(repos) >= max_repos:
                break

        if not search["pageInfo"]["hasNextPage"] or len(repos) >= max_repos:
            break
        cursor = search["pageInfo"]["endCursor"]

    return repos


def parse_iso8601(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def enrich_repository_metrics(token: str, owner: str, name: str) -> Dict[str, int]:
    url = f"{GITHUB_REST_URL}/repos/{owner}/{name}"
    data, _ = github_json_request(token, url)
    if not isinstance(data, dict):
        return {"forks": 0, "watchers": 0, "network": 0}
    return {
        "forks": int(data.get("forks_count", 0) or 0),
        "watchers": int(data.get("subscribers_count", 0) or 0),
        "network": int(data.get("network_count", 0) or 0),
    }


def apply_base_filters(
    repos: List[Dict[str, Any]],
    min_stars: int,
    min_forks: int,
    min_watchers: int,
    min_network: int,
) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for repo in repos:
        stars = int(repo.get("stargazerCount", 0) or 0)
        forks = int(repo.get("forkCount", 0) or 0)
        watchers = int(repo.get("watchersCount", 0) or 0)
        network = int(repo.get("networkCount", 0) or 0)
        if stars < min_stars:
            continue
        if forks < min_forks:
            continue
        if watchers < min_watchers:
            continue
        if network < min_network:
            continue
        filtered.append(repo)
    return filtered


def sort_top_repositories(repos: List[Dict[str, Any]], sort_by: str) -> None:
    if sort_by == "forks":
        repos.sort(key=lambda x: x.get("forkCount", 0), reverse=True)
    elif sort_by == "watchers":
        repos.sort(key=lambda x: x.get("watchersCount", 0), reverse=True)
    elif sort_by == "network":
        repos.sort(key=lambda x: x.get("networkCount", 0), reverse=True)
    else:
        repos.sort(key=lambda x: x.get("stargazerCount", 0), reverse=True)


def parse_last_page(link_header: str) -> Optional[int]:
    if not link_header:
        return None
    for part in [x.strip() for x in link_header.split(",")]:
        if 'rel="last"' not in part:
            continue
        match = re.search(r"<([^>]+)>", part)
        if not match:
            continue
        parsed = urlparse(match.group(1))
        page_vals = parse_qs(parsed.query).get("page")
        if not page_vals:
            continue
        try:
            return int(page_vals[0])
        except ValueError:
            return None
    return None


def weekly_growth_for_repo(
    token: str,
    owner: str,
    name: str,
    now: datetime,
    max_star_pages: int,
    window_days: int,
) -> Dict[str, int]:
    try:
        return weekly_growth_for_repo_graphql(
            token=token,
            owner=owner,
            name=name,
            now=now,
            max_star_pages=max_star_pages,
            window_days=window_days,
        )
    except RuntimeError:
        # Fallback to REST if GraphQL is unstable for a repository.
        return weekly_growth_for_repo_rest(
            token=token,
            owner=owner,
            name=name,
            now=now,
            max_star_pages=max_star_pages,
            window_days=window_days,
        )


def weekly_growth_for_repo_graphql(
    token: str,
    owner: str,
    name: str,
    now: datetime,
    max_star_pages: int,
    window_days: int,
) -> Dict[str, int]:
    query = """
    query ($owner: String!, $name: String!, $cursor: String) {
      repository(owner: $owner, name: $name) {
        stargazers(first: 100, after: $cursor, orderBy: {field: STARRED_AT, direction: DESC}) {
          pageInfo {
            hasNextPage
            endCursor
          }
          edges {
            starredAt
          }
        }
      }
    }
    """

    current_start = now - timedelta(days=window_days)
    previous_start = now - timedelta(days=2 * window_days)

    current_week = 0
    previous_week = 0
    cursor: Optional[str] = None
    should_stop = False

    for _ in range(max_star_pages):
        data = github_graphql(
            token,
            query,
            {"owner": owner, "name": name, "cursor": cursor},
        )
        stargazers = data["repository"]["stargazers"]
        edges = stargazers.get("edges", [])
        if not edges:
            break

        for edge in edges:
            starred_at_raw = edge.get("starredAt")
            if not starred_at_raw:
                continue
            starred_at = parse_iso8601(starred_at_raw)

            if starred_at >= current_start:
                current_week += 1
            elif starred_at >= previous_start:
                previous_week += 1
            else:
                should_stop = True
                break

        if should_stop:
            break
        if not stargazers["pageInfo"]["hasNextPage"]:
            break
        cursor = stargazers["pageInfo"]["endCursor"]

        # Small pause to reduce request burst.
        time.sleep(0.05)

    return {
        "current_week": current_week,
        "previous_week": previous_week,
    }


def weekly_growth_for_repo_rest(
    token: str,
    owner: str,
    name: str,
    now: datetime,
    max_star_pages: int,
    window_days: int,
) -> Dict[str, int]:
    current_start = now - timedelta(days=window_days)
    previous_start = now - timedelta(days=2 * window_days)

    current_week = 0
    previous_week = 0
    should_stop = False

    first_url = f"{GITHUB_REST_URL}/repos/{owner}/{name}/stargazers?per_page=100&page=1"
    first_page_data, first_headers = github_json_request(
        token,
        first_url,
        accept="application/vnd.github.star+json",
    )
    if not isinstance(first_page_data, list):
        return {"current_week": 0, "previous_week": 0}

    last_page = parse_last_page(first_headers.get("Link", "")) or 1
    start_page = max(1, last_page - max_star_pages + 1)

    for page in range(last_page, start_page - 1, -1):
        if page == 1:
            page_data = first_page_data
        else:
            page_url = f"{GITHUB_REST_URL}/repos/{owner}/{name}/stargazers?per_page=100&page={page}"
            page_data, _ = github_json_request(
                token,
                page_url,
                accept="application/vnd.github.star+json",
            )
        if not isinstance(page_data, list) or not page_data:
            continue

        events = [event for event in page_data if event.get("starred_at")]
        events.sort(key=lambda x: x["starred_at"], reverse=True)
        for star_event in events:
            starred_at_raw = star_event.get("starred_at")
            if not starred_at_raw:
                continue
            starred_at = parse_iso8601(starred_at_raw)

            if starred_at >= current_start:
                current_week += 1
            elif starred_at >= previous_start:
                previous_week += 1
            else:
                should_stop = True
                break

        if should_stop:
            break

        # Small pause to reduce request burst.
        time.sleep(0.05)

    return {
        "current_week": current_week,
        "previous_week": previous_week,
    }


def rank_repositories(
    token: str,
    repos: List[Dict[str, Any]],
    min_weekly_stars: int,
    sort_by: str,
    max_star_pages: int,
    window_days: int,
) -> RankResult:
    now = datetime.now(timezone.utc)
    result: List[RepoGrowth] = []
    skipped_api_errors = 0

    for idx, repo in enumerate(repos, start=1):
        owner = repo["owner"]["login"]
        name = repo["name"]
        try:
            metrics = weekly_growth_for_repo(
                token,
                owner,
                name,
                now,
                max_star_pages,
                window_days,
            )
        except RuntimeError as exc:
            print(
                f"Warning: skipping {repo['nameWithOwner']} due to API error: {exc}",
                file=sys.stderr,
            )
            skipped_api_errors += 1
            continue

        weekly = metrics["current_week"]
        previous = metrics["previous_week"]
        if weekly < min_weekly_stars:
            continue

        delta = weekly - previous
        growth_rate = float("inf") if previous == 0 and weekly > 0 else (weekly / previous if previous > 0 else 0.0)

        result.append(
            RepoGrowth(
                name_with_owner=repo["nameWithOwner"],
                url=repo["url"],
                stars=repo["stargazerCount"],
                forks=repo.get("forkCount", 0),
                watchers=repo.get("watchersCount", 0),
                network=repo.get("networkCount", 0),
                weekly_stars=weekly,
                previous_week_stars=previous,
                delta=delta,
                growth_rate=growth_rate,
                language=(repo.get("primaryLanguage") or {}).get("name") or "N/A",
                description=(repo.get("description") or "").strip(),
            )
        )

        print(f"Analyzed {idx}/{len(repos)} repositories...", file=sys.stderr)

    if sort_by == "delta":
        result.sort(key=lambda r: (r.delta, r.weekly_stars, r.stars), reverse=True)
    elif sort_by == "weekly_stars":
        result.sort(key=lambda r: (r.weekly_stars, r.delta, r.stars), reverse=True)
    elif sort_by == "stars":
        result.sort(key=lambda r: (r.stars, r.delta), reverse=True)
    elif sort_by == "forks":
        result.sort(key=lambda r: (r.forks, r.delta), reverse=True)
    elif sort_by == "watchers":
        result.sort(key=lambda r: (r.watchers, r.delta), reverse=True)
    elif sort_by == "network":
        result.sort(key=lambda r: (r.network, r.delta), reverse=True)
    else:
        result.sort(
            key=lambda r: (
                r.growth_rate if r.growth_rate != float("inf") else 10**9,
                r.weekly_stars,
                r.stars,
            ),
            reverse=True,
        )

    return RankResult(items=result, skipped_api_errors=skipped_api_errors)


def print_table(items: List[RepoGrowth], top: int, window_days: int) -> None:
    show = items[:top]
    if not show:
        print("No repositories matched the criteria.")
        return

    period_col = f"{window_days}d"
    prev_col = f"Prev{window_days}d"
    header = f"{'#':<3} {'Repo':<35} {'Stars':>9} {period_col:>6} {prev_col:>8} {'Delta':>7} {'Rate':>8}"
    print(header)
    print("-" * len(header))

    for i, item in enumerate(show, start=1):
        rate_str = "inf" if item.growth_rate == float("inf") else f"{item.growth_rate:.2f}x"
        repo_name = item.name_with_owner[:35]
        print(
            f"{i:<3} {repo_name:<35} {item.stars:>9} {item.weekly_stars:>6} "
            f"{item.previous_week_stars:>8} {item.delta:>7} {rate_str:>8}"
        )
        print(f"    {item.url}")


def print_json(items: List[RepoGrowth], top: int) -> None:
    payload = []
    for x in items[:top]:
        payload.append(
            {
                "repo": x.name_with_owner,
                "url": x.url,
                "stars": x.stars,
                "forks": x.forks,
                "watchers": x.watchers,
                "network": x.network,
                "weekly_stars": x.weekly_stars,
                "previous_week_stars": x.previous_week_stars,
                "delta": x.delta,
                "growth_rate": "inf" if x.growth_rate == float("inf") else round(x.growth_rate, 4),
                "language": x.language,
                "description": x.description,
            }
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def write_growth_csv(items: List[RepoGrowth], top: int, csv_path: str) -> None:
    fieldnames = [
        "repo",
        "url",
        "stars",
        "forks",
        "watchers",
        "network",
        "window_stars",
        "previous_window_stars",
        "delta",
        "growth_rate",
        "language",
        "description",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for x in items[:top]:
            writer.writerow(
                {
                    "repo": x.name_with_owner,
                    "url": x.url,
                    "stars": x.stars,
                    "forks": x.forks,
                    "watchers": x.watchers,
                    "network": x.network,
                    "window_stars": x.weekly_stars,
                    "previous_window_stars": x.previous_week_stars,
                    "delta": x.delta,
                    "growth_rate": "inf" if x.growth_rate == float("inf") else round(x.growth_rate, 4),
                    "language": x.language,
                    "description": x.description,
                }
            )


def print_top_table(repos: List[Dict[str, Any]], top: int) -> None:
    show = repos[:top]
    if not show:
        print("No repositories matched the criteria.")
        return

    header = (
        f"{'#':<3} {'Repo':<35} {'Stars':>9} {'Forks':>8} {'Watch':>7} {'Network':>8} {'Language':<15}"
    )
    print(header)
    print("-" * len(header))

    for i, repo in enumerate(show, start=1):
        lang = (repo.get("primaryLanguage") or {}).get("name") or "N/A"
        print(
            f"{i:<3} {repo['nameWithOwner'][:35]:<35} {repo['stargazerCount']:>9} "
            f"{repo.get('forkCount', 0):>8} {repo.get('watchersCount', 0):>7} "
            f"{repo.get('networkCount', 0):>8} {lang[:15]:<15}"
        )
        print(f"    {repo['url']}")


def print_top_json(repos: List[Dict[str, Any]], top: int) -> None:
    payload = []
    for repo in repos[:top]:
        payload.append(
            {
                "repo": repo["nameWithOwner"],
                "url": repo["url"],
                "stars": repo["stargazerCount"],
                "forks": repo.get("forkCount", 0),
                "watchers": repo.get("watchersCount", 0),
                "network": repo.get("networkCount", 0),
                "language": (repo.get("primaryLanguage") or {}).get("name") or "N/A",
                "description": (repo.get("description") or "").strip(),
            }
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def write_top_csv(repos: List[Dict[str, Any]], top: int, csv_path: str) -> None:
    fieldnames = ["repo", "url", "stars", "forks", "watchers", "network", "language", "description"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for repo in repos[:top]:
            writer.writerow(
                {
                    "repo": repo["nameWithOwner"],
                    "url": repo["url"],
                    "stars": repo["stargazerCount"],
                    "forks": repo.get("forkCount", 0),
                    "watchers": repo.get("watchersCount", 0),
                    "network": repo.get("networkCount", 0),
                    "language": (repo.get("primaryLanguage") or {}).get("name") or "N/A",
                    "description": (repo.get("description") or "").strip(),
                }
            )


def print_run_summary(
    *,
    mode: str,
    fetched: int,
    enriched_errors: int,
    after_filters: int,
    output_count: int,
    skipped_growth_api: int = 0,
    window_days: Optional[int] = None,
) -> None:
    summary_parts = [
        f"mode={mode}",
        f"fetched={fetched}",
        f"after_filters={after_filters}",
        f"output={output_count}",
        f"enrich_errors={enriched_errors}",
    ]
    if mode == "growth":
        summary_parts.append(f"growth_api_skips={skipped_growth_api}")
    if window_days is not None:
        summary_parts.append(f"window_days={window_days}")
    print("Summary: " + ", ".join(summary_parts), file=sys.stderr)


def main() -> int:
    load_env_file()
    args = parse_args()

    if args.config:
        config_data = load_config_file(args.config)
        args = apply_config_defaults(args, config_data)

    if not args.token:
        print(
            "Missing GitHub token. Pass --token or set GITHUB_TOKEN.",
            file=sys.stderr,
        )
        return 1

    window_days = resolve_window_days(args.period, args.window_days)

    if window_days <= 0:
        print("window_days must be > 0.", file=sys.stderr)
        return 1

    repos = fetch_repositories(args.token, args.min_stars, args.max_repos)
    fetched_count = len(repos)
    enrich_errors = 0
    for repo in repos:
        owner = repo["owner"]["login"]
        name = repo["name"]
        try:
            metrics = enrich_repository_metrics(args.token, owner, name)
        except RuntimeError as exc:
            print(
                f"Warning: failed to enrich {repo['nameWithOwner']} metrics: {exc}",
                file=sys.stderr,
            )
            metrics = {"forks": 0, "watchers": 0, "network": 0}
            enrich_errors += 1
        repo["forkCount"] = metrics["forks"]
        repo["watchersCount"] = metrics["watchers"]
        repo["networkCount"] = metrics["network"]
        if "watchers" in repo and isinstance(repo["watchers"], dict):
            repo["watchersCount"] = int(repo["watchers"].get("totalCount", repo["watchersCount"]) or 0)

    repos = apply_base_filters(
        repos,
        args.min_stars,
        args.min_forks,
        args.min_watchers,
        args.min_network,
    )
    filtered_count = len(repos)
    if args.mode == "top":
        sort_top_repositories(repos, args.sort_by)
        if args.json:
            print_top_json(repos, args.top)
        else:
            print_top_table(repos, args.top)
        if args.csv:
            write_top_csv(repos, args.top, args.csv)
            print(f"Wrote CSV: {args.csv}", file=sys.stderr)
        print_run_summary(
            mode="top",
            fetched=fetched_count,
            enriched_errors=enrich_errors,
            after_filters=filtered_count,
            output_count=min(args.top, len(repos)),
        )
        return 0

    rank_result = rank_repositories(
        args.token,
        repos,
        args.min_weekly_stars,
        args.sort_by,
        args.max_star_pages,
        window_days,
    )
    ranked = rank_result.items

    if args.json:
        print_json(ranked, args.top)
    else:
        print_table(ranked, args.top, window_days)
    if args.csv:
        write_growth_csv(ranked, args.top, args.csv)
        print(f"Wrote CSV: {args.csv}", file=sys.stderr)

    print_run_summary(
        mode="growth",
        fetched=fetched_count,
        enriched_errors=enrich_errors,
        after_filters=filtered_count,
        output_count=min(args.top, len(ranked)),
        skipped_growth_api=rank_result.skipped_api_errors,
        window_days=window_days,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
