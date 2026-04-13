from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _read_bool(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "y"}


def _read_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def detect_node_root(explicit: str | Path | None = None) -> Path | None:
    if explicit:
        return Path(explicit).expanduser().resolve()

    configured = str(os.getenv("HERMES_NODE_ROOT", "") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    hermes_home = str(os.getenv("HERMES_HOME", "") or "").strip()
    if hermes_home:
        home_path = Path(hermes_home).expanduser().resolve()
        if home_path.name == ".hermes":
            return home_path.parent

    local_root = Path("/local")
    if local_root.exists():
        return local_root
    return None


@dataclass(frozen=True)
class WikiSettings:
    enabled: bool
    wiki_root: Path
    plugin_root: Path
    seed_root: Path
    current_node: str
    max_writes_per_agent_per_hour: int
    max_new_pages_per_day: int
    max_page_bytes: int
    max_pages_per_query: int
    max_summary_layers: int
    max_graph_hops: int
    max_raw_evidence_reads: int
    max_token_target: int
    doctrine_min_frequency: int
    ecd_min_frequency: int
    large_page_line_threshold: int
    outdated_after_days: int
    page_split_line_threshold: int
    proposal_lock_timeout_sec: int

    @property
    def indexes_root(self) -> Path:
        return self.wiki_root / "indexes"

    @property
    def meta_root(self) -> Path:
        return self.wiki_root / "meta"

    @property
    def graph_root(self) -> Path:
        return self.meta_root / "graph"

    @property
    def compression_root(self) -> Path:
        return self.meta_root / "compression"

    @property
    def proposals_root(self) -> Path:
        return self.meta_root / "proposals"

    @property
    def queues_root(self) -> Path:
        return self.meta_root / "queues"

    @property
    def history_root(self) -> Path:
        return self.meta_root / "history"

    @property
    def observability_root(self) -> Path:
        return self.meta_root / "observability"

    @property
    def health_reports_root(self) -> Path:
        return self.meta_root / "health_reports"

    @property
    def self_heal_root(self) -> Path:
        return self.meta_root / "self_heal"

    @property
    def doctrine_root(self) -> Path:
        return self.meta_root / "doctrine_candidates"

    @property
    def refactor_root(self) -> Path:
        return self.meta_root / "refactor_reports"

    @property
    def emergence_root(self) -> Path:
        return self.meta_root / "emergence_reports"

    @property
    def queue_lock_path(self) -> Path:
        return self.queues_root / "commit.lock"


def load_settings() -> WikiSettings:
    plugin_root = Path(__file__).resolve().parents[1]
    wiki_root = Path(
        str(os.getenv("HERMES_WIKI_ROOT", "") or "").strip()
        or "/local/agents/private/shared/wiki"
    ).expanduser()
    current_node = str(os.getenv("NODE_NAME", "") or "").strip()

    return WikiSettings(
        enabled=_read_bool("NODE_WIKI_ENABLED", False),
        wiki_root=wiki_root,
        plugin_root=plugin_root,
        seed_root=plugin_root / "wiki_seed",
        current_node=current_node,
        max_writes_per_agent_per_hour=_read_int("NODE_WIKI_MAX_WRITES_PER_AGENT_PER_HOUR", 12),
        max_new_pages_per_day=_read_int("NODE_WIKI_MAX_NEW_PAGES_PER_DAY", 8),
        max_page_bytes=_read_int("NODE_WIKI_MAX_PAGE_BYTES", 120_000),
        max_pages_per_query=_read_int("NODE_WIKI_MAX_PAGES_PER_QUERY", 4),
        max_summary_layers=_read_int("NODE_WIKI_MAX_SUMMARY_LAYERS", 2),
        max_graph_hops=_read_int("NODE_WIKI_MAX_GRAPH_HOPS", 2),
        max_raw_evidence_reads=_read_int("NODE_WIKI_MAX_RAW_EVIDENCE_READS", 1),
        max_token_target=_read_int("NODE_WIKI_MAX_TOKEN_TARGET", 1_800),
        doctrine_min_frequency=_read_int("NODE_WIKI_DOCTRINE_MIN_FREQUENCY", 3),
        ecd_min_frequency=_read_int("NODE_WIKI_ECD_MIN_FREQUENCY", 3),
        large_page_line_threshold=_read_int("NODE_WIKI_LARGE_PAGE_LINE_THRESHOLD", 220),
        outdated_after_days=_read_int("NODE_WIKI_OUTDATED_AFTER_DAYS", 90),
        page_split_line_threshold=_read_int("NODE_WIKI_PAGE_SPLIT_LINE_THRESHOLD", 260),
        proposal_lock_timeout_sec=_read_int("NODE_WIKI_PROPOSAL_LOCK_TIMEOUT_SEC", 30),
    )
