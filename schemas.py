"""Schema for the owner-authorized Antigravity control tool."""

ANTIGRAVITY_CONTROL = {
    "name": "antigravity_control",
    "description": (
        "Control the owner's already-running local Antigravity coding agent through loopback-only CDP. "
        "Use when the user asks to delegate coding to Antigravity, inspect its current conversation/progress, "
        "or stop its active run. The send action operates on the visible active Antigravity conversation and "
        "returns a postcondition-verified result. Permission prompts remain governed by the separate scoped approval bridge."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "send", "stop"],
                "description": "status reads current state; send submits a coding task; stop requests cancellation."
            },
            "task": {
                "type": "string",
                "description": "Complete task instruction for Antigravity. Required only for send."
            },
            "expected_conversation": {
                "type": "string",
                "description": "Optional exact active conversation title; mismatch fails closed."
            }
        },
        "required": ["action"]
    }
}
