from kiwipiepy import Kiwi


class KiwiTokenizer:
    def __init__(self, model_type: str = "cong", typos: str | None = "basic"):
        if model_type in {"sbg", "knlm"}:
            model_type = "cong"

        self.model_type = model_type
        self.typos = typos
        self.kiwi = Kiwi(model_type=model_type)

    def tokenize(self, text: str):
        return self.kiwi.tokenize(text, typos=self.typos)

