"""sop-core package: SOP generation, CRUD, and runtime contracts."""

from sop_core.sop_loader import normalize_step_dict
from sop_core.sop_path_generator import SopPathGenerator

__all__ = ["SopPathGenerator", "normalize_step_dict"]
