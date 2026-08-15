from __future__ import annotations

from enum import StrEnum


class SurfaceKind(StrEnum):
    BROWSER = "browser"
    WINDOWS = "windows"


class AgentDecisionState(StrEnum):
    CONTINUE = "CONTINUE"
    GOAL_COMPLETE = "GOAL_COMPLETE"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    BLOCKED = "BLOCKED"


class ActionType(StrEnum):
    NAVIGATE = "navigate"
    CLICK = "click"
    INPUT_TEXT = "input_text"
    SELECT_OPTION = "select_option"
    PRESS_KEY = "press_key"
    READ = "read"
    EXTRACT = "extract"
    SCROLL = "scroll"
    WAIT = "wait"


class RiskLevel(StrEnum):
    SAFE = "safe"
    REVERSIBLE_WRITE = "reversible_write"
    IRREVERSIBLE = "irreversible"


class ResolutionStrategyKind(StrEnum):
    SEMANTIC = "semantic"
    ATTRIBUTE = "attribute"
    TEXT_ANCHOR = "text_anchor"
    VISUAL_TEMPLATE = "visual_template"


class CheckpointType(StrEnum):
    CONTROL_PRESENT = "control_present"
    CONTROL_ABSENT = "control_absent"
    CONTROL_VALUE = "control_value"
    TEXT_PRESENT = "text_present"
    URL_MATCHES = "url_matches"
    DIALOG_PRESENT = "dialog_present"
    OUTPUT_EXTRACTABLE = "output_extractable"
    PAGE_STATE = "page_state"


class ExecutionStatus(StrEnum):
    SUCCESS = "SUCCESS"
    BUSINESS_OUTCOME = "BUSINESS_OUTCOME"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    FAILURE = "FAILURE"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ExecutionMode(StrEnum):
    DISCOVERY = "discovery"
    REPLAY = "replay"
    HANDOFF = "handoff"


class Actor(StrEnum):
    LLM = "llm"
    AUTOMATION = "automation"
    HUMAN = "human"


class PolicyDecisionType(StrEnum):
    ALLOW = "ALLOW"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    TAKEOVER_REQUIRED = "TAKEOVER_REQUIRED"
    DENY = "DENY"


class InterventionKind(StrEnum):
    APPROVAL = "APPROVAL"
    TAKEOVER = "TAKEOVER"


class ControlOwner(StrEnum):
    AUTOMATION = "AUTOMATION"
    HUMAN = "HUMAN"


class RunState(StrEnum):
    CREATED = "CREATED"
    AUTOMATING = "AUTOMATING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    HUMAN_CONTROL = "HUMAN_CONTROL"
    RESUMING = "RESUMING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ApprovalState(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    DEPRECATED = "deprecated"


class SchemaValueType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"