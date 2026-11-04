"""Task registry: importing this module registers every task on `sia.worker.app`.

Feature modules define their tasks next to their own code; list them here.
"""

from sia.modules.enrichment import tasks as enrichment_tasks

__all__ = ["enrichment_tasks"]
