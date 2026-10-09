from abc import ABC, abstractmethod
from core.models import SourceProduct

class Source(ABC):
    name = "base"

    @abstractmethod
    def fetch(self) -> list[SourceProduct]:
        raise NotImplementedError
