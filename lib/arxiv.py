import httpx
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

ARXIV_API = "https://export.arxiv.org/api/query"


@dataclass
class ArxivPaper:
    id: str
    title: str
    abstract: str
    authors: list[str]
    categories: list[str]
    url: str
    published_at: datetime
