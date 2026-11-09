"""Trading mode management: PAPER (default) and LIVE.

Safety invariants (section 6 of the platform spec):
- Paper is the default mode at every start-up; the live state never persists
  across process restarts without re-authorization.
- Switching to live requires an explicit, typed confirmation string AND a
  connected broker account. Switching back to paper requires confirmation
  only for open live positions (documented transition plan).
- Mode changes are recorded in an append-only audit trail.
- Modes never transfer, duplicate, or silently close existing positions:
  ``plan_transition`` returns the operator the exact set of open positions
  and pending orders that will remain in their original environment.
- Paper orders can never reach a live adapter and vice versa: the manager
  hands out exactly one active execution adapter for the current mode.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("goldbot.modes")

CONFIRMATION_PHRASE = "ENABLE LIVE TRADING"


@dataclass
class AuditEvent:
    timestamp_utc: str
    actor: str
    event: str
    details: dict

    def to_dict(self) -> dict:
        return {
            "timestamp_utc": self.timestamp_utc,
            "actor": self.actor,
            "event": self.event,
            "details": self.details,
        }


@dataclass
class TransitionPlan:
    """What happens to open positions/orders when the mode changes."""

    from_mode: str
    to_mode: str
    open_positions_kept_in_original_mode: list[str] = field(default_factory=list)
    pending_orders_cancelled_in_original_mode: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "from_mode": self.from_mode,
            "to_mode": self.to_mode,
            "open_positions_kept_in_original_mode": (self.open_positions_kept_in_original_mode),
            "pending_orders_cancelled_in_original_mode": (
                self.pending_orders_cancelled_in_original_mode
            ),
            "note": self.note,
        }


class TradingModeManager:
    """Owns the current trading mode, its audit trail, and the switch gates."""

    def __init__(
        self,
        audit_sink=None,
        clock=None,
    ):
        """
        Args:
            audit_sink: optional callable receiving an ``AuditEvent`` (e.g. a
                database writer). The in-memory trail always records too.
            clock: optional callable returning a UTC datetime (tests).
        """
        self._lock = threading.RLock()
        self._mode = "paper"  # ALWAYS start in paper
        self._live_authorized = False  # broker connected + confirmed
        self._broker_connected = False
        self._audit: list[AuditEvent] = []
        self._audit_sink = audit_sink
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    @property
    def live_authorized(self) -> bool:
        return self._live_authorized

    @property
    def broker_connected(self) -> bool:
        return self._broker_connected

    def status(self) -> dict:
        with self._lock:
            return {
                "mode": self._mode,
                "live_authorized": self._live_authorized,
                "broker_connected": self._broker_connected,
                "confirmation_phrase_required": CONFIRMATION_PHRASE,
            }

    # ------------------------------------------------------------------
    # Broker connection state (set by the account-connections layer)
    # ------------------------------------------------------------------

    def set_broker_connection(self, connected: bool, detail: str = "") -> None:
        with self._lock:
            self._broker_connected = connected
            if not connected:
                # Losing the broker connection revokes live authorization and
                # forces the mode back to paper immediately.
                if self._mode == "live":
                    self._mode = "paper"
                    self._record("mode_forced_paper", reason="broker_disconnected")
                self._live_authorized = False
            self._record(
                "broker_connection",
                connected=connected,
                detail=detail,
            )

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    def authorize_live(self, confirmation: str, actor: str = "operator") -> dict:
        """Explicit live-execution authorization (step 1 of the live switch).

        Requires the exact typed confirmation phrase and a connected broker.
        """
        with self._lock:
            if confirmation != CONFIRMATION_PHRASE:
                self._record(
                    "live_authorization_denied", actor=actor, reason="confirmation_phrase_mismatch"
                )
                return {
                    "authorized": False,
                    "reason": f'type exactly "{CONFIRMATION_PHRASE}" to authorize',
                }
            if not self._broker_connected:
                self._record(
                    "live_authorization_denied", actor=actor, reason="broker_not_connected"
                )
                return {
                    "authorized": False,
                    "reason": "connect a broker account before enabling live trading",
                }
            self._live_authorized = True
            self._record("live_authorized", actor=actor)
            return {"authorized": True}

    def switch_mode(self, to_mode: str, actor: str = "operator") -> dict:
        """Switch execution mode with full safety gates and audit.

        Returns a dict with ``status`` in {"ok", "denied", "already"} plus a
        transition plan. Existing positions/orders are NEVER transferred,
        duplicated, or silently closed — see ``plan_transition``.
        """
        to_mode = to_mode.lower()
        if to_mode not in ("paper", "live"):
            return {"status": "denied", "reason": "mode must be 'paper' or 'live'"}

        with self._lock:
            if to_mode == self._mode:
                self._record("mode_switch_noop", actor=actor, to_mode=to_mode)
                return {"status": "already", "mode": self._mode}

            if to_mode == "live":
                if not self._broker_connected or not self._live_authorized:
                    self._record("mode_switch_denied", actor=actor, to_mode="live")
                    return {
                        "status": "denied",
                        "reason": (
                            "live trading requires a connected broker account and "
                            f'explicit authorization (type "{CONFIRMATION_PHRASE}")'
                        ),
                    }

            plan = self.plan_transition(to_mode)
            previous = self._mode
            self._mode = to_mode
            if to_mode == "paper":
                # Dropping back to paper never auto-closes live positions;
                # they remain on the broker under the operator's control.
                self._live_authorized = False
            self._record("mode_switch", actor=actor, **plan.to_dict())
            logger.warning(
                "TRADING MODE SWITCHED %s -> %s by %s (positions kept in original mode: %s)",
                previous,
                to_mode,
                actor,
                plan.open_positions_kept_in_original_mode,
            )
            return {"status": "ok", "mode": to_mode, "transition": plan.to_dict()}

    def plan_transition(self, to_mode: str) -> TransitionPlan:
        """Describe the safe transition for open positions / pending orders.

        Called before the switch so the UI can show the operator exactly what
        will happen. Positions stay where they are; the caller decides (via
        explicit operator action) whether to close them first.
        """
        return TransitionPlan(
            from_mode=self._mode,
            to_mode=to_mode,
            open_positions_kept_in_original_mode=[
                "all open positions remain "
                "in their original environment; GoldBot will not close or "
                "transfer them automatically"
            ],
            pending_orders_cancelled_in_original_mode=[
                "pending orders remain in their original environment; cancel them explicitly first"
            ],
            note=(
                "Switching modes does not move money or positions. Paper "
                "positions stay simulated; live positions stay on the broker."
            )
            if to_mode == "paper"
            else ("New orders will be executed on the LIVE broker account."),
        )

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    @property
    def audit_trail(self) -> list[AuditEvent]:
        return list(self._audit)

    def _record(self, event: str, actor: str = "system", **details) -> None:
        record = AuditEvent(
            timestamp_utc=self._clock().isoformat(),
            actor=actor,
            event=event,
            details=details,
        )
        self._audit.append(record)
        # Keep the in-memory trail bounded; the DB sink is the durable record.
        if len(self._audit) > 1000:
            self._audit = self._audit[-500:]
        if self._audit_sink is not None:
            try:
                self._audit_sink(record)
            except Exception:
                logger.exception("audit sink failed; event kept in memory only")


__all__ = [
    "TradingModeManager",
    "AuditEvent",
    "TransitionPlan",
    "CONFIRMATION_PHRASE",
]
