import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from backend.research_workflow.integrations.world_news import (
    _build_world_news_query,
    fetch_news,
)
from backend.shared.article_processing import clean_article_text, story_key


class WorldNewsTests(unittest.TestCase):
    def test_build_query_scopes_topic_to_company(self) -> None:
        query = _build_world_news_query(
            "aapl",
            "products OR competition",
            "Apple Inc.",
        )

        self.assertEqual(
            query,
            '(AAPL OR "Apple Inc.") AND (products OR competition)',
        )

    @patch.dict("os.environ", {"WORLD_NEWS_API_KEY": "test-key"})
    @patch("backend.research_workflow.integrations.world_news.requests.get")
    def test_fetch_news_keeps_only_current_full_text_articles(
        self,
        get: Mock,
    ) -> None:
        as_of = datetime.now(timezone.utc) - timedelta(minutes=1)
        date_from = as_of - timedelta(days=2)
        complete_article = " ".join(
            ["Apple described a new product strategy with enough detail for research."]
            * 12
        )
        response = Mock()
        response.ok = True
        response.status_code = 200
        response.headers = {
            "X-API-Quota-Request": "1.02",
            "X-API-Quota-Left": "48.98",
        }
        response.json.return_value = {
            "available": 3,
            "news": [
                {
                    "id": 123,
                    "title": "Apple announces a new product",
                    "text": complete_article,
                    "url": "https://example.com/apple-product",
                    "publish_date": (as_of - timedelta(hours=1)).isoformat(),
                    "authors": ["Jane Doe", "John Doe"],
                    "summary": None,
                },
                {
                    "id": 456,
                    "title": "Apple article with no body",
                    "text": "",
                    "url": "https://example.com/apple-empty",
                    "publish_date": (as_of - timedelta(hours=1)).isoformat(),
                    "authors": [],
                },
                {
                    "id": 789,
                    "title": "Apple future product update",
                    "text": complete_article,
                    "url": "https://example.com/apple-future",
                    "publish_date": (as_of + timedelta(hours=1)).isoformat(),
                    "authors": [],
                },
            ],
        }
        get.return_value = response

        articles = fetch_news(
            symbol="AAPL",
            company_name="Apple Inc.",
            query="products OR competition",
            date_from=date_from,
            date_to=as_of,
            limit=5,
        )

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["reference_id"], "123")
        self.assertEqual(articles[0]["author"], "Jane Doe, John Doe")
        self.assertIsNone(articles[0]["summary"])
        self.assertEqual(
            articles[0]["content"],
            complete_article,
        )
        _, kwargs = get.call_args
        self.assertEqual(kwargs["headers"], {"x-api-key": "test-key"})
        self.assertNotIn("api-key", kwargs["params"])
        self.assertEqual(kwargs["params"]["text-match-indexes"], "title,content")
        self.assertEqual(
            kwargs["params"]["latest-publish-date"],
            as_of.strftime("%Y-%m-%d %H:%M:%S"),
        )

    def test_clean_article_text_removes_navigation_and_related_content(self) -> None:
        title = "Apple Lays Off Staff As Vision Pro Demand Disappoints"
        body = [
            "Apple reportedly reduced the team after demand remained below expectations, creating execution risk for its spatial-computing strategy.",
            "The company is placing greater emphasis on smart glasses and artificial intelligence while continuing to support the current product.",
            "Investors are monitoring whether the revised roadmap can produce broader adoption without further delays or restructuring.",
        ]
        raw_text = "\n".join(
            [
                "Latest Headlines",
                "Top Stories",
                "Breaking News",
                title,
                "By Example Staff Writer",
                "| Published: 8/21/2026 4:47 PM ET",
                *body,
                "For comments and feedback contact: editorial@example.com",
                "RELATED NEWS",
                "Unrelated market headline",
            ]
        )

        cleaned = clean_article_text(title, raw_text)

        self.assertEqual(cleaned, "\n\n".join(body))
        self.assertNotIn("Latest Headlines", cleaned)
        self.assertNotIn("RELATED NEWS", cleaned)

    def test_story_key_ignores_case_and_headline_punctuation(self) -> None:
        self.assertEqual(
            story_key(
                "Apple cuts jobs in Siri, Vision Pro immersive video and gaming teams"
            ),
            story_key(
                "Apple Cuts Jobs in Siri, Vision Pro Immersive Video, and Gaming Teams"
            ),
        )


if __name__ == "__main__":
    unittest.main()
