class TransientStepError(Exception):
    """A step-level failure worth retrying (slow render, brief hiccup)."""