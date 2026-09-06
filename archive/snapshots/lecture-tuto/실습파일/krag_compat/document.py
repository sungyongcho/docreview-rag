from langchain_core.documents import Document


class KragDocument(Document):
    def __init__(self, page_content: str, metadata: dict | None = None):
        super().__init__(page_content=page_content, metadata=metadata or {})

    def get_summary(self) -> str:
        if len(self.page_content) <= 100:
            return self.page_content
        return self.page_content[:100] + "..."

