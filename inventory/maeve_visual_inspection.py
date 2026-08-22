from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit


VERDICTS = {"looks_good", "possible_problem", "unable_to_verify"}
ISSUES = {"first_layer", "warp", "spaghetti", "separation", "unknown"}


@dataclass(frozen=True)
class ExternalCameraSource:
    """Disabled-by-default, read-only source definition for future Maeve vision."""

    enabled: bool = False
    stream_url: str | None = None

    def validate(self) -> None:
        if not self.enabled:
            if self.stream_url is not None:
                raise ValueError("disabled camera source must not retain a stream URL")
            return
        if not self.stream_url:
            raise ValueError("enabled camera source requires a private stream URL")
        parsed = urlsplit(self.stream_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("camera source must use HTTP or HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("camera credentials and tokens must not appear in the URL")
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError as exc:
            raise ValueError("camera source must use a verified private IP address") from exc
        if not (address.is_private or address.is_loopback):
            raise ValueError("camera source must remain on a private local address")


@dataclass(frozen=True)
class VisualEvidence:
    usable_frames: int
    plate_visible: bool
    good_confidence: float
    problem_confidence: float
    issue: str = "unknown"


@dataclass(frozen=True)
class InspectionResult:
    verdict: str
    confidence: float
    issue: str
    control_capable: bool = False
    automatic_action: bool = False


class ReadOnlyVisualInspectionGate:
    """Converts future model evidence into conservative, non-controlling results."""

    def __init__(self, *, minimum_frames: int = 4, good_threshold: float = 0.90, problem_threshold: float = 0.80):
        self.minimum_frames = minimum_frames
        self.good_threshold = good_threshold
        self.problem_threshold = problem_threshold

    def decide(self, evidence: VisualEvidence) -> InspectionResult:
        if evidence.issue not in ISSUES:
            raise ValueError("unsupported visual issue category")
        for value in (evidence.good_confidence, evidence.problem_confidence):
            if not 0.0 <= value <= 1.0:
                raise ValueError("confidence must be between zero and one")
        if evidence.usable_frames < self.minimum_frames or not evidence.plate_visible:
            return InspectionResult("unable_to_verify", 0.0, evidence.issue)
        if evidence.problem_confidence >= self.problem_threshold:
            return InspectionResult("possible_problem", evidence.problem_confidence, evidence.issue)
        if evidence.good_confidence >= self.good_threshold and evidence.problem_confidence < self.problem_threshold:
            return InspectionResult("looks_good", evidence.good_confidence, evidence.issue)
        return InspectionResult("unable_to_verify", max(evidence.good_confidence, evidence.problem_confidence), evidence.issue)
