"""Desktop agent package (BIG #2).

Standalone local process: polls the coordinator (outbound only),
claims approved desktop actions, revalidates approval, executes via
the local backend, and reports results. No inbound server, no port
forwarding, no coordinator-side input ever.
"""

__version__ = "0.1.0"
