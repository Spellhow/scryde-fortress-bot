"""Protocol implemented by source-specific normalizers."""
from typing import Protocol, Sequence
from community.models import Event, World


class SourceAdapter(Protocol):
    source_id: str

    def parse(self, payload: object, *, world: World) -> Sequence[Event]:
        """Normalize an already-fetched source payload."""
        ...
