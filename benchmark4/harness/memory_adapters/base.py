from abc import ABC, abstractmethod


class MemoryAdapter(ABC):
    @abstractmethod
    def ingest(self, events): ...

    @abstractmethod
    def retrieve(self, query, limit=10): ...

    @abstractmethod
    def dump_memories(self): ...
