#!/usr/bin/env python3
import argparse
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


@dataclass
class RepoGrowth:
    name_with_owner: str
    url: str
    stars: int
    weekly_stars: int
    previous_week_stars: int
    delta: int
    growth_rate: float
    language: str
    description: str


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
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"), help="GitHub token (or GITHUB_TOKEN env)")
    parser.add_argument("--min-stars", type=int, default=500, help="Minimum total star count")
    parser.add_argument("--max-repos", type=int, default=30, help="Maximum repositories to analyze")
    parser.add_argument(
        "--min-weekly-stars",
        type=int,
        default=20,
        help="Minimum stars in the most recent 7 days",
    )
    parser.add_argument(
        "--sort-by",
        choices=["delta", "weekly_stars", "growth_rate"],
        default="delta",
        help="Result sorting metric",
    )
    parser.add_argument("--top", type=int, default=15, help="Number of results to display")
    parser.add_argument(
        "--max-star-pages",
        type=int,
        default=20,
        help="Max stargazer pages per repo (100 records/page)",
    )
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    return parser.parse_args()


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
) -> Dict[str, int]:
    week_start = now - timedelta(days=7)
    prev_week_start = now - timedelta(days=14)

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

            if starred_at >= week_start:
                current_week += 1
            elif starred_at >= prev_week_start:
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
) -> List[RepoGrowth]:
    now = datetime.now(timezone.utc)
    result: List[RepoGrowth] = []

    for idx, repo in enumerate(repos, start=1):
        owner = repo["owner"]["login"]
        name = repo["name"]
        try:
            metrics = weekly_growth_for_repo(token, owner, name, now, max_star_pages)
        except RuntimeError as exc:
            print(
                f"Warning: skipping {repo['nameWithOwner']} due to API error: {exc}",
                file=sys.stderr,
            )
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
    else:
        result.sort(
            key=lambda r: (
                r.growth_rate if r.growth_rate != float("inf") else 10**9,
                r.weekly_stars,
                r.stars,
            ),
            reverse=True,
        )

    return result


def print_table(items: List[RepoGrowth], top: int) -> None:
    show = items[:top]
    if not show:
        print("No repositories matched the criteria.")
        return

    header = f"{'#':<3} {'Repo':<35} {'Stars':>9} {'7d':>6} {'Prev7d':>8} {'Delta':>7} {'Rate':>8}"
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
                "weekly_stars": x.weekly_stars,
                "previous_week_stars": x.previous_week_stars,
                "delta": x.delta,
                "growth_rate": "inf" if x.growth_rate == float("inf") else round(x.growth_rate, 4),
                "language": x.language,
                "description": x.description,
            }
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    load_env_file()
    args = parse_args()

    if not args.token:
        print(
            "Missing GitHub token. Pass --token or set GITHUB_TOKEN.",
            file=sys.stderr,
        )
        return 1

    repos = fetch_repositories(args.token, args.min_stars, args.max_repos)
    ranked = rank_repositories(
        args.token,
        repos,
        args.min_weekly_stars,
        args.sort_by,
        args.max_star_pages,
    )

    if args.json:
        print_json(ranked, args.top)
    else:
        print_table(ranked, args.top)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
