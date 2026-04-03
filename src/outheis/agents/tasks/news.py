"""
News headlines task — fetches headlines from news sites.

PoC: Süddeutsche Zeitung (sz.de)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from outheis.agents.tasks.base import Task, TaskResult, TaskSchedule, TaskSource


@dataclass
class NewsHeadlinesTask(Task):
    """
    Fetch top headlines from a news source.
    
    Default: sz.de (Süddeutsche Zeitung)
    """
    
    source_url: str = "https://www.sz.de"
    source_name: str = "SZ"
    max_headlines: int = 5
    
    def execute(self) -> TaskResult:
        """Fetch headlines from the news source."""
        try:
            # Fetch page
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            }
            response = httpx.get(self.source_url, headers=headers, timeout=10.0, follow_redirects=True)
            response.raise_for_status()
            
            # Parse headlines
            soup = BeautifulSoup(response.text, "html.parser")
            headlines = self._extract_headlines(soup)
            
            return TaskResult(
                success=True,
                data={
                    "source": self.source_name,
                    "url": self.source_url,
                    "headlines": headlines[:self.max_headlines],
                    "fetched_at": datetime.now().isoformat(),
                }
            )
        
        except Exception as e:
            return TaskResult(
                success=False,
                error=str(e),
            )
    
    def _extract_headlines(self, soup: BeautifulSoup) -> list[str]:
        """Extract headlines from parsed HTML."""
        headlines = []
        
        # SZ uses various headline elements
        # Try multiple selectors
        selectors = [
            "h2.css-1kkg5u2",  # Main headlines
            "h3.css-1kkg5u2",  # Secondary
            "article h2",
            "article h3",
            "[data-testid='teaser-headline']",
            ".teaser-headline",
            "h2 a",
            "h3 a",
        ]
        
        seen = set()
        for selector in selectors:
            for el in soup.select(selector):
                text = el.get_text(strip=True)
                # Clean up
                text = re.sub(r'\s+', ' ', text)
                # Skip short or duplicate
                if len(text) > 15 and text not in seen:
                    seen.add(text)
                    headlines.append(text)
        
        # Fallback: find any h2/h3 with reasonable text
        if not headlines:
            for tag in ["h2", "h3"]:
                for el in soup.find_all(tag):
                    text = el.get_text(strip=True)
                    text = re.sub(r'\s+', ' ', text)
                    if 15 < len(text) < 200 and text not in seen:
                        seen.add(text)
                        headlines.append(text)
        
        return headlines
    
    def format_for_agenda(self, result: TaskResult) -> str:
        """Format headlines for Daily.md insertion."""
        if not result.success:
            return f"## {self.source_name} (Fehler)\n\n_{result.error}_\n"
        
        data = result.data
        lines = [f"## {self.source_name}"]
        
        for headline in data.get("headlines", []):
            lines.append(f"- {headline}")
        
        return "\n".join(lines) + "\n"
    
    def to_dict(self) -> dict:
        """Serialize task including news-specific fields."""
        data = super().to_dict()
        data.update({
            "source_url": self.source_url,
            "source_name": self.source_name,
            "max_headlines": self.max_headlines,
        })
        return data


def create_sz_task(
    task_id: str = "sz-headlines",
    times: list[str] | None = None,
    source: "TaskSource | None" = None,
    instruction: str = "",
) -> NewsHeadlinesTask:
    """Create an SZ headlines task with default settings."""
    return NewsHeadlinesTask(
        id=task_id,
        name="SZ Schlagzeilen",
        instruction=instruction or "2x täglich die wichtigsten Schlagzeilen der SZ",
        source=source,
        schedule=TaskSchedule.TWICE_DAILY,
        times=times or ["08:00", "18:00"],
        source_url="https://www.sz.de",
        source_name="SZ",
        max_headlines=5,
        target_agent="agenda",
    )
