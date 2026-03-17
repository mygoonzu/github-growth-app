import argparse
import unittest

import github_growth_app as app


class CoreLogicTests(unittest.TestCase):
    def test_resolve_window_days_default_week(self):
        self.assertEqual(app.resolve_window_days("week", None), 7)

    def test_resolve_window_days_default_month(self):
        self.assertEqual(app.resolve_window_days("month", None), 30)

    def test_resolve_window_days_custom(self):
        self.assertEqual(app.resolve_window_days("week", 14), 14)

    def test_apply_config_defaults_only_overwrites_defaults(self):
        args = argparse.Namespace(
            mode="growth",
            min_stars=500,
            min_forks=0,
            min_watchers=0,
            min_network=0,
            max_repos=30,
            min_weekly_stars=20,
            period="week",
            window_days=None,
            sort_by="delta",
            top=15,
            max_star_pages=20,
            json=False,
            csv=None,
        )
        config = {"min_stars": 1000, "top": 50, "sort_by": "stars"}
        updated = app.apply_config_defaults(args, config)
        self.assertEqual(updated.min_stars, 1000)
        self.assertEqual(updated.top, 50)
        self.assertEqual(updated.sort_by, "stars")

        # Simulate CLI override: non-default value should not be overwritten by config
        args.min_stars = 700
        updated2 = app.apply_config_defaults(args, {"min_stars": 1000})
        self.assertEqual(updated2.min_stars, 700)

    def test_apply_base_filters(self):
        repos = [
            {"nameWithOwner": "a/x", "stargazerCount": 600, "forkCount": 50, "watchersCount": 10, "networkCount": 55},
            {"nameWithOwner": "b/y", "stargazerCount": 300, "forkCount": 200, "watchersCount": 20, "networkCount": 250},
            {"nameWithOwner": "c/z", "stargazerCount": 1000, "forkCount": 300, "watchersCount": 40, "networkCount": 350},
        ]
        filtered = app.apply_base_filters(
            repos,
            min_stars=500,
            min_forks=100,
            min_watchers=15,
            min_network=100,
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["nameWithOwner"], "c/z")

    def test_sort_top_repositories(self):
        repos = [
            {"nameWithOwner": "a/x", "stargazerCount": 100, "forkCount": 20, "watchersCount": 4, "networkCount": 30},
            {"nameWithOwner": "b/y", "stargazerCount": 200, "forkCount": 10, "watchersCount": 8, "networkCount": 25},
            {"nameWithOwner": "c/z", "stargazerCount": 150, "forkCount": 50, "watchersCount": 2, "networkCount": 80},
        ]
        app.sort_top_repositories(repos, "forks")
        self.assertEqual(repos[0]["nameWithOwner"], "c/z")

        app.sort_top_repositories(repos, "watchers")
        self.assertEqual(repos[0]["nameWithOwner"], "b/y")

        app.sort_top_repositories(repos, "network")
        self.assertEqual(repos[0]["nameWithOwner"], "c/z")

        app.sort_top_repositories(repos, "stars")
        self.assertEqual(repos[0]["nameWithOwner"], "b/y")


if __name__ == "__main__":
    unittest.main()
