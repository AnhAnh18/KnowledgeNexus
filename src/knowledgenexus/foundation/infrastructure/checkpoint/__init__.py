"""Private checkpoint persistence seam (wired by the lock-owning stage)."""

# Deliberately no public exports: callers use the private adapter module or
# the lock-owning factory seam, preserving the M7 architecture boundary.
__all__: list[str] = []
