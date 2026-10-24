"""Readiness of the process-owned job delivery task."""

from dataclasses import dataclass


@dataclass
class JobDeliveryStatus:
    enabled: bool
    ready: bool = False
    failed: bool = False
    stopping: bool = False

    @property
    def healthy(self) -> bool:
        return not self.enabled or (self.ready and not self.failed and not self.stopping)
