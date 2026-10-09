from abc import ABC, abstractmethod

class Destination(ABC):
    name = "base"

    @abstractmethod
    def publish(self, products):
        raise NotImplementedError
