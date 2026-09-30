import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from backend.research_workflow.integrations import tavily
from backend.shared.article_processing import clean_article_text, story_key


class TavilyTests(unittest.TestCase):
    @patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"})
    @patch("backend.research_workflow.integrations.tavily.requests.post")
    def test_search_keeps_only_dated_results_within_as_of(self, post: Mock) -> None:
        as_of = datetime.now(timezone.utc) - timedelta(minutes=1)
        response = Mock(ok=True)
        response.json.return_value = {
            "results": [
                {
                    "title": "Apple launches product",
                    "url": "https://example.com/one",
                    "content": "Apple launch",
                    "published_date": (as_of - timedelta(hours=1)).isoformat(),
                },
                {
                    "title": "Undated",
                    "url": "https://example.com/two",
                    "content": "Apple",
                    "published_date": None,
                },
                {
                    "title": "Future",
                    "url": "https://example.com/three",
                    "content": "Apple",
                    "published_date": (as_of + timedelta(hours=1)).isoformat(),
                },
                {
                    "title": "Apple RFC dated update",
                    "url": "https://example.com/rfc",
                    "content": "Apple risk update",
                    "published_date": (as_of - timedelta(days=1)).strftime(
                        "%a, %d %b %Y %H:%M:%S GMT"
                    ),
                },
                {
                    "title": "Ambiguous same day",
                    "url": "https://example.com/four",
                    "content": "Apple",
                    "published_date": as_of.date().isoformat(),
                },
            ]
        }
        post.return_value = response
        results, rejected = tavily.search(
            query="Apple product",
            topic="news",
            date_from=as_of - timedelta(days=2),
            as_of=as_of,
            limit=5,
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(rejected, 3)
        self.assertEqual(results[0].source_url, "https://example.com/one")
        payload = post.call_args.kwargs["json"]
        self.assertTrue(payload["filter_by_published_date"])
        self.assertFalse(payload["include_raw_content"])
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"], "Bearer test-key"
        )

    @patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"})
    @patch("backend.research_workflow.integrations.tavily.requests.post")
    def test_extract_reports_partial_failure(self, post: Mock) -> None:
        response = Mock(ok=True)
        response.json.return_value = {
            "results": [
                {"url": "https://example.com/one", "raw_content": "Apple source text"}
            ],
            "failed_results": [
                {"url": "https://example.com/two", "error": "unavailable"}
            ],
        }
        post.return_value = response
        pages, failed = tavily.extract(
            ["https://example.com/one", "https://example.com/two"]
        )
        self.assertEqual(pages[0].content, "Apple source text")
        self.assertEqual(failed, ["https://example.com/two"])
        self.assertEqual(post.call_args.kwargs["json"]["format"], "text")

    def test_clean_article_text_removes_navigation_and_related_content(self) -> None:
        title = "Apple Lays Off Staff As Vision Pro Demand Disappoints"
        body = "\n".join(  # noqa: FLY002 - page lines
            [
                "Latest Headlines",
                "Top Stories",
                title,
                "Apple reportedly reduced the team after demand remained below expectations, creating execution risk for its spatial-computing strategy.",
                "The company is placing greater emphasis on smart glasses and artificial intelligence while continuing to support the current product.",
                "Investors are monitoring whether the revised roadmap can produce broader adoption without further delays or restructuring.",
                "RELATED NEWS",
                "Unrelated market headline",
            ]
        )
        cleaned = clean_article_text(title, body)
        self.assertIn("Apple reportedly reduced", cleaned)
        self.assertNotIn("Latest Headlines", cleaned)

    def test_story_key_ignores_case_and_headline_punctuation(self) -> None:
        self.assertEqual(
            story_key("Apple launches new iPhone!"),
            story_key("APPLE launches new iPhone"),
        )
