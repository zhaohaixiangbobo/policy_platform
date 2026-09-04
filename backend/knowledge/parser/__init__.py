"""文件说明：公开制度DOCX解析和ParseRun审核能力。"""

from .ooxml import ImageReviewRequiredError
from .pipeline import ParserConfig, PolicyParserPipeline

__all__ = ["ImageReviewRequiredError", "ParserConfig", "PolicyParserPipeline"]
