"""共通データモデル"""
from dataclasses import dataclass
from datetime import date


@dataclass
class DeadlineEntry:
    """1件の締切"""
    company: str
    event_title: str
    deadline: date
    url: str
    source: str
    description: str = ""

    def key(self) -> str:
        """重複判定用のキー。カレンダー側の description に埋め込まれる。"""
        return f"{self.source}|{self.company}|{self.event_title}|{self.deadline}"
