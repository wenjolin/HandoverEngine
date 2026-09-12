from enum import Enum


class JobStatus(str, Enum):
    queued = "queued"
    ingesting = "ingesting"
    indexing = "indexing"
    extracting = "extracting"
    planning = "planning"
    curriculum = "curriculum"
    writing_quizzes = "writing_quizzes"
    validating = "validating"
    rendering = "rendering"
    exporting_pdf = "exporting_pdf"
    packaging = "packaging"
    done = "done"
    failed = "failed"


class CardCategory(str, Enum):
    overview = "overview"
    architecture = "architecture"
    module = "module"
    runbook = "runbook"
    business_rule = "business_rule"
    pitfall = "pitfall"
    dependency = "dependency"


class Importance(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class DayBlockType(str, Enum):
    goal = "goal"
    reading = "reading"
    checklist = "checklist"
    diagram = "diagram"
    note = "note"


class DayProgressStatus(str, Enum):
    unread = "unread"
    reading = "reading"
    passed = "passed"
    failed = "failed"


class GapStatus(str, Enum):
    unresolved = "unresolved"
    confirmed = "confirmed"
    resolved = "resolved"
